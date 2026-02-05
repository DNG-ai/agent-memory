"""Tests for configuration management."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_memory.config import (
    Config,
    ensure_directories,
    get_base_path,
    load_config,
    update_config,
)


class TestConfig:
    """Tests for configuration."""

    def test_load_default_config(self, temp_dir: Path) -> None:
        """Test loading default configuration."""
        config = load_config(temp_dir)

        assert config.base_path == temp_dir
        assert config.semantic.enabled is True
        assert config.semantic.provider == "vertex"
        assert config.semantic.threshold == 0.7
        assert config.autosave.enabled is True
        assert config.startup.auto_load_pinned is True

    def test_config_file_created(self, temp_dir: Path) -> None:
        """Test that config file is created on load."""
        load_config(temp_dir)

        config_file = temp_dir / "config.yaml"
        assert config_file.exists()

    def test_directories_created(self, temp_dir: Path) -> None:
        """Test that required directories are created."""
        load_config(temp_dir)

        assert (temp_dir / "global").exists()
        assert (temp_dir / "global" / "summaries").exists()
        assert (temp_dir / "projects").exists()

    def test_update_config(self, temp_dir: Path) -> None:
        """Test updating configuration values."""
        config = load_config(temp_dir)

        # Update semantic enabled
        new_config = update_config(config, "semantic.enabled", "false")
        assert new_config.semantic.enabled is False

        # Update threshold
        new_config = update_config(new_config, "semantic.threshold", "0.8")
        assert new_config.semantic.threshold == 0.8

        # Reload and verify persistence
        reloaded = load_config(temp_dir)
        assert reloaded.semantic.enabled is False
        assert reloaded.semantic.threshold == 0.8

    def test_global_path(self, config: Config) -> None:
        """Test global path property."""
        assert config.global_path == config.base_path / "global"

    def test_projects_path(self, config: Config) -> None:
        """Test projects path property."""
        assert config.projects_path == config.base_path / "projects"

    def test_config_file_path(self, config: Config) -> None:
        """Test config file path property."""
        assert config.config_file == config.base_path / "config.yaml"


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_all_directories(self) -> None:
        """Test that all required directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "agent-memory"

            ensure_directories(base_path)

            assert base_path.exists()
            assert (base_path / "global").exists()
            assert (base_path / "global" / "summaries").exists()
            assert (base_path / "projects").exists()

    def test_idempotent(self) -> None:
        """Test that calling ensure_directories multiple times is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "agent-memory"

            ensure_directories(base_path)
            ensure_directories(base_path)  # Should not raise

            assert base_path.exists()
