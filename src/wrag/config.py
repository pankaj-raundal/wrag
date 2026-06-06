"""Configuration management for wRag — load/save YAML config."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# Default config location: <project_root>/config.yaml
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

DEFAULT_EXCLUDED_DIRS = [
    "vendor",
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".data",
    ".idea",
    ".tox",
    "dist",
    "build",
]

DEFAULT_EXCLUDED_EXTENSIONS = [
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".sql",
    ".patch",
    ".gz",
    ".zip",
    ".tar",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
]


@dataclass
class WorkspaceSource:
    """A registered local workspace."""

    name: str
    path: str

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspaceSource":
        return cls(name=data["name"], path=data["path"])


@dataclass
class ConfluenceSource:
    """A registered Confluence space."""

    name: str
    domain: str
    space_key: str
    email: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "space_key": self.space_key,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConfluenceSource":
        return cls(
            name=data["name"],
            domain=data["domain"],
            space_key=data["space_key"],
            email=data.get("email", ""),
        )


@dataclass
class Settings:
    """Global settings."""

    embedding_model: str = "local"  # "local" or "openai"
    openai_api_key: Optional[str] = None
    chunk_max_lines: int = 60
    excluded_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_DIRS))
    excluded_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_EXTENSIONS)
    )

    def to_dict(self) -> dict:
        d = {
            "embedding_model": self.embedding_model,
            "chunk_max_lines": self.chunk_max_lines,
            "excluded_dirs": self.excluded_dirs,
            "excluded_extensions": self.excluded_extensions,
        }
        if self.openai_api_key:
            d["openai_api_key"] = self.openai_api_key
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        return cls(
            embedding_model=data.get("embedding_model", "local"),
            openai_api_key=data.get("openai_api_key"),
            chunk_max_lines=data.get("chunk_max_lines", 60),
            excluded_dirs=data.get("excluded_dirs", list(DEFAULT_EXCLUDED_DIRS)),
            excluded_extensions=data.get("excluded_extensions", list(DEFAULT_EXCLUDED_EXTENSIONS)),
        )


@dataclass
class Config:
    """Top-level wRag configuration."""

    workspaces: list[WorkspaceSource] = field(default_factory=list)
    confluences: list[ConfluenceSource] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def to_dict(self) -> dict:
        return {
            "workspaces": [w.to_dict() for w in self.workspaces],
            "confluences": [c.to_dict() for c in self.confluences],
            "settings": self.settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            workspaces=[WorkspaceSource.from_dict(w) for w in data.get("workspaces", [])],
            confluences=[ConfluenceSource.from_dict(c) for c in data.get("confluences", [])],
            settings=Settings.from_dict(data.get("settings", {})),
        )

    def find_source(self, name: str) -> Optional[WorkspaceSource | ConfluenceSource]:
        """Find a source by name (workspace or confluence)."""
        for w in self.workspaces:
            if w.name == name:
                return w
        for c in self.confluences:
            if c.name == name:
                return c
        return None

    def remove_source(self, name: str) -> bool:
        """Remove a source by name. Returns True if found and removed."""
        for i, w in enumerate(self.workspaces):
            if w.name == name:
                self.workspaces.pop(i)
                return True
        for i, c in enumerate(self.confluences):
            if c.name == name:
                self.confluences.pop(i)
                return True
        return False

    def all_source_names(self) -> list[str]:
        """Return all registered source names."""
        return [w.name for w in self.workspaces] + [c.name for c in self.confluences]


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file. Returns empty config if file doesn't exist."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return Config()
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return Config.from_dict(data)


def save_config(config: Config, path: Path | None = None) -> None:
    """Save config to YAML file."""
    config_path = path or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)
