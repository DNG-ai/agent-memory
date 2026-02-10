"""Command event log for usage tracking."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agent_memory.config import Config
from agent_memory.utils import get_timestamp


@dataclass
class CommandEvent:
    """A logged command event."""

    id: int
    timestamp: str
    command: str
    subcommand: str | None
    project_path: str | None
    result_count: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


class EventLog:
    """SQLite-based append-only event log for command tracking."""

    def __init__(self, config: Config) -> None:
        self._db_path = config.base_path / "events.db"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
        return self._conn

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    command TEXT NOT NULL,
                    subcommand TEXT,
                    project_path TEXT,
                    result_count INTEGER,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_command ON events(command)
            """)
            conn.commit()
        except Exception:
            pass

    def log(
        self,
        command: str,
        subcommand: str | None = None,
        project_path: str | None = None,
        result_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a command event. Never raises."""
        try:
            conn = self._get_conn()
            now = get_timestamp().isoformat()
            conn.execute(
                """
                INSERT INTO events (timestamp, command, subcommand, project_path, result_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    command,
                    subcommand,
                    project_path,
                    result_count,
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()
        except Exception:
            pass

    def get_command_counts(self, since_days: int = 30) -> dict[str, int]:
        """Get command frequency counts."""
        try:
            conn = self._get_conn()
            cutoff = (get_timestamp() - timedelta(days=since_days)).isoformat()
            cursor = conn.execute(
                """
                SELECT command, subcommand, COUNT(*) as cnt
                FROM events
                WHERE timestamp >= ?
                GROUP BY command, subcommand
                ORDER BY cnt DESC
                """,
                (cutoff,),
            )
            counts: dict[str, int] = {}
            for row in cursor.fetchall():
                command, subcommand, cnt = row
                key = f"{command} {subcommand}" if subcommand else command
                counts[key] = cnt
            return counts
        except Exception:
            return {}

    def get_search_stats(self, since_days: int = 30) -> dict[str, Any]:
        """Get search effectiveness statistics."""
        try:
            conn = self._get_conn()
            cutoff = (get_timestamp() - timedelta(days=since_days)).isoformat()

            # Total searches
            cursor = conn.execute(
                "SELECT COUNT(*) FROM events WHERE command = 'search' AND timestamp >= ?",
                (cutoff,),
            )
            total = cursor.fetchone()[0]

            if total == 0:
                return {
                    "total_searches": 0,
                    "avg_result_count": 0.0,
                    "zero_result_count": 0,
                    "zero_result_rate": 0.0,
                }

            # Average result count
            cursor = conn.execute(
                """
                SELECT AVG(result_count), SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END)
                FROM events
                WHERE command = 'search' AND timestamp >= ? AND result_count IS NOT NULL
                """,
                (cutoff,),
            )
            row = cursor.fetchone()
            avg_results = row[0] or 0.0
            zero_count = row[1] or 0

            return {
                "total_searches": total,
                "avg_result_count": round(avg_results, 1),
                "zero_result_count": zero_count,
                "zero_result_rate": round(zero_count / total, 2) if total > 0 else 0.0,
            }
        except Exception:
            return {
                "total_searches": 0,
                "avg_result_count": 0.0,
                "zero_result_count": 0,
                "zero_result_rate": 0.0,
            }

    def get_session_stats(self, since_days: int = 30) -> dict[str, Any]:
        """Get session compliance statistics."""
        try:
            conn = self._get_conn()
            cutoff = (get_timestamp() - timedelta(days=since_days)).isoformat()

            # Startup count
            cursor = conn.execute(
                "SELECT COUNT(*) FROM events WHERE command = 'startup' AND timestamp >= ?",
                (cutoff,),
            )
            startup_count = cursor.fetchone()[0]

            # Session starts
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE command = 'session' AND subcommand = 'start' AND timestamp >= ?
                """,
                (cutoff,),
            )
            session_starts = cursor.fetchone()[0]

            # Session summarizes
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE command = 'session' AND subcommand = 'summarize' AND timestamp >= ?
                """,
                (cutoff,),
            )
            summarize_count = cursor.fetchone()[0]

            # Session ends
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE command = 'session' AND subcommand = 'end' AND timestamp >= ?
                """,
                (cutoff,),
            )
            session_ends = cursor.fetchone()[0]

            # Summarize rate: summarize_count / max(startup, session_starts, 1)
            total_sessions = max(startup_count, session_starts, 1)
            summarize_rate = round(summarize_count / total_sessions, 2)

            return {
                "startup_count": startup_count,
                "session_starts": session_starts,
                "session_ends": session_ends,
                "summarize_count": summarize_count,
                "summarize_rate": min(summarize_rate, 1.0),
            }
        except Exception:
            return {
                "startup_count": 0,
                "session_starts": 0,
                "session_ends": 0,
                "summarize_count": 0,
                "summarize_rate": 0.0,
            }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
