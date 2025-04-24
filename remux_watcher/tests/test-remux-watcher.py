import asyncio
import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from remux_watcher.config import Config
from remux_watcher.database import DatabaseManager, RemuxStatus, PlexUpdateStatus
from remux_watcher.monitor import FileMonitor
from remux_watcher.plex import PlexManager
from remux_watcher.remux import RemuxManager


@pytest.fixture
def sample_config():
    with tempfile.TemporaryDirectory() as watch_dir, \
         tempfile.TemporaryDirectory() as dest_dir, \
         tempfile.NamedTemporaryFile(suffix='.json') as db_file:
        
        config = Config(
            watch_folder=Path(watch_dir),
            destination_folder=Path(dest_dir),
            db_path=Path(db_file.name),
            remux_pause=1,
            max_jobs=2,
            puid=1000,
            pgid=1000,
            plex_url="http://localhost:32400",
            plex_token="dummy_token",
            plex_library="TV Shows"
        )
        yield config


@pytest.fixture
def sample_db_json():
    return {
        "recordings": {
            "1": {
                "id": "3a4abe3e-066d-4903-8f3a-07d47c1dd258",
                "name": "Formula 1",
                "url": "https://example.com/stream.ts",
                "start_time": "2025-04-22T14:14:10.386973+00:00",
                "duration_seconds": 6349,
                "description": "SkySp F1 UHD",
                "status": "completed",
                "created_at": "2025-04-22T14:14:10.386973+00:00",
                "file_path": "/recordings/3a4abe3e-066d-4903-8f3a-07d47c1dd258.ts",
                "error": None,
                "headers": None,
                "parent_id": "https://example.com/stream.ts"
            }
        }
    }


@pytest.fixture
def db_manager(sample_config, sample_db_json):
    # Create a temporary app DB
    app_db_path = Path(tempfile.NamedTemporaryFile(suffix='.json').name)
    
    # Create and write temporary recordings DB
    recordings_db_path = Path(tempfile.NamedTemporaryFile(suffix='.json').name)
    with open(recordings_db_path, 'w') as f:
        json.dump(sample_db_json, f)
    
    return DatabaseManager(app_db_path, recordings_db_path)


@pytest.mark.asyncio
async def test_get_recording_info(db_manager):
    recording_info = await db_manager.get_recording_info("/recordings/3a4abe3e-066d-4903-8f3a-07d47c1dd258.ts")
    assert recording_info is not None
    assert recording_info["name"] == "Formula 1"
    assert recording_info["description"] == "SkySp F1 UHD"


@pytest.mark.asyncio
async def test_is_recording_complete(db_manager):
    recording_info = await db_manager.get_recording_info("/recordings/3a4abe3e-066d-4903-8f3a-07d47c1dd258.ts")
    assert db_manager.is_recording_complete(recording_info) is True
    
    # Test with recording status
    recording_info["status"] = "recording"
    assert db_manager.is_recording_complete(recording_info) is False


def test_add_remux_job(db_manager):
    recording_info = {
        "name": "Test Show",
        "description": "Test Episode",
        "created_at": "2025-04-22T14:14:10.386973+00:00",
        "status": "completed"
    }
    
    job_id = db_manager.add_remux_job(
        original_path="/test/original.ts",
        output_path="/test/output.mkv",
        recording_info=recording_info
    )
    
    assert job_id > 0
    
    # Check if job exists
    jobs = db_manager.app_db.table("remux_jobs").all()
    assert len(jobs) == 1
    assert jobs[0]["original_path"] == "/test/original.ts"
    assert jobs[0]["output_path"] == "/test/output.mkv"
    assert jobs[0]["remux_status"] == RemuxStatus.PENDING.value


def test_update_remux_status(db_manager):
    recording_info = {
        "name": "Test Show",
        "description": "Test Episode",
        "created_at": "2025-04-22T14:14:10.386973+00:00"
    }
    
    job_id = db_manager.add_remux_job(
        original_path="/test/original.ts",
        output_path="/test/output.mkv",
        recording_info=recording_info
    )
    
    db_manager.update_remux_status(job_id, RemuxStatus.STARTED)
    
    job = db_manager.app_db.table("remux_jobs").get(doc_id=job_id)
    assert job["remux_status"] == RemuxStatus.STARTED.value
    assert job["remux_started_at"] is not None


@pytest.mark.asyncio
async def test_remux_file_dry_run(sample_config, db_manager):
    remux_manager = RemuxManager(sample_config, db_manager, dry_run=True)
    
    recording_info = {
        "name": "Test Show",
        "description": "Test Episode",
        "created_at": "2025-04-22T14:14:10.386973+00:00"
    }
    
    job_id = db_manager.add_remux_job(
        original_path="/test/original.ts",
        output_path="/test/output.mkv",
        recording_info=recording_info
    )
    
    result = await remux_manager.remux_file(
        job_id, 
        Path("/test/original.ts"), 
        Path("/test/output.mkv")
    )
    
    assert result is True
    job = db_manager.app_db.table("remux_jobs").get(doc_id=job_id)
    assert job["remux_status"] == RemuxStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_plex_update_dry_run(sample_config, db_manager):
    plex_manager = PlexManager(
        url=sample_config.plex_url,
        token=sample_config.plex_token,
        library=sample_config.plex_library,
        dry_run=True
    )
    
    recording_info = {
        "name": "Test Show",
        "description": "Test Episode",
        "created_at": "2025-04-22T14:14:10.386973+00:00"
    }
    
    job_id = db_manager.add_remux_job(
        original_path="/test/original.ts",
        output_path="/test/output.mkv",
        recording_info=recording_info
    )
    
    # Patch the database update method to avoid circular import issues in tests
    with patch('remux_watcher.database.DatabaseManager.update_plex_status') as mock_update:
        result = await plex_manager.update_library(job_id, Path("/test/output.mkv"))
        assert result is True


@pytest.mark.asyncio
async def test_format_output_filename():
    config = Config(
        watch_folder=Path("/watch"),
        destination_folder=Path("/destination"),
        db_path=Path("/db.json"),
        remux_pause=1,
        max_jobs=2,
        puid=1000,
        pgid=1000,
        plex_url="http://localhost:32400",
        plex_token="dummy_token",
        plex_library="TV Shows"
    )
    
    db_manager = MagicMock()
    file_monitor = FileMonitor(config, dry_run=True)
    
    recording_info = {
        "name": "Test: Show?",
        "description": "Test/Episode*2",
        "created_at": "2025-04-22T14:14:10.386973+00:00"
    }
    
    output_filename = file_monitor._format_output_filename(recording_info)
    assert output_filename == "Test_ Show_-Test_Episode_2-20250422141410.mkv"


@pytest.mark.asyncio
async def test_process_file_dry_run(sample_config):
    # Create mocks
    db_manager = MagicMock()
    db_manager.is_file_processed.return_value = False
    db_manager.get_recording_info.return_value = {
        "name": "Test Show",
        "description": "Test Episode",
        "created_at": "2025-04-22T14:14:10.386973+00:00",
        "status": "completed"
    }
    db_manager.is_recording_complete.return_value = True
    db_manager.add_remux_job.return_value = 1
    
    # Set up monitor with our mocks
    file_monitor = FileMonitor(sample_config, dry_run=True)
    file_monitor.db_manager = db_manager
    file_monitor.remux_manager = MagicMock()
    file_monitor.plex_manager = MagicMock()
    
    # Process a test file
    await file_monitor._process_file(Path("/test/recording.ts"))
    
    # Verify expected calls
    db_manager.is_file_processed.assert_called_once()
    db_manager.get_recording_info.assert_called_once()
    db_manager.is_recording_complete.assert_called_once()
    db_manager.add_remux_job.assert_called_once()
    # In dry-run mode, we don't actually call remux
    file_monitor.remux_manager.remux_file.assert_not_called()
