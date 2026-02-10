"""Tests for the usage CLI command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from agent_memory.cli import main


class TestUsageCommand:
    """Tests for the 'usage' command."""

    def test_usage_default(self, temp_dir) -> None:
        """Test usage command with defaults."""
        runner = CliRunner()
        result = runner.invoke(main, ["usage"], env={"AGENT_MEMORY_PATH": str(temp_dir)})
        assert result.exit_code == 0
        assert "Usage Report" in result.output
        assert "Command Frequency" in result.output
        assert "Search Effectiveness" in result.output
        assert "Memory Effectiveness" in result.output
        assert "Agent Compliance" in result.output

    def test_usage_json(self, temp_dir) -> None:
        """Test usage command with --json output."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["usage", "--json"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "period_days" in data
        assert data["period_days"] == 30
        assert "command_frequency" in data
        assert "search_effectiveness" in data
        assert "session_compliance" in data
        assert "memory_effectiveness" in data
        assert "recommendations" in data

    def test_usage_since_7d(self, temp_dir) -> None:
        """Test usage command with --since 7d."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["usage", "--since", "7d"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        assert "last 7d" in result.output

    def test_usage_since_90d(self, temp_dir) -> None:
        """Test usage command with --since 90d."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["usage", "--since", "90d"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        assert "last 90d" in result.output

    def test_usage_invalid_since(self, temp_dir) -> None:
        """Test usage command with invalid --since."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["usage", "--since", "7w"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code != 0

    def test_usage_json_period_days(self, temp_dir) -> None:
        """Test JSON output reflects --since parameter."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["usage", "--since", "7d", "--json"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["period_days"] == 7

    def test_usage_with_some_data(self, temp_dir) -> None:
        """Test usage command after some commands have been run."""
        runner = CliRunner()

        # Save a memory first
        runner.invoke(
            main,
            ["save", "Test memory for usage tracking"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        # Now check usage
        result = runner.invoke(
            main, ["usage", "--json"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        data = json.loads(result.output)

        # Should have at least one save event
        freq = data["command_frequency"]
        assert freq.get("save", 0) >= 1

    def test_usage_memory_effectiveness(self, temp_dir) -> None:
        """Test memory effectiveness section in JSON output."""
        runner = CliRunner()

        # Save a couple of memories
        runner.invoke(
            main,
            ["save", "Memory one"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )
        runner.invoke(
            main,
            ["save", "Memory two"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        result = runner.invoke(
            main, ["usage", "--json"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        data = json.loads(result.output)

        mem_eff = data["memory_effectiveness"]
        assert mem_eff["total_memories"] >= 2
        assert "never_accessed" in mem_eff
        assert "never_accessed_pct" in mem_eff

    def test_usage_recommendations_in_json(self, temp_dir) -> None:
        """Test recommendations section in JSON output."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["usage", "--json"], env={"AGENT_MEMORY_PATH": str(temp_dir)}
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data["recommendations"], list)
