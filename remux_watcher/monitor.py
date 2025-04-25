import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime, timedelta

from remux_watcher.config import Config
from remux_watcher.database import DatabaseManager, RemuxStatus
from remux_watcher.plex import PlexManager
from remux_watcher.remux import RemuxManager

logger = logging.getLogger(__name__)

class FileMonitor:
    def __init__(self, config: Config, dry_run: bool = False):
        """Initialize the file monitor.
        
        Args:
            config: Application configuration
            dry_run: Whether to run in dry-run mode
        """
        self.config = config
        self.dry_run = dry_run
        
        # Initialize database manager
        self.db_manager = DatabaseManager(config=config)
        
        # Initialize remux manager
        self.remux_manager = RemuxManager(
            config=config,
            db_manager=self.db_manager,
            dry_run=dry_run
        )
        
        # Initialize Plex manager (if configured)
        if config.plex_url and config.plex_token and config.plex_library:
            self.plex_manager = PlexManager(
                config=config,
                url=config.plex_url,
                token=config.plex_token,
                library=config.plex_library,
                dry_run=dry_run
            )
        else:
            self.plex_manager = None
            if not dry_run:
                logger.warning("Plex integration disabled due to missing configuration")
    
    async def start_monitoring(self) -> None:
        """Start monitoring for files to remux."""
        logger.info(f"Starting monitoring of {self.config.watch_folder}")
        
        while True:
            try:
                # Check if we should process files based on the current minute
                current_minute = datetime.now().minute
                valid_intervals = [1, 2, 5, 10, 15, 20, 30, 45, 55]
                interval = self.config.interval
                
                # Check if current minute is a multiple of the interval or is in valid_intervals
                if interval in valid_intervals and current_minute % interval == 0:
                    logger.info(f"Checking for files at interval {interval} (minute: {current_minute})")
                    
                    # Find all TS files in the watch folder
                    ts_files = self._find_ts_files()
                    logger.debug(f"Found {len(ts_files)} TS files in watch folder")
                    
                    # Process each file
                    tasks = []
                    for file_path in ts_files:
                        tasks.append(self._process_file(file_path))
                    
                    # Wait for all processing tasks to complete
                    if tasks:
                        await asyncio.gather(*tasks)
                
                # Wait for the next minute to check again
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.exception(f"Error monitoring files: {e}")
                await asyncio.sleep(1)
    
    def _find_ts_files(self) -> List[Path]:
        """Find all TS files in the watch folder."""
        results = []
        try:
            for entry in self.config.watch_folder.glob("*.ts"):
                if entry.is_file():
                    results.append(entry)
        except Exception as e:
            logger.error(f"Error scanning watch folder: {e}")
        
        return results
    
    async def _process_file(self, file_path: Path) -> None:
        """Process a TS file."""
        # Skip if already processed
        if self.db_manager.is_file_processed(str(file_path)):
            logger.debug(f"Skipping already processed file: {file_path.name}")
            return
            
        logger.info(f"Processing file: {file_path.name}")
        
        # Get recording info from db.json
        recording_info = await self.db_manager.get_recording_info(str(file_path))
        
        if not recording_info:
            logger.warning(f"No recording info found for {file_path.name}")
            return
            
        # Check if we are including cancelled recordings
        # logger.info(f"IAN: Include Cancelled? {self.config.include_cancelled}  Recording Cancelled? {self.db_manager.is_recording_cancelled(recording_info)}")
        # logger.info(f"If we are not including cancelled AND this recording is cancelled we should see a SKIP message?")
        if not self.config.include_cancelled and self.db_manager.is_recording_cancelled(recording_info):
            logger.info(f"Skipping cancelled recordings as requested: {file_path.name}")
            return

        # Check if recording is complete
        if self.db_manager.is_recording(recording_info):
            logger.info(f"Skipping active recording: {file_path.name}")
            return

        # Get formatted output path
        folder_name, output_filename = self._format_output_path(recording_info)
        output_folder = self.config.destination_folder / folder_name
        output_path = output_folder / output_filename
        relative_output = output_folder.relative_to(self.config.destination_folder)
        plex_folder = self.config.plex_folder / relative_output        

        # logger.info(f"Output Path: {output_path}")
        # logger.info(f"Plex Folder: {plex_folder}")
        
        # Create folder if it doesn't exist
        output_folder.mkdir(exist_ok=True, parents=True)
        
        # Add job to database
        job_id = self.db_manager.add_remux_job(
            original_path=str(file_path),
            output_path=str(output_path),
            recording_info=recording_info
        )
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would remux {file_path.name} to {folder_name}/{output_filename}")
            return
            
        # Start remux process
        success = await self.remux_manager.remux_file(job_id, file_path, output_path, recording_info)
        
        # Update Plex if remux was successful and Plex is configured
        if success and self.plex_manager:
            await self.plex_manager.update_library(job_id, output_path, plex_folder, recording_info)

    
    def _format_output_filename(self, recording_info: Dict) -> str:
        """Format an output filename based on recording info."""
        # Get components from recording info
        name = recording_info.get("name", "Unknown")
        description = recording_info.get("description", "")
        
        # Parse and format created_at timestamp
        created_at = recording_info.get("created_at", "")
        try:
            if created_at:
                # Handle both timestamp formats (with and without timezone)
                if '+' in created_at:
                    dt = datetime.fromisoformat(created_at)
                else:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                date_formatted = dt.strftime("%Y%m%d%H%M%S")
            else:
                date_formatted = "unknown_date"
        except ValueError:
            logger.warning(f"Invalid date format in recording: {created_at}")
            date_formatted = "unknown_date"
        
        # Clean up components for safe filenames
        name = self._clean_filename(name)
        description = self._clean_filename(description)
        
        # Construct final filename
        return f"{name}-{description}-{date_formatted}.mkv"
    
    def _clean_filename(self, name: str) -> str:
        """Clean a string to be used in a filename."""
        # Replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Remove leading/trailing spaces and dots
        name = name.strip(' .')
        
        # If name is empty, use a placeholder
        if not name:
            name = "unnamed"
            
        return name

    def _format_output_path(self, recording_info: Dict) -> tuple:
        """Format output folder and filename based on recording info."""
        # Get name for folder
        folder_name = self._clean_filename(recording_info.get("description", "Unknown"))
        file_name = self._clean_filename(recording_info.get("name", "Unknown"))
        
        # Parse start time
        start_time_str = recording_info.get("start_time", "")
        duration_seconds = int(recording_info.get("duration_seconds", 0))
        
        try:
            if start_time_str:
                # Parse start time and adjust for timezone
                if '+' in start_time_str:
                    start_time = datetime.fromisoformat(start_time_str)
                else:
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                
                # Calculate end time
                end_time = start_time + timedelta(seconds=duration_seconds)
                
                # Format date and times for filename
                date_formatted = start_time.strftime("%Y-%m-%d")
                start_time_formatted = start_time.strftime("%H:%M")
                end_time_formatted = end_time.strftime("%H:%M")
                
                # Construct filename
                filename = f"{file_name}_{date_formatted}_{start_time_formatted}-{end_time_formatted}.mkv"
            else:
                # Fallback if no valid start time
                filename = f"{file_name}_unknown_time.mkv"
        except ValueError:
            logger.warning(f"Invalid date format in recording: {start_time_str}")
            filename = f"{file_name}_invalid_time.mkv"
        
        return folder_name, filename        
