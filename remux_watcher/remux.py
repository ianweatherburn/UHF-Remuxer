import asyncio
import ffmpeg
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from textwrap import dedent
from datetime import datetime, timedelta

from remux_watcher.config import Config
from remux_watcher.database import DatabaseManager, RemuxStatus

logger = logging.getLogger(__name__)

class RemuxManager:
    def __init__(self, config: Config, db_manager: DatabaseManager, dry_run: bool = False):
        """Initialize the remux manager.
        
        Args:
            config: Application configuration
            db_manager: Database manager instance
            dry_run: Whether to run in dry-run mode
        """
        self.config = config
        self.db_manager = db_manager
        self.dry_run = dry_run
        self._active_jobs = 0
        self._job_semaphore = asyncio.Semaphore(config.max_jobs)
    

    async def remux_file(self, job_id: int, input_path: Path, output_path: Path, recording_info: Dict) -> bool:
        """Remux a TS file to MKV."""
        # Acquire semaphore to limit concurrent jobs
        async with self._job_semaphore:
            try:
                self.db_manager.update_remux_status(job_id, RemuxStatus.STARTED)
                
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would execute ffmpeg on {input_path.name}")
                    await asyncio.sleep(1)  # Simulate processing
                    success = True
                else:
                    logger.info(f"Starting remux of {input_path.name} to {output_path.name}")
                    success = await self._execute_ffmpeg(input_path, output_path, recording_info)
                
                if success:
                    # Set file ownership
                    if not self.dry_run:
                        try:
                            os.chown(output_path, self.config.puid, self.config.pgid)
                            
                            # Also set ownership on parent directory
                            os.chown(output_path.parent, self.config.puid, self.config.pgid)
                        except Exception as e:
                            logger.warning(f"Failed to change ownership of {output_path}: {e}")
                    
                    # Extract the remux duration and update the remux database
                    duration = await self._get_mkv_duration(output_path)
                    if duration > 0:
                        self.db_manager.update_remux_duration(job_id, duration)
                    else:
                        logger.warning(f"Failed to extract duration for {output_path.name}, skipping database update")

                    # Remux complete
                    self.db_manager.update_remux_status(job_id, RemuxStatus.COMPLETED)
                    logger.info(f"Successfully remuxed {input_path.name} to {output_path.name}")
                else:
                    self.db_manager.update_remux_status(
                        job_id, 
                        RemuxStatus.FAILED, 
                        error="FFmpeg process failed"
                    )
                    logger.error(f"Failed to remux {input_path.name}")
                
                return success
            except Exception as e:
                error_msg = f"Error remuxing {input_path.name}: {str(e)}"
                logger.exception(error_msg)
                self.db_manager.update_remux_status(job_id, RemuxStatus.FAILED, error=error_msg)
                return False
    
    async def _execute_ffmpeg(self, input_path: Path, output_path: Path, recording_info: Dict) -> bool:
        """Execute FFmpeg to remux a TS file to MKV with metadata."""
        try:

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Get metadata values from recording_info
            name = recording_info.get("name", "Unknown")
            description = recording_info.get("description", "")
            recording_id = recording_info.get("id", "")
            start_time_str = recording_info.get("start_time", "")
            duration_seconds = recording_info.get("duration_seconds", 0)
            status = recording_info.get("status", "")

            # Calculate end time
            try:
                if start_time_str:
                    # Parse start time
                    if '+' in start_time_str:
                        start_time = datetime.fromisoformat(start_time_str)
                    else:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        
                    # Calculate end time
                    end_time = start_time + timedelta(seconds=duration_seconds)
                    end_time_str = end_time.isoformat()
                else:
                    start_time_str = "unknown"
                    end_time_str = "unknown"
            except ValueError:
                logger.warning(f"Invalid date format in recording: {start_time_str}")
                start_time_str = "unknown"
                end_time_str = "unknown"

            # Format comment
            comment = " | ".join([
                f"Original Title: {recording_id}",
                f"Recording: {start_time_str} - {end_time_str}",
                f"Duration: {duration_seconds} seconds",
                f"Status: {status}",
                "Source: UHF-Server (https://www.uhfapp.com/)"
            ]).replace('"', "'")  # Replace double quotes with single quotes

            # Build FFmpeg command using the more reliable .global_args() approach
            stream = ffmpeg.input(str(input_path))
            stream = ffmpeg.output(
                stream,
                str(output_path),
                c="copy",
                y=None,
                **{
                    'metadata:g:0': f"title={name}",
                    'metadata:g:1': f"publisher={description}",
                    'metadata:g:2': "genre=TV-Show",
                    'metadata:g:3': f"description={description}-{name}",
                    'metadata:g:4': "language=eng",
                    'metadata:g:5': f"creation_time={start_time_str}",
                    'metadata:g:6': f"encoded_date={datetime.now().isoformat()}",
                    'metadata:g:7': f"comment={comment}"
                }
            )

            # Run FFmpeg in an executor to handle synchronous call
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(
                    None,
                    lambda: ffmpeg.run(
                        stream,
                        capture_stdout=True,
                        capture_stderr=True,
                        quiet=True
                    )
                )
                return True
            except ffmpeg.Error as e:
                logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
                return False

        except Exception as e:
            logger.exception(f"Error executing FFmpeg: {e}")
            return False    

    async def _get_mkv_duration(self, file_path: Path) -> float:
        """Extract the duration of an MKV file using FFprobe."""
        try:
            probe = ffmpeg.probe(str(file_path), v="error", show_entries="format=duration", of="json")
            duration = float(probe["format"].get("duration", 0))
            # logger.info(f"Extracted duration {duration} seconds for {file_path.name}")
            return duration
        except ffmpeg.Error as e:
            logger.error(f"FFprobe failed for {file_path.name}: {e.stderr.decode() if e.stderr else str(e)}")
            return 0.0
        except Exception as e:
            logger.error(f"Error probing duration for {file_path.name}: {str(e)}")
            return 0.0    

                 
