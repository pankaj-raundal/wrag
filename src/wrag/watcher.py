"""File watcher — monitors workspace directories and triggers re-indexing on changes."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from wrag.config import Settings, DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_EXTENSIONS


class _DebouncedHandler(FileSystemEventHandler):
    """Collects file events and triggers callback after a debounce period."""

    def __init__(
        self,
        callback: Callable[[set[str]], None],
        settings: Settings,
        debounce_seconds: float = 2.0,
    ):
        super().__init__()
        self.callback = callback
        self.settings = settings
        self.debounce_seconds = debounce_seconds
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _should_ignore(self, path: str) -> bool:
        """Check if this path should be ignored based on settings."""
        parts = Path(path).parts
        for excluded in self.settings.excluded_dirs:
            if excluded in parts:
                return True

        ext = Path(path).suffix.lower()
        if ext in self.settings.excluded_extensions:
            return True

        return False

    def _on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return

        src = event.src_path
        if self._should_ignore(src):
            return

        with self._lock:
            self._pending.add(src)
            # Reset debounce timer
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def on_created(self, event: FileSystemEvent):
        self._on_any_event(event)

    def on_modified(self, event: FileSystemEvent):
        self._on_any_event(event)

    def on_deleted(self, event: FileSystemEvent):
        self._on_any_event(event)

    def on_moved(self, event: FileSystemEvent):
        self._on_any_event(event)

    def _flush(self):
        """Fire the callback with accumulated paths."""
        with self._lock:
            paths = self._pending.copy()
            self._pending.clear()
            self._timer = None

        if paths:
            self.callback(paths)


class WorkspaceWatcher:
    """Watches one or more workspace directories for changes and re-indexes."""

    def __init__(
        self,
        workspaces: list[tuple[str, str]],  # (app_name, path) pairs
        settings: Settings,
        on_change: Callable[[str, set[str]], None] | None = None,
        debounce_seconds: float = 2.0,
    ):
        """
        Args:
            workspaces: List of (app_name, workspace_path) tuples to watch
            settings: Settings for exclusion rules
            on_change: Callback(app_name, changed_paths) when changes detected
            debounce_seconds: Seconds to wait before triggering re-index
        """
        self.workspaces = workspaces
        self.settings = settings
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds
        self._observer = Observer()
        self._running = False

    def _make_callback(self, app_name: str) -> Callable[[set[str]], None]:
        """Create a callback bound to a specific app name."""
        def cb(paths: set[str]):
            if self.on_change:
                self.on_change(app_name, paths)
        return cb

    def start(self):
        """Start watching all configured workspaces."""
        for app_name, path in self.workspaces:
            if not Path(path).is_dir():
                continue
            handler = _DebouncedHandler(
                callback=self._make_callback(app_name),
                settings=self.settings,
                debounce_seconds=self.debounce_seconds,
            )
            self._observer.schedule(handler, path, recursive=True)

        self._observer.start()
        self._running = True

    def stop(self):
        """Stop the watcher."""
        if self._running:
            self._observer.stop()
            self._observer.join()
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def wait(self):
        """Block until the observer is stopped (e.g. via KeyboardInterrupt)."""
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
