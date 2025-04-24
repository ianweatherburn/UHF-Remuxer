import json
import logging
import time
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import aiofiles
from tinydb import TinyDB, Query
from remux_watcher.config import Config

logger = logging.getLogger(__name__)

class RemuxStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class PlexUpdateStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RecordingStatus(str, Enum):
    RECORDING = "recording"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DatabaseManager:
    def __init__(
        self, 
        config: Config):
        # app_db_path: Path = None, 
        # recordings_db_path: Path = None):
        """Initialize the database manager.
        
        Args:
            app_db_path: Path to the application database
            recordings_db_path: Path to the recordings database (db.json)
        """
        app_db_path = Path(config.destination_folder) / config.remux_file
        recordings_db_path = Path(config.db_path) / config.db_file

        self.app_db = TinyDB(app_db_path)
        os.chown(app_db_path, config.puid, config.pgid)
        os.chmod(app_db_path, 0o660)         

        self.recordings_db_path = recordings_db_path
        self.recordings_cache = {}
        self.cache_timestamp = 0
        self.cache_ttl = 30  # Cache TTL in seconds
        
    async def get_recording_info(self, file_path: str) -> Optional[Dict]:
        """Get recording info from db.json for the given file path."""
        await self._refresh_recordings_cache_if_needed()
        
        for recording_id, recording in self.recordings_cache.get("recordings", {}).items():
            if recording.get("file_path") == file_path:
                return recording
        
        return None
    
    async def _refresh_recordings_cache_if_needed(self) -> None:
        """Refresh the recordings cache if it's expired."""
        current_time = time.time()
        if current_time - self.cache_timestamp > self.cache_ttl:
            await self._refresh_recordings_cache()
    
    async def _refresh_recordings_cache(self) -> None:
        """Refresh the recordings cache from db.json."""
        try:
            if not self.recordings_db_path.exists():
                logger.warning(f"Recordings database file not found: {self.recordings_db_path}")
                self.recordings_cache = {}
                return
                
            async with aiofiles.open(self.recordings_db_path, "r") as f:
                content = await f.read()
                self.recordings_cache = json.loads(content)
                self.cache_timestamp = time.time()
                logger.debug(f"Refreshed recordings cache with {len(self.recordings_cache.get('recordings', {}))} recordings")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading recordings database: {e}")
            self.recordings_cache = {}
    
    def is_recording_complete(self, recording_info: Dict) -> bool:
        """Check if a recording is complete based on its status."""
        status = recording_info.get("status", "").lower()
        return status != "recording"
    
    def add_remux_job(self, 
                      original_path: str, 
                      output_path: str, 
                      recording_info: Dict) -> int:
        """Add a remux job to the database."""
        jobs = self.app_db.table("remux_jobs")
        
        # Check if we already have this job
        Job = Query()
        existing_job = jobs.get(Job.original_path == original_path)
        if existing_job:
            logger.debug(f"Job already exists for {original_path}")
            return existing_job.doc_id
        
        # Create new job
        job_id = jobs.insert({
            "original_path": original_path,
            "output_path": output_path,
            "recording_name": recording_info.get("name", ""),
            "recording_description": recording_info.get("description", ""),
            "created_at": recording_info.get("created_at", ""),
            "remux_status": RemuxStatus.PENDING.value,
            "remux_started_at": None,
            "remux_completed_at": None,
            "plex_update_status": PlexUpdateStatus.PENDING.value,
            "plex_update_completed_at": None,
            "error": None
        })
        
        logger.info(f"Created new remux job {job_id} for {original_path}")
        return job_id
    
    def update_remux_status(self, job_id: int, status: RemuxStatus, error: str = None) -> None:
        """Update the remux status for a job."""
        jobs = self.app_db.table("remux_jobs")
        
        update_data = {"remux_status": status.value}
        
        if status == RemuxStatus.STARTED:
            update_data["remux_started_at"] = datetime.now().isoformat()
        elif status in (RemuxStatus.COMPLETED, RemuxStatus.FAILED):
            update_data["remux_completed_at"] = datetime.now().isoformat()
            
        if error:
            update_data["error"] = error
            
        jobs.update(update_data, doc_ids=[job_id])
        logger.debug(f"Updated job {job_id} remux status to {status.value}")
    
    def update_plex_status(self, job_id: int, status: PlexUpdateStatus, error: str = None) -> None:
        """Update the Plex update status for a job."""
        jobs = self.app_db.table("remux_jobs")
        
        update_data = {
            "plex_update_status": status.value,
            "plex_update_completed_at": datetime.now().isoformat()
        }
        
        if error:
            update_data["error"] = error
            
        jobs.update(update_data, doc_ids=[job_id])
        logger.debug(f"Updated job {job_id} Plex status to {status.value}")
    
    def get_pending_jobs(self) -> List[Dict]:
        """Get all pending remux jobs."""
        jobs = self.app_db.table("remux_jobs")
        Job = Query()
        return jobs.search(Job.remux_status == RemuxStatus.PENDING.value)
    
    def is_file_processed(self, file_path: str) -> bool:
        """Check if a file has already been processed."""
        jobs = self.app_db.table("remux_jobs")
        Job = Query()
        return bool(jobs.get(Job.original_path == file_path))
