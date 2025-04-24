# Remux Watcher

A Docker-based application that monitors a folder for TS video files, remuxes them to MKV format, and updates a Plex media server.

## Features

- Monitors a specified folder for TS files
- Checks recording status in a database file rather than file size
- Renames output files according to metadata from the database
- Remuxes TS to MKV using ffmpeg
- Updates Plex library after successful remuxing
- Maintains a database of processed files
- Supports dry-run mode for testing

## Setup

1. Clone this repository
2. Copy `.env.sample` to `.env` and edit with your configuration
3. Build and run the Docker container:

```bash
docker-compose up -d
```

## Configuration

The following environment variables can be configured in the `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `WATCH_FOLDER` | Directory to monitor for TS files | Required |
| `DESTINATION_FOLDER` | Directory to save MKV files | Required |
| `DB_PATH` | Path to the database JSON file | Required |
| `REMUX_PAUSE` | Seconds to wait between scans | 5 |
| `MAX_JOBS` | Maximum concurrent remux jobs | 2 |
| `TZ` | Timezone | Africa/Johannesburg |
| `PUID` | User ID for file ownership | 1000 |
| `PGID` | Group ID for file ownership | 1000 |
| `PLEX_URL` | Plex server URL | Optional |
| `PLEX_TOKEN` | Plex authentication token | Optional |
| `PLEX_LIBRARY` | Plex library name to update | Optional |

## Usage

### Dry Run Mode

To test the application without making any changes:

```bash
docker-compose run --rm remuxer python -m remux_watcher --dry-run
```

### Debug Mode

For more verbose logging:

```bash
docker-compose run --rm remuxer python -m remux_watcher --debug
```

## How It Works

1. The application monitors the `WATCH_FOLDER` for `.ts` files
2. For each file, it checks the database at `DB_PATH` to see if the recording is complete
3. If the recording is complete and hasn't been processed before, it:
   - Creates a new filename based on metadata in the database
   - Remuxes the file to MKV format using ffmpeg
   - Moves the file to the `DESTINATION_FOLDER`
   - Updates the Plex library (if configured)
   - Updates its internal database to track processed files

## Development

### Running Tests

```bash
pip install -r requirements.txt
pytest
```

### Project Structure

- `remux_watcher/` - Main application package
  - `__main__.py` - Entry point
  - `config.py` - Configuration handling
  - `database.py` - Database operations
  - `monitor.py` - File monitoring
  - `remux.py` - FFmpeg remuxing
  - `plex.py` - Plex integration
- `tests/` - Test suite
- `Dockerfile` - Docker image definition
- `docker-compose.yml` - Docker Compose configuration
- `requirements.txt` - Python dependencies
- `entrypoint.sh` - Container entry point
