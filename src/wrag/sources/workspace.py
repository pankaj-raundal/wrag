"""Workspace source — walks local filesystem, computes hashes, yields files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from wrag.config import Settings


@dataclass
class FileEntry:
    """A file discovered in the workspace."""

    path: str  # relative path from workspace root
    abs_path: str  # absolute path
    content_hash: str  # sha256 of file content
    content: str  # file text content


def walk_workspace(
    workspace_path: str,
    settings: Settings,
) -> Generator[FileEntry, None, None]:
    """Walk workspace directory, yielding files that should be indexed.

    Respects exclusion settings (dirs and extensions).
    Skips binary files.
    """
    root = Path(workspace_path)
    excluded_dirs = set(settings.excluded_dirs)
    excluded_exts = set(settings.excluded_extensions)

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out excluded directories (modifies in-place for os.walk)
        dirnames[:] = [
            d for d in dirnames
            if d not in excluded_dirs and not d.startswith(".")
        ]

        for filename in filenames:
            # Skip hidden files
            if filename.startswith("."):
                continue

            # Skip excluded extensions
            ext = Path(filename).suffix.lower()
            if ext in excluded_exts:
                continue

            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, root)

            # Skip very large files (>1MB)
            try:
                size = os.path.getsize(abs_path)
                if size > 1_048_576:  # 1MB
                    continue
                if size == 0:
                    continue
            except OSError:
                continue

            # Read and check for binary content
            try:
                with open(abs_path, "r", encoding="utf-8", errors="strict") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                # Binary or unreadable file
                continue

            # Compute hash
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            yield FileEntry(
                path=rel_path,
                abs_path=abs_path,
                content_hash=content_hash,
                content=content,
            )


def compute_file_hash(file_path: str) -> str:
    """Compute sha256 hash of a file's content."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except (UnicodeDecodeError, OSError):
        return ""
