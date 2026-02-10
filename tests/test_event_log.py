"""Tests for the event log module."""

from __future__ import annotations

import pytest

from agent_memory.config import Config
from agent_memory.event_log import EventLog


class TestEventLog:
    """Tests for EventLog."""

    def test_log_and_get_command_counts(self, config: Config) -> None:
        """Test logging events and retrieving command counts."""
        log = EventLog(config)
        try:
            log.log("save", project_path="/test")
            log.log("save", project_path="/test")
            log.log("search", project_path="/test", result_count=3)
            log.log("startup", project_path="/test")

            counts = log.get_command_counts(since_days=1)
            assert counts["save"] == 2
            assert counts["search"] == 1
            assert counts["startup"] == 1
        finally:
            log.close()

    def test_log_with_subcommand(self, config: Config) -> None:
        """Test logging events with subcommands."""
        log = EventLog(config)
        try:
            log.log("session", subcommand="start")
            log.log("session", subcommand="summarize")
            log.log("session", subcommand="summarize")

            counts = log.get_command_counts(since_days=1)
            assert counts["session start"] == 1
            assert counts["session summarize"] == 2
        finally:
            log.close()

    def test_log_with_metadata(self, config: Config) -> None:
        """Test logging events with metadata."""
        log = EventLog(config)
        try:
            log.log("search", result_count=5, metadata={"query": "test query"})
            counts = log.get_command_counts(since_days=1)
            assert counts["search"] == 1
        finally:
            log.close()

    def test_get_search_stats(self, config: Config) -> None:
        """Test search statistics aggregation."""
        log = EventLog(config)
        try:
            log.log("search", result_count=5, metadata={"query": "q1"})
            log.log("search", result_count=3, metadata={"query": "q2"})
            log.log("search", result_count=0, metadata={"query": "q3"})

            stats = log.get_search_stats(since_days=1)
            assert stats["total_searches"] == 3
            assert stats["avg_result_count"] == pytest.approx(2.7, abs=0.1)
            assert stats["zero_result_count"] == 1
            assert stats["zero_result_rate"] == pytest.approx(0.33, abs=0.01)
        finally:
            log.close()

    def test_get_search_stats_empty(self, config: Config) -> None:
        """Test search stats with no data."""
        log = EventLog(config)
        try:
            stats = log.get_search_stats(since_days=1)
            assert stats["total_searches"] == 0
            assert stats["avg_result_count"] == 0.0
            assert stats["zero_result_count"] == 0
            assert stats["zero_result_rate"] == 0.0
        finally:
            log.close()

    def test_get_session_stats(self, config: Config) -> None:
        """Test session compliance statistics."""
        log = EventLog(config)
        try:
            log.log("startup")
            log.log("startup")
            log.log("session", subcommand="start")
            log.log("session", subcommand="summarize")
            log.log("session", subcommand="end")

            stats = log.get_session_stats(since_days=1)
            assert stats["startup_count"] == 2
            assert stats["session_starts"] == 1
            assert stats["session_ends"] == 1
            assert stats["summarize_count"] == 1
            assert stats["summarize_rate"] == 0.5  # 1 summarize / 2 startups
        finally:
            log.close()

    def test_get_session_stats_empty(self, config: Config) -> None:
        """Test session stats with no data."""
        log = EventLog(config)
        try:
            stats = log.get_session_stats(since_days=1)
            assert stats["startup_count"] == 0
            assert stats["session_starts"] == 0
            assert stats["summarize_count"] == 0
            assert stats["summarize_rate"] == 0.0
        finally:
            log.close()

    def test_log_never_raises(self, config: Config) -> None:
        """Test that log() never raises exceptions."""
        log = EventLog(config)
        try:
            # Close connection to force an error scenario
            log.close()
            # This should not raise
            log.log("save")
        finally:
            log.close()

    def test_command_counts_filtered_by_time(self, config: Config) -> None:
        """Test that command counts respect time filter."""
        log = EventLog(config)
        try:
            log.log("save")
            log.log("search", result_count=1)

            # Since 1 day should include recent events
            counts = log.get_command_counts(since_days=1)
            assert "save" in counts
            assert "search" in counts
        finally:
            log.close()
