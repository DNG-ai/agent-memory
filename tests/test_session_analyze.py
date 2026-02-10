"""Tests for the session analyze command."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from agent_memory.cli import main
from agent_memory.llm import LLMProvider


class TestSessionAnalyze:
    """Tests for session analyze subcommand."""

    def test_analyze_text_dry_run(self, config, temp_dir):
        """Test analyzing inline text with --dry-run."""
        runner = CliRunner()

        mock_patterns = [
            {
                "error": "TypeError: Cannot read property 'map' of undefined",
                "cause": "API returns null instead of array",
                "fix": "Use optional chaining with fallback",
                "context": "UserList.tsx",
            }
        ]

        with patch("agent_memory.llm.get_llm_provider") as mock_get_llm:
            mock_llm = MagicMock(spec=LLMProvider)
            mock_llm.extract_patterns.return_value = mock_patterns
            mock_get_llm.return_value = mock_llm

            result = runner.invoke(
                main,
                [
                    "session",
                    "analyze",
                    "Hit TypeError in UserList.tsx, null check missing",
                    "--dry-run",
                ],
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )

        assert result.exit_code == 0
        assert "TypeError" in result.output
        assert "dry run" in result.output

    def test_analyze_text_dry_run_json(self, config, temp_dir):
        """Test analyzing with --dry-run and --json."""
        runner = CliRunner()

        mock_patterns = [
            {
                "error": "ECONNREFUSED",
                "cause": "Redis not running",
                "fix": "Start Redis with docker compose up",
                "context": "test suite",
            }
        ]

        with patch("agent_memory.llm.get_llm_provider") as mock_get_llm:
            mock_llm = MagicMock(spec=LLMProvider)
            mock_llm.extract_patterns.return_value = mock_patterns
            mock_get_llm.return_value = mock_llm

            result = runner.invoke(
                main,
                [
                    "session",
                    "analyze",
                    "ECONNREFUSED when running tests, fixed by starting Redis",
                    "--dry-run",
                    "--json",
                ],
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["error"] == "ECONNREFUSED"

    def test_analyze_no_patterns(self, config, temp_dir):
        """Test when no patterns are found."""
        runner = CliRunner()

        with patch("agent_memory.llm.get_llm_provider") as mock_get_llm:
            mock_llm = MagicMock(spec=LLMProvider)
            mock_llm.extract_patterns.return_value = []
            mock_get_llm.return_value = mock_llm

            result = runner.invoke(
                main,
                ["session", "analyze", "Everything worked fine", "--dry-run"],
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )

        assert result.exit_code == 0
        assert "No error-fix patterns found" in result.output

    def test_analyze_no_llm(self, config, temp_dir):
        """Test graceful failure when LLM is not available."""
        runner = CliRunner()

        with patch("agent_memory.llm.get_llm_provider") as mock_get_llm:
            mock_get_llm.return_value = None

            result = runner.invoke(
                main,
                ["session", "analyze", "some content"],
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )

        assert result.exit_code != 0
        assert "LLM provider not available" in result.output

    def test_analyze_no_arguments(self, config, temp_dir):
        """Test error when no content source is provided."""
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["session", "analyze"],
            env={"AGENT_MEMORY_PATH": str(temp_dir)},
        )

        assert result.exit_code != 0
        assert "Provide content text" in result.output

    def test_analyze_saves_memories(self, config, temp_dir):
        """Test that analyze saves patterns as memories."""
        runner = CliRunner()

        mock_patterns = [
            {
                "error": "ImportError: no module named foo",
                "cause": "Missing dependency",
                "fix": "pip install foo",
                "context": "main.py",
            }
        ]

        project_dir = temp_dir / "test-project"
        project_dir.mkdir()

        with (
            patch("agent_memory.llm.get_llm_provider") as mock_get_llm,
            patch("agent_memory.cli.get_current_project_path", return_value=project_dir),
        ):
            mock_llm = MagicMock(spec=LLMProvider)
            mock_llm.extract_patterns.return_value = mock_patterns
            mock_get_llm.return_value = mock_llm

            result = runner.invoke(
                main,
                [
                    "session",
                    "analyze",
                    "ImportError no module foo, fixed by installing",
                    "--json",
                ],
                env={"AGENT_MEMORY_PATH": str(temp_dir)},
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert "memory_id" in data[0]
        assert data[0]["memory_id"].startswith("mem_")


class TestExtractPatterns:
    """Tests for LLMProvider.extract_patterns."""

    def test_extract_patterns_empty_content(self, config):
        """Test with empty content."""
        llm = LLMProvider(config)
        assert llm.extract_patterns("") == []

    def test_extract_patterns_parses_json(self, config):
        """Test JSON parsing of LLM response."""
        llm = LLMProvider(config)

        response_json = json.dumps([
            {
                "error": "TypeError",
                "cause": "null ref",
                "fix": "add null check",
                "context": "app.ts",
            }
        ])

        with patch.object(llm, "_summarize_claude", return_value=response_json):
            llm.provider = "claude"
            result = llm.extract_patterns("some session content")

        assert len(result) == 1
        assert result[0]["error"] == "TypeError"

    def test_extract_patterns_handles_markdown_fences(self, config):
        """Test handling of markdown code fences in LLM response."""
        llm = LLMProvider(config)

        response_with_fences = '```json\n[{"error": "E1", "cause": "C1", "fix": "F1", "context": "X"}]\n```'

        with patch.object(llm, "_summarize_claude", return_value=response_with_fences):
            llm.provider = "claude"
            result = llm.extract_patterns("content")

        assert len(result) == 1
        assert result[0]["error"] == "E1"

    def test_extract_patterns_handles_malformed_json(self, config):
        """Test graceful handling of malformed JSON."""
        llm = LLMProvider(config)

        with patch.object(llm, "_summarize_claude", return_value="not valid json at all"):
            llm.provider = "claude"
            result = llm.extract_patterns("content")

        assert result == []

    def test_extract_patterns_handles_llm_error(self, config):
        """Test graceful handling of LLM errors."""
        llm = LLMProvider(config)

        with patch.object(llm, "_summarize_claude", side_effect=Exception("API error")):
            llm.provider = "claude"
            result = llm.extract_patterns("content")

        assert result == []
