"""Git-based update check for agent-memory CLI."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

CHECK_INTERVAL = 86400  # 24 hours in seconds
SUBPROCESS_TIMEOUT = 10  # seconds


def _find_repo_path() -> Path | None:
    """Find the git repo path for the agent-memory installation.

    Tries two strategies:
    1. Parse direct_url.json from the dist-info directory (editable installs)
    2. Walk up from this file looking for .git/
    """
    # Strategy 1: dist-info direct_url.json
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("agent-memory")
        for f in dist.files or []:
            if f.name == "direct_url.json":
                direct_url_path = Path(str(dist._path.parent / f))
                if direct_url_path.exists():
                    data = json.loads(direct_url_path.read_text())
                    url = data.get("url", "")
                    if url.startswith("file://"):
                        repo_path = Path(url.removeprefix("file://"))
                        if (repo_path / ".git").is_dir():
                            return repo_path
    except Exception:
        pass

    # Strategy 2: walk up from __file__
    current = Path(__file__).resolve().parent
    for _ in range(10):  # limit depth
        if (current / ".git").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _run_git(repo_path: Path, *args: str) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _get_cache_path(base_path: Path) -> Path:
    return base_path / "update_check.json"


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    try:
        if cache_path.exists():
            return json.loads(cache_path.read_text())
    except Exception:
        pass
    return None


def _write_cache(cache_path: Path, data: dict[str, Any]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))
    except Exception:
        pass


def check_for_updates(config: Any) -> dict[str, Any] | None:
    """Check if the local agent-memory repo is behind the remote.

    Returns {"behind": N, "local": "<sha>", "remote": "<sha>"} or None.
    Results are cached for 24 hours to avoid repeated network calls.
    Never raises — returns None on any failure.
    """
    try:
        cache_path = _get_cache_path(config.base_path)
        cached = _read_cache(cache_path)

        # Return cached result if fresh enough
        if cached and time.time() - cached.get("last_check", 0) < CHECK_INTERVAL:
            return {
                "behind": cached.get("behind", 0),
                "local": cached.get("local_sha", ""),
                "remote": cached.get("remote_sha", ""),
            }

        repo_path = _find_repo_path()
        if not repo_path:
            return None

        # Fetch latest from remote (quiet, no merge)
        _run_git(repo_path, "fetch", "--quiet")

        local_sha = _run_git(repo_path, "rev-parse", "--short", "HEAD")
        remote_sha = _run_git(repo_path, "rev-parse", "--short", "@{u}")
        if not local_sha or not remote_sha:
            return None

        behind_str = _run_git(repo_path, "rev-list", "--count", "HEAD..@{u}")
        behind = int(behind_str) if behind_str else 0

        result = {
            "behind": behind,
            "local": local_sha,
            "remote": remote_sha,
        }

        _write_cache(cache_path, {
            "last_check": time.time(),
            "behind": behind,
            "local_sha": local_sha,
            "remote_sha": remote_sha,
            "repo_path": str(repo_path),
        })

        return result

    except Exception:
        return None
