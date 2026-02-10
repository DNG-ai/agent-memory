"""Tests for the hook check-error command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from agent_memory.cli import main


class TestHookCheckError:
    """Tests for hook check-error subcommand."""

    def test_nudge_when_error_detected(self, config, temp_dir):
        """Test that a nudge is printed when errors are found in input."""
        runner = CliRunner()

        # Enable error_nudge in config
        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        input_data = json.dumps({"tool_response": "Error: ECONNREFUSED 127.0.0.1:6379"})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input=input_data,
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert "[agent-memory]" in result.output
        assert "Error detected" in result.output

    def test_silent_when_disabled(self, config, temp_dir):
        """Test that no output is produced when hooks.error_nudge is disabled."""
        runner = CliRunner()

        # Default config has error_nudge=false
        input_data = json.dumps({"tool_response": "Error: ECONNREFUSED"})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input=input_data,
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_silent_when_no_error(self, config, temp_dir):
        """Test that no output is produced when there are no errors."""
        runner = CliRunner()

        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        input_data = json.dumps({"tool_response": "Build succeeded. 42 tests passed."})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input=input_data,
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_silent_on_empty_stdin(self, config, temp_dir):
        """Test graceful handling of empty stdin."""
        runner = CliRunner()

        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input="",
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_detects_various_error_keywords(self, config, temp_dir):
        """Test that various error keywords are detected."""
        runner = CliRunner()

        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        error_messages = [
            "Traceback (most recent call last):",
            "fatal: not a git repository",
            "FAILED tests/test_foo.py::test_bar",
            "ModuleNotFoundError: No module named 'foo'",
            "panic: runtime error: index out of range",
            "TypeError: undefined is not a function",
            "command not found: foobar",
        ]

        for msg in error_messages:
            input_data = json.dumps({"tool_response": msg})
            result = runner.invoke(
                main,
                ["hook", "check-error"],
                input=input_data,
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )
            assert "[agent-memory]" in result.output, f"Failed to detect error in: {msg}"

    def test_handles_non_json_stdin(self, config, temp_dir):
        """Test handling of raw text (non-JSON) stdin."""
        runner = CliRunner()

        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input="Error: something went wrong",
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert "[agent-memory]" in result.output

    def test_handles_stdout_field(self, config, temp_dir):
        """Test extraction from stdout field."""
        runner = CliRunner()

        from agent_memory.config import save_config_data

        config_file = temp_dir / "config.yaml"
        save_config_data(config_file, {"hooks": {"error_nudge": True}})

        input_data = json.dumps({"stdout": "FileNotFoundError: config.yaml not found"})

        result = runner.invoke(
            main,
            ["hook", "check-error"],
            input=input_data,
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert "[agent-memory]" in result.output


class TestHooksConfig:
    """Tests for hooks configuration."""

    def test_default_hooks_config(self, config):
        """Test that hooks.error_nudge defaults to False."""
        assert config.hooks.error_nudge is False

    def test_config_set_hooks_error_nudge(self, config, temp_dir):
        """Test setting hooks.error_nudge via config set."""
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["config", "set", "hooks.error_nudge=true"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0
        assert "hooks.error_nudge" in result.output

        # Verify it persisted
        from agent_memory.config import load_config

        new_config = load_config(temp_dir)
        assert new_config.hooks.error_nudge is True

    def test_config_set_hooks_error_nudge_false(self, config, temp_dir):
        """Test disabling hooks.error_nudge."""
        runner = CliRunner()

        # First enable
        runner.invoke(
            main,
            ["config", "set", "hooks.error_nudge=true"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        # Then disable
        result = runner.invoke(
            main,
            ["config", "set", "hooks.error_nudge=false"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code == 0

        from agent_memory.config import load_config

        new_config = load_config(temp_dir)
        assert new_config.hooks.error_nudge is False
