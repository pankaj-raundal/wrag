"""Tests for the file watcher."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wrag.config import Settings
from wrag.watcher import WorkspaceWatcher, _DebouncedHandler


class TestDebouncedHandler:
    def test_ignores_excluded_dirs(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.1)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/project/vendor/autoload.php"
        handler.on_modified(event)

        time.sleep(0.3)
        cb.assert_not_called()

    def test_ignores_excluded_extensions(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.1)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/project/data/dump.sql"
        handler.on_modified(event)

        time.sleep(0.3)
        cb.assert_not_called()

    def test_ignores_directories(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.1)

        event = MagicMock()
        event.is_directory = True
        event.src_path = "/project/src/"
        handler.on_modified(event)

        time.sleep(0.3)
        cb.assert_not_called()

    def test_debounces_multiple_events(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.2)

        for fname in ["a.py", "b.py", "c.py"]:
            event = MagicMock()
            event.is_directory = False
            event.src_path = f"/project/src/{fname}"
            handler.on_modified(event)

        # Not called yet (debounce window)
        cb.assert_not_called()

        # Wait for debounce to fire
        time.sleep(0.5)
        cb.assert_called_once()
        paths = cb.call_args[0][0]
        assert len(paths) == 3
        assert "/project/src/a.py" in paths

    def test_fires_on_created(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.1)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/project/src/new_file.py"
        handler.on_created(event)

        time.sleep(0.3)
        cb.assert_called_once()

    def test_fires_on_deleted(self):
        settings = Settings()
        cb = MagicMock()
        handler = _DebouncedHandler(callback=cb, settings=settings, debounce_seconds=0.1)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/project/src/old.py"
        handler.on_deleted(event)

        time.sleep(0.3)
        cb.assert_called_once()


class TestWorkspaceWatcher:
    def test_start_and_stop(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1")

        settings = Settings()
        cb = MagicMock()

        watcher = WorkspaceWatcher(
            workspaces=[("testapp", str(src_dir))],
            settings=settings,
            on_change=cb,
            debounce_seconds=0.2,
        )
        watcher.start()
        assert watcher.is_running()

        watcher.stop()
        assert not watcher.is_running()

    def test_detects_file_change(self, tmp_path):
        src_dir = tmp_path / "project"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hello')")

        settings = Settings()
        cb = MagicMock()

        watcher = WorkspaceWatcher(
            workspaces=[("testapp", str(src_dir))],
            settings=settings,
            on_change=cb,
            debounce_seconds=0.3,
        )
        watcher.start()

        # Modify a file
        time.sleep(0.1)  # Let observer settle
        (src_dir / "main.py").write_text("print('changed')")

        # Wait for debounce
        time.sleep(1.0)
        watcher.stop()

        cb.assert_called()
        app_name = cb.call_args[0][0]
        assert app_name == "testapp"

    def test_skips_nonexistent_paths(self):
        settings = Settings()
        watcher = WorkspaceWatcher(
            workspaces=[("ghost", "/nonexistent/path/xyz")],
            settings=settings,
            on_change=MagicMock(),
        )
        # Should not raise
        watcher.start()
        watcher.stop()
