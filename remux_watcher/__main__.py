import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from remux_watcher.config import load_config
from remux_watcher.monitor import FileMonitor


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TS to MKV Remux Watcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without performing actual remux or Plex updates",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    # Set logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load environment variables
    load_dotenv()
    
    # Load configuration
    config = load_config()
    
    if args.dry_run:
        logger.info("Running in DRY RUN mode - no actual changes will be made")
    
    # Create the file monitor and start monitoring
    monitor = FileMonitor(config, dry_run=args.dry_run)
    
    try:
        await monitor.start_monitoring()
    except KeyboardInterrupt:
        logger.info("Shutting down remux watcher")
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
