"""Utility functions for agent-memory."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def generate_memory_id() -> str:
    """Generate a unique memory ID."""
    return f"mem_{uuid.uuid4().hex[:12]}"


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"sess_{uuid.uuid4().hex[:12]}"


def get_timestamp() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_timestamp(s: str) -> datetime:
    """Parse ISO format timestamp string."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hash_project_path(project_path: Path) -> str:
    """Create a hash of a project path for storage."""
    return hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:16]


def detect_category(content: str) -> str:
    """Attempt to auto-detect memory category from content.

    Categories:
    - factual: Facts about codebase, architecture, patterns
    - decision: User preferences, choices made, rejected options
    - task_history: Completed tasks, what was done
    - session_summary: Conversation summaries
    """
    content_lower = content.lower()

    # Decision indicators
    decision_keywords = [
        "prefer",
        "chose",
        "decided",
        "rejected",
        "instead of",
        "rather than",
        "don't use",
        "always use",
        "never use",
        "should use",
        "shouldn't",
    ]
    if any(keyword in content_lower for keyword in decision_keywords):
        return "decision"

    # Task history indicators
    task_keywords = [
        "completed",
        "implemented",
        "fixed",
        "added",
        "removed",
        "refactored",
        "updated",
        "created",
        "deployed",
        "migrated",
    ]
    if any(keyword in content_lower for keyword in task_keywords):
        return "task_history"

    # Session summary indicators
    summary_keywords = [
        "session",
        "summary",
        "discussed",
        "covered",
        "worked on",
        "today we",
        "in this session",
    ]
    if any(keyword in content_lower for keyword in summary_keywords):
        return "session_summary"

    # Default to factual
    return "factual"


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text for display."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def serialize_metadata(metadata: dict[str, Any] | None) -> str:
    """Serialize metadata to JSON string."""
    if metadata is None:
        return "{}"
    return json.dumps(metadata)


def deserialize_metadata(metadata_str: str) -> dict[str, Any]:
    """Deserialize metadata from JSON string."""
    if not metadata_str:
        return {}
    return json.loads(metadata_str)


def get_current_project_path() -> Path:
    """Get the current working directory as project path."""
    return Path.cwd()


def is_valid_category(category: str) -> bool:
    """Check if category is valid."""
    return category in {"factual", "decision", "task_history", "session_summary"}


def normalize_category(category: str | None, content: str = "") -> str:
    """Normalize and validate category, auto-detecting if needed."""
    if category is None or not is_valid_category(category):
        return detect_category(content)
    return category


CATEGORY_DISPLAY_NAMES = {
    "factual": "Factual Knowledge",
    "decision": "Decision",
    "task_history": "Task History",
    "session_summary": "Session Summary",
}


def get_category_display_name(category: str) -> str:
    """Get display name for category."""
    return CATEGORY_DISPLAY_NAMES.get(category, category.title())


def calculate_expiration(created_at: datetime, days: int | None) -> datetime | None:
    """Calculate expiration datetime."""
    if days is None:
        return None
    from datetime import timedelta

    return created_at + timedelta(days=days)


def is_expired(expires_at: datetime | None) -> bool:
    """Check if a memory is expired."""
    if expires_at is None:
        return False
    return get_timestamp() > expires_at
