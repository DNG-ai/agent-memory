"""Tests for utility functions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_memory.utils import (
    calculate_expiration,
    detect_category,
    format_timestamp,
    generate_memory_id,
    generate_session_id,
    get_category_display_name,
    get_timestamp,
    is_expired,
    is_valid_category,
    normalize_category,
    truncate_text,
)


class TestGenerateIds:
    """Tests for ID generation."""

    def test_generate_memory_id(self) -> None:
        """Test memory ID generation."""
        id1 = generate_memory_id()
        id2 = generate_memory_id()

        assert id1.startswith("mem_")
        assert id2.startswith("mem_")
        assert id1 != id2
        assert len(id1) == 16  # "mem_" + 12 hex chars

    def test_generate_session_id(self) -> None:
        """Test session ID generation."""
        id1 = generate_session_id()
        id2 = generate_session_id()

        assert id1.startswith("sess_")
        assert id2.startswith("sess_")
        assert id1 != id2


class TestTimestamp:
    """Tests for timestamp functions."""

    def test_get_timestamp(self) -> None:
        """Test getting current timestamp."""
        ts = get_timestamp()

        assert isinstance(ts, datetime)
        assert ts.tzinfo == timezone.utc

    def test_format_timestamp(self) -> None:
        """Test timestamp formatting."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        formatted = format_timestamp(ts)

        assert "2024-01-15" in formatted
        assert "10:30:00" in formatted
        assert "UTC" in formatted


class TestCategoryDetection:
    """Tests for category detection."""

    def test_detect_decision_category(self) -> None:
        """Test detection of decision category."""
        assert detect_category("User prefers functional components") == "decision"
        assert detect_category("We chose to use Redux") == "decision"
        assert detect_category("Rejected the class-based approach") == "decision"
        assert detect_category("Always use type hints") == "decision"
        assert detect_category("Never use var in TypeScript") == "decision"

    def test_detect_task_history_category(self) -> None:
        """Test detection of task history category."""
        assert detect_category("Implemented the login feature") == "task_history"
        assert detect_category("Fixed the authentication bug") == "task_history"
        assert detect_category("Added new API endpoint") == "task_history"
        assert detect_category("Refactored the user module") == "task_history"

    def test_detect_session_summary_category(self) -> None:
        """Test detection of session summary category."""
        assert detect_category("Session summary: worked on auth") == "session_summary"
        assert detect_category("Today we discussed the API design") == "session_summary"
        assert detect_category("In this session we covered testing") == "session_summary"

    def test_detect_factual_category(self) -> None:
        """Test detection of factual category (default)."""
        assert detect_category("The API uses REST") == "factual"
        assert detect_category("Database is PostgreSQL") == "factual"
        assert detect_category("Port 8080 is used for the server") == "factual"

    def test_is_valid_category(self) -> None:
        """Test category validation."""
        assert is_valid_category("factual") is True
        assert is_valid_category("decision") is True
        assert is_valid_category("task_history") is True
        assert is_valid_category("session_summary") is True
        assert is_valid_category("invalid") is False
        assert is_valid_category("") is False

    def test_normalize_category(self) -> None:
        """Test category normalization."""
        # Valid category passes through
        assert normalize_category("factual", "") == "factual"
        assert normalize_category("decision", "") == "decision"

        # None triggers auto-detection
        assert normalize_category(None, "User prefers X") == "decision"
        assert normalize_category(None, "The API uses REST") == "factual"

        # Invalid category triggers auto-detection
        assert normalize_category("invalid", "User prefers X") == "decision"

    def test_get_category_display_name(self) -> None:
        """Test category display names."""
        assert get_category_display_name("factual") == "Factual Knowledge"
        assert get_category_display_name("decision") == "Decision"
        assert get_category_display_name("task_history") == "Task History"
        assert get_category_display_name("session_summary") == "Session Summary"
        assert get_category_display_name("unknown") == "Unknown"


class TestTextUtils:
    """Tests for text utility functions."""

    def test_truncate_text_short(self) -> None:
        """Test truncating text shorter than limit."""
        text = "Short text"
        assert truncate_text(text, 100) == "Short text"

    def test_truncate_text_at_limit(self) -> None:
        """Test truncating text at exact limit."""
        text = "Exactly 10"
        assert truncate_text(text, 10) == "Exactly 10"

    def test_truncate_text_over_limit(self) -> None:
        """Test truncating text over limit."""
        text = "This is a longer text that should be truncated"
        truncated = truncate_text(text, 20)

        assert len(truncated) == 20
        assert truncated.endswith("...")


class TestExpiration:
    """Tests for expiration functions."""

    def test_calculate_expiration_with_days(self) -> None:
        """Test calculating expiration date."""
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expires = calculate_expiration(created, 30)

        assert expires is not None
        assert expires == datetime(2024, 1, 31, tzinfo=timezone.utc)

    def test_calculate_expiration_none(self) -> None:
        """Test calculating expiration with no days (never expires)."""
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expires = calculate_expiration(created, None)

        assert expires is None

    def test_is_expired_past(self) -> None:
        """Test checking if a past date is expired."""
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert is_expired(past) is True

    def test_is_expired_future(self) -> None:
        """Test checking if a future date is expired."""
        future = get_timestamp() + timedelta(days=30)
        assert is_expired(future) is False

    def test_is_expired_none(self) -> None:
        """Test checking if None (never expires) is expired."""
        assert is_expired(None) is False
