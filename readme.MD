# Remux Watcher

A Docker-based application that monitors a folder for .TS video files create by the UHF-Server, remuxes them to .MKV format with metadata, and updates a Plex media server.

## Features

- Monitors a specified folder for various media files, created by the UHF Server
- Checks recording status from the UHF database
- Renames output files according to metadata from the database (instead of the UHF UUID)
- Remuxes the media file to MKV using ffmpeg and embeds recording metadata
- Updates a Plex library after successful remuxing with added metadata
- Maintains a database of processed files
- Supports dry-run mode for testing
- Specifies an interval to monitor the UHF server for completed recordings

## Setup

1. Clone this repository
2. Copy `.env.sample` to `.env` and edit with your configuration. You must specify a PLEX_TOKEN to get Plex library updates.
3. Build and run the Docker container:

```bash
docker-compose up -d
```

## Configuration

The following environment variables can be configured in the `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `WATCH_FOLDER` | Directory to monitor for media files where UHF server saves recordings | Required |
| `WATCH_FILES` | File extensions to monitor for remuxing (comma-separatated, such as .ts,.m2t) | Optional (.ts) |
| `DESTINATION_FOLDER` | Directory to save MKV files where Plex will pick up the remux | Required |
| `REMUX_FILE` | The database of completed remuxes stored in the DESTINATION_FOLDER | Optional (.remux.json) |
| `DB_PATH` | Path to the UHF server database | Required |
| `DB_FILE` | Filename of the UHF server database | Optional (db.json)|
| `INTERVAL` | The interval at which scans are run | Optional (5) |
| `INCLUDE_CANCELLED` | Remux recordings that were cancelled on UHF-Server | Optional (True) |
| `THRESHOLD` | Exclude remuxes that do not match the requested recording time by the threshold percentage | Optional (0) |
| `MAX_JOBS` | Maximum concurrent ffmpeg remux jobs | Optional (2) |
| `LANGUAGE` | A valid ISO-639-2 language code to apply to the stream | Optional (eng) |
| `TZ` | Timezone used for UTC conversions | Required |
| `PUID` | User ID for file ownership | Required |
| `PGID` | Group ID for file ownership | Required |
| `PLEX_URL` | Plex server URL | Optional |
| `PLEX_TOKEN` | Plex authentication token | Optional |
| `PLEX_LIBRARY` | Plex library name to update | Optional |
| `PLEX_SCAN_COUNT` | Iterations to wait until Plex library scanning is complete | Optional (30) |
| `PLEX_FOLDER` | The Plex library folder where remuxes are stored (NOTE: This is relative to Plex if running on a different server) | Optional |

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

1. The application monitors the `WATCH_FOLDER` for the specified media files
2. For each file, it checks the UHF database at `DB_PATH` to see if the recording is complete, and hasn't failed
3. If the recording is complete and hasn't been processed before, it:
   - Ignore the recording if it was cancelled on the UHF-Server, and INCLUDE_CANCELLED=false
   - Creates a new filename based on metadata in the database
   - Remuxes the file to MKV format using ffmpeg and embeds metadata (note that the audio language may not be correct. UHF does not provide that info)
   - Ignore the file if it does not meet the recording duration threshold (ie the difference in recording duration between that requested on the UHF-Server and the Remux file is below the %)
   - Moves the file to the `DESTINATION_FOLDER`
   - Updates the Plex library (if configured)
   - Adds metadata to the Plex library item
   - Updates its internal database to track processed files
4. Duration THRESHOLD check is ignored, if the recording was cancelled and INCLUDE_CANCELLED=true, to allow for adhoc recordings

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
