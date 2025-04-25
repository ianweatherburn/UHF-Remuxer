import os
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class Config:
    watch_folder: Path
    destination_folder: Path
    db_path: Path
    interval: int
    max_jobs: int
    puid: int
    pgid: int
    plex_url: str
    plex_token: str
    plex_library: str
    plex_scan_count: int
    plex_folder: str
    remux_file: str
    db_file: str
    threshold: int
    include_cancelled: bool
    
def load_config() -> Config:
    """Load configuration from environment variables."""
    # Required environment variables
    required_vars = [
        "WATCH_FOLDER",
        "DESTINATION_FOLDER",
        "DB_PATH"
    ]
    
    # Check required environment variables
    for var in required_vars:
        if not os.environ.get(var):
            raise ValueError(f"Required environment variable {var} is not set")

    # Load configuration values
    config = Config(
        watch_folder=Path("/recordings"),
        destination_folder=Path("/remux"),
        db_path=Path("/data"),
        interval=int(os.environ.get("INTERVAL", "5")),
        max_jobs=int(os.environ.get("MAX_JOBS", "2")),
        puid=int(os.environ.get("PUID", "1000")),
        pgid=int(os.environ.get("PGID", "1000")),
        plex_url=os.environ.get("PLEX_URL", ""),
        plex_token=os.environ.get("PLEX_TOKEN", ""),
        plex_library=os.environ.get("PLEX_LIBRARY", ""),
        plex_scan_count=int(os.environ.get("PLEX_SCAN_COUNT", "30")),
        plex_folder=Path(os.environ.get("PLEX_FOLDER", "/media/videos/uhf-server")),
        remux_file=os.environ.get("REMUX_FILE", "remux.json"),
        db_file=os.environ.get("DB_FILE", "db.json"),
        threshold=int(os.environ.get("THRESHOLD", "30")),
        include_cancelled=str_to_bool(os.environ.get("INCLUDE_CANCELLED", "true"))
    )

    # Validate paths
    if not config.watch_folder.exists():
        logger.warning(f"Watch folder '{config.watch_folder}' does not exist")
    
    if not config.destination_folder.exists():
        logger.warning(f"Destination folder '{config.destination_folder}' does not exist")
        
    # Validate Plex configuration
    if config.plex_url and not config.plex_token:
        logger.warning("PLEX_URL provided but PLEX_TOKEN is missing")
    if config.plex_token and not config.plex_url:
        logger.warning("PLEX_TOKEN provided but PLEX_URL is missing")
    if (config.plex_url and config.plex_token) and not config.plex_library:
        logger.warning("Plex connection info provided but PLEX_LIBRARY is missing")
    # if not config.plex_folder.exists():
    #     logger.warning(f"Plex Folder '{config.plex_folder}' does not exist")
    # else:
    #     logger.info(f"Plex Folder '{config.plex_folder}' exists")
    
    return config

def str_to_bool(value: str) -> bool:
    return str(value).lower() in ("true", "1", "yes", "y")    
