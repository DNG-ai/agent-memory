"""Pytest configuration and fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from agent_memory.config import Config, load_config
from agent_memory.store import MemoryStore


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def config(temp_dir: Path) -> Config:
    """Create a test configuration."""
    return load_config(temp_dir)


@pytest.fixture
def store(config: Config, temp_dir: Path) -> Generator[MemoryStore, None, None]:
    """Create a test memory store."""
    project_path = temp_dir / "test-project"
    project_path.mkdir()

    store = MemoryStore(config, project_path)
    yield store
    store.close()


@pytest.fixture
def global_store(config: Config) -> Generator[MemoryStore, None, None]:
    """Create a test memory store for global scope."""
    store = MemoryStore(config, None)
    yield store
    store.close()
