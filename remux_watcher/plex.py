import logging
import time
from pathlib import Path
from urllib.parse import quote
from typing import Dict, Optional
import aiohttp
from datetime import datetime
from typing import Dict, Optional
import asyncio

from remux_watcher.database import PlexUpdateStatus
from remux_watcher.config import Config

logger = logging.getLogger(__name__)

class PlexManager:
    def __init__(self, config: Config, url: str, token: str, library: str, dry_run: bool = False, scan_count_limit: int = 30):
        """Initialize the Plex manager."""
        self.config = config
        self.base_url = url.rstrip('/')
        self.token = token
        self.library_name = library
        self.dry_run = dry_run
        self.library_section_id = None
        self.scan_count_limit = scan_count_limit
    
    async def update_library(self, job_id: int, file_path: Path, plex_folder: Path, recording_info: Dict) -> bool:
        """Update Plex library after a successful remux."""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would update Plex library for {file_path.name}")
                return True
                
            # Get library section ID if not already cached
            if self.library_section_id is None:
                self.library_section_id = await self._get_library_section_id()
                if self.library_section_id is None:
                    logger.error(f"Failed to find Plex library: {self.library_name}")
                    from remux_watcher.database import DatabaseManager
                    DatabaseManager(self.config).update_plex_status(
                        job_id, 
                        PlexUpdateStatus.FAILED,
                        error=f"Library '{self.library_name}' not found"
                    )
                    return False
            
            # Wait for Plex to not be scanning
            scanning = await self._wait_for_plex_not_scanning()
            if not scanning:
                logger.warning("Plex scan status couldn't be determined or timed out")
            
            # Update library for the specific file
            result = await self._refresh_library_path(plex_folder)
            
            if result:
                # Wait a bit for Plex to process the file
                await asyncio.sleep(3)
                
                # Update metadata for the newly added item
                metadata_result = await self._update_item_metadata(file_path, plex_folder, recording_info)
                if not metadata_result:
                    logger.warning(f"Failed to update metadata for {file_path.name}")
            
            # Update database with result
            from remux_watcher.database import DatabaseManager
            if result:
                DatabaseManager(self.config).update_plex_status(job_id, PlexUpdateStatus.COMPLETED)
            else:
                DatabaseManager(self.config).update_plex_status(
                    job_id, 
                    PlexUpdateStatus.FAILED,
                    error="Failed to update Plex library"
                )
            
            return result
        except Exception as e:
            logger.exception(f"Error updating Plex library: {e}")
            from remux_watcher.database import DatabaseManager
            DatabaseManager(self.config).update_plex_status(
                job_id, 
                PlexUpdateStatus.FAILED,
                error=str(e)
            )
            return False

    async def _get_library_section_id(self) -> Optional[str]:
        """Get the section ID for the configured library name."""
        url = f"{self.base_url}/library/sections"
        headers = {"X-Plex-Token": self.token}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch Plex libraries: {response.status}")
                        return None
                    
                    # Parse XML response
                    text = await response.text()
                    
                    # Simple XML parsing for this specific case
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(text)
                    
                    for directory in root.findall(".//Directory"):
                        title = directory.get("title")
                        section_id = directory.get("key")
                        
                        if title == self.library_name:
                            logger.info(f"Found Plex library '{title}' with ID {section_id}")
                            return section_id
                    
                    logger.warning(f"Plex library '{self.library_name}' not found")
                    return None
        except Exception as e:
            logger.exception(f"Error getting Plex library sections: {e}")
            return None            
    
    async def _wait_for_plex_not_scanning(self) -> bool:
        """Wait for Plex to not be in a scanning state."""
        for attempt in range(self.scan_count_limit):
            scanning = await self._is_plex_scanning()
            if scanning is None:
                logger.warning("Couldn't determine Plex scanning status")
                return False
            
            if not scanning:
                logger.debug("Plex is not currently scanning")
                return True
            
            logger.debug(f"Plex is scanning, waiting (attempt {attempt+1}/{self.scan_count_limit})")
            await asyncio.sleep(2)
        
        logger.warning(f"Timed out waiting for Plex to finish scanning after {self.scan_count_limit} attempts")
        return False
    
    async def _is_plex_scanning(self) -> Optional[bool]:
        """Check if Plex is currently scanning."""
        url = f"{self.base_url}/library/sections/{self.library_section_id}"
        headers = {"X-Plex-Token": self.token}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to check Plex scanning status: {response.status}")
                        return None
                    
                    # Parse XML response
                    text = await response.text()
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(text)
                    
                    # Check if scanning attribute exists and is "1"
                    directory = root.find(".//Directory")
                    if directory is not None:
                        scanning = directory.get("scanning")
                        return scanning == "1"
                    
                    return False
        except Exception as e:
            logger.exception(f"Error checking Plex scanning status: {e}")
            return None
    
    async def _refresh_library_path(self, plex_folder: Path) -> bool:
        """Refresh a specific path in a Plex library section."""
        if self.library_section_id is None:
            logger.error("Cannot refresh library: section ID not known")
            return False

        # Use the fully qualified path for the file
        url = f"{self.base_url}/library/sections/{self.library_section_id}/refresh"
        logger.info(f"Plex Refresh: '{url}?path={plex_folder}'")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, 
                    params={"path": str(plex_folder), "X-Plex-Token": self.token}
                ) as response:
                    if response.status == 200:
                        logger.info(f"Successfully refreshed Plex library for path: {plex_folder}")
                        return True
                    else:
                        logger.error(f"Failed to refresh Plex library: {response.status}")
                        return False
        except Exception as e:
            logger.exception(f"Error refreshing Plex library: {e}")
            return False
    
    async def _update_item_metadata(self, file_path: Path, plex_folder: Path, recording_info: Dict) -> bool:
        """Update metadata for a Plex item."""
        try:
            # Find the item in Plex
            item_id = await self._find_plex_item(file_path, plex_folder)
            if not item_id:
                logger.warning(f"Couldn't find Plex item for '{file_path.name}'' in '{plex_folder}'")
                return False
            
            # Get metadata values
            name = recording_info.get("name", "")
            original_file = Path(recording_info.get("file_path", "")).name
            studio = recording_info.get("description", "")
            
            # Parse the start time
            start_time_str = recording_info.get("start_time", "")
            try:
                if start_time_str:
                    if '+' in start_time_str:
                        start_time = datetime.fromisoformat(start_time_str)
                    else:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    
                    # Format date and time for sort_title
                    sort_date = start_time.strftime("%Y%m%d%H%M%S")
                    available_date = start_time.strftime("%Y-%m-%d")
                else:
                    sort_date = "Unknown Date"
                    available_date = None
            except ValueError:
                logger.warning(f"Invalid date format in recording: {start_time_str}")
                sort_date = "Unknown Date"
                available_date = None
            
            params = {
                "X-Plex-Token": self.token,
                "type": "1",  # Type for videos
                "title.value": name,
                "titleSort.value": f"{sort_date}_{name}",
                "originalTitle.value": original_file,
                "studio": studio,
                # Optionally lock fields to prevent manual changes
                "title.locked": "1",
                "titleSort.locked": "1",
                "originalTitle.locked": "1",
                "studio.locked": "1"
            }
            
            # Add originally available date if we have it
            if available_date:
                params["originallyAvailableAt.value"] = available_date
                params["originallyAvailableAt.locked"] = "1"
            
            # Update the metadata
            url = f"{self.base_url}/library/metadata/{item_id}"
            async with aiohttp.ClientSession() as session:
                async with session.put(url, params=params) as response:
                    # logger.info(f"Updating Plex metadata for {file_path.name} with: "
                    #     f"title='{name}', titleSort='{sort_date}_{name}', "
                    #     f"originalTitle='{original_file}', availableAt='{available_date}'")

                    if response.status == 200:
                        logger.info(f"Successfully updated metadata for {file_path}")
                        return True
                    else:
                        logger.error(f"Failed to update metadata: {response.status}")
                        return False
        except Exception as e:
            logger.exception(f"Error updating item metadata: {e}")
            return False
    
    async def _find_plex_item(self, file_path: Path, plex_folder: Path) -> Optional[str]:
        """Find a Plex item by its file path."""

        # Get the fully-qualified file name without extension for better matching
        full_path =  plex_folder / file_path.name
        logger.info(f"Searching Plex for '{full_path}'")
        
        url = f"{self.base_url}/library/sections/{self.library_section_id}/all"
        headers = {"X-Plex-Token": self.token}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch Plex library items: {response.status}")
                        return None
                    
                    text = await response.text()
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(text)
                    
                    # Check each video element for matching file path
                    for video in root.findall(".//Video"):
                        media = video.find("./Media")
                        if media is not None:
                            part = media.find("./Part")
                            if part is not None:
                                part_file = part.get("file")
                                if part_file and Path(part_file) == full_path:
                                    return video.get("ratingKey")
                    
                    logger.warning(f"No matching Plex item found for {file_path}")
                    return None
        except Exception as e:
            logger.exception(f"Error finding Plex item: {e}")
            return None
