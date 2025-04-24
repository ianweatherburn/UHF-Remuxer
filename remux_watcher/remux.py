import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
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
        """Execute ffmpeg command to remux TS to MKV with enhanced metadata."""
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Extract metadata from recording info
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
        
        # Current time for encoded_date
        current_time = datetime.now().isoformat()
        
        # Format comment
        comment = f"""Original Title: {recording_id}
    Start Time: {start_time_str}
    Duration: {duration_seconds}
    End Time: {end_time_str}
    Status: {status}"""
        
        # Build ffmpeg command with metadata
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output if exists
            "-i", str(input_path),
            "-c", "copy",  # Copy streams without re-encoding
            "-metadata", f"title={name}",
            "-metadata", f"publisher={description}",
            "-metadata", "genre=TV-Show",
            "-metadata", f"description={description}-{name}",
            "-metadata", "language=eng",
            "-metadata", f"creation_time={start_time_str}",
            "-metadata", f"encoded_date={current_time}",
            "-metadata", f"comment={comment}",
            str(output_path)
        ]
        
        try:
            # Run ffmpeg process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for process to complete
            stdout, stderr = await process.communicate()
            
            # Check if process succeeded
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr.decode().strip()}")
                return False
            
            return True
        except Exception as e:
            logger.exception(f"Error executing ffmpeg: {e}")
            return False
