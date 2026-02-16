"""Configuration management for agent-memory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = {
    "semantic": {
        "enabled": True,
        "provider": "vertex",
        "threshold": 0.7,
        "vertex": {
            "project_id": "",
            "location": "us-central1",
            "model": "gemini-embedding-001",
        },
        "claude": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "model": "voyage-4-lite",
        },
    },
    "llm": {
        # LLM for summarization (compaction). Reuses semantic provider credentials.
        "model": "gemini-3-flash",  # Default model for summarization
        "vertex": {
            "model": "gemini-3-flash",
        },
        "claude": {
            "model": "claude-haiku-4-5-20251001",
        },
    },
    "autosave": {
        "enabled": True,
        "on_task_complete": True,
        "on_remember_request": True,
        "session_summary": True,
        "summary_interval_messages": 20,
    },
    "startup": {
        "auto_load_pinned": True,
        "ask_load_previous_session": True,
    },
    "expiration": {
        "enabled": False,
        "default_days": 90,
        "categories": {
            "task_history": 30,
            "session_summary": 60,
            "factual": None,
            "decision": None,
        },
    },
    "relevance": {
        "search_limit": 5,
        "include_global": True,
        "access_weight": 0.1,
    },
    "hooks": {
        "error_nudge": False,
    },
}


@dataclass
class SemanticConfig:
    """Semantic search configuration."""

    enabled: bool = True
    provider: str = "vertex"
    threshold: float = 0.7
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-embedding-001"
    claude_api_key_env: str = "ANTHROPIC_API_KEY"
    claude_model: str = "voyage-4-lite"


@dataclass
class AutosaveConfig:
    """Autosave configuration.

    Note: ``on_task_complete``, ``session_summary``, and
    ``summary_interval_messages`` are advisory hints exposed in startup
    output.  They are NOT enforced by agent-memory itself — the calling
    agent is responsible for honoring them.
    """

    enabled: bool = True
    on_task_complete: bool = True
    on_remember_request: bool = True
    session_summary: bool = True
    summary_interval_messages: int = 20


@dataclass
class StartupConfig:
    """Startup behavior configuration."""

    auto_load_pinned: bool = True
    ask_load_previous_session: bool = True


@dataclass
class ExpirationConfig:
    """Memory expiration configuration."""

    enabled: bool = False
    default_days: int = 90
    category_days: dict[str, int | None] = field(default_factory=dict)


@dataclass
class RelevanceConfig:
    """Relevance scoring configuration."""

    search_limit: int = 5
    include_global: bool = True
    access_weight: float = 0.1


@dataclass
class HooksConfig:
    """Hooks configuration for agent integrations."""

    error_nudge: bool = False


@dataclass
class LLMConfig:
    """LLM configuration for summarization (compaction).

    Reuses the same provider as semantic search but with a different model.
    """

    model: str = "gemini-3-flash"
    vertex_model: str = "gemini-3-flash"
    claude_model: str = "claude-haiku-4-5-20251001"


@dataclass
class Config:
    """Main configuration object."""

    base_path: Path
    semantic: SemanticConfig
    autosave: AutosaveConfig
    startup: StartupConfig
    expiration: ExpirationConfig
    relevance: RelevanceConfig
    llm: LLMConfig
    hooks: HooksConfig

    @property
    def global_path(self) -> Path:
        """Path to global memory storage."""
        return self.base_path / "global"

    @property
    def projects_path(self) -> Path:
        """Path to project-specific memory storage."""
        return self.base_path / "projects"

    @property
    def config_file(self) -> Path:
        """Path to configuration file."""
        return self.base_path / "config.yaml"


def get_base_path() -> Path:
    """Get the base path for agent-memory storage."""
    env_path = os.environ.get("AGENT_MEMORY_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".agent-memory"


def ensure_directories(base_path: Path) -> None:
    """Ensure all required directories exist."""
    base_path.mkdir(parents=True, exist_ok=True)
    (base_path / "global").mkdir(exist_ok=True)
    (base_path / "global" / "summaries").mkdir(exist_ok=True)
    (base_path / "projects").mkdir(exist_ok=True)


def load_config(base_path: Path | None = None) -> Config:
    """Load configuration from file or create default."""
    if base_path is None:
        base_path = get_base_path()

    ensure_directories(base_path)
    config_file = base_path / "config.yaml"

    if config_file.exists():
        with open(config_file) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
        save_config_data(config_file, DEFAULT_CONFIG)

    # Merge with defaults
    merged = _deep_merge(DEFAULT_CONFIG.copy(), data)

    return _build_config(base_path, merged)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _build_config(base_path: Path, data: dict[str, Any]) -> Config:
    """Build Config object from dictionary data."""
    semantic_data = data.get("semantic", {})
    semantic = SemanticConfig(
        enabled=semantic_data.get("enabled", True),
        provider=semantic_data.get("provider", "vertex"),
        threshold=semantic_data.get("threshold", 0.7),
        vertex_project_id=semantic_data.get("vertex", {}).get("project_id", ""),
        vertex_location=semantic_data.get("vertex", {}).get("location", "us-central1"),
        vertex_model=semantic_data.get("vertex", {}).get("model", "gemini-embedding-001"),
        claude_api_key_env=semantic_data.get("claude", {}).get("api_key_env", "ANTHROPIC_API_KEY"),
        claude_model=semantic_data.get("claude", {}).get("model", "voyage-4-lite"),
    )

    autosave_data = data.get("autosave", {})
    autosave = AutosaveConfig(
        enabled=autosave_data.get("enabled", True),
        on_task_complete=autosave_data.get("on_task_complete", True),
        on_remember_request=autosave_data.get("on_remember_request", True),
        session_summary=autosave_data.get("session_summary", True),
        summary_interval_messages=autosave_data.get("summary_interval_messages", 20),
    )

    startup_data = data.get("startup", {})
    startup = StartupConfig(
        auto_load_pinned=startup_data.get("auto_load_pinned", True),
        ask_load_previous_session=startup_data.get("ask_load_previous_session", True),
    )

    expiration_data = data.get("expiration", {})
    expiration = ExpirationConfig(
        enabled=expiration_data.get("enabled", False),
        default_days=expiration_data.get("default_days", 90),
        category_days=expiration_data.get("categories", {}),
    )

    relevance_data = data.get("relevance", {})
    relevance = RelevanceConfig(
        search_limit=relevance_data.get("search_limit", 5),
        include_global=relevance_data.get("include_global", True),
        access_weight=relevance_data.get("access_weight", 0.1),
    )

    llm_data = data.get("llm", {})
    llm = LLMConfig(
        model=llm_data.get("model", "gemini-3-flash"),
        vertex_model=llm_data.get("vertex", {}).get("model", "gemini-3-flash"),
        claude_model=llm_data.get("claude", {}).get("model", "claude-haiku-4-5-20251001"),
    )

    hooks_data = data.get("hooks", {})
    hooks = HooksConfig(
        error_nudge=hooks_data.get("error_nudge", False),
    )

    return Config(
        base_path=base_path,
        semantic=semantic,
        autosave=autosave,
        startup=startup,
        expiration=expiration,
        relevance=relevance,
        llm=llm,
        hooks=hooks,
    )


def save_config_data(config_file: Path, data: dict[str, Any]) -> None:
    """Save configuration data to file."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def update_config(config: Config, key_path: str, value: Any) -> Config:
    """Update a configuration value and save."""
    # Load current data
    if config.config_file.exists():
        with open(config.config_file) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = DEFAULT_CONFIG.copy()

    # Parse key path (e.g., "semantic.enabled")
    keys = key_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Convert value if needed
    if value.lower() in ("true", "on", "yes"):
        value = True
    elif value.lower() in ("false", "off", "no"):
        value = False
    elif value.replace(".", "").isdigit():
        value = float(value) if "." in value else int(value)

    current[keys[-1]] = value

    # Save and reload
    save_config_data(config.config_file, data)
    return load_config(config.base_path)


def get_project_path(config: Config, project_dir: Path) -> Path:
    """Get storage path for a specific project."""
    # Use a hash of the project path to create a unique directory
    import hashlib

    project_hash = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:16]
    project_storage = config.projects_path / project_hash

    # Store a reference to the original path
    project_storage.mkdir(parents=True, exist_ok=True)
    ref_file = project_storage / ".project_path"
    if not ref_file.exists():
        ref_file.write_text(str(project_dir.resolve()))

    (project_storage / "summaries").mkdir(exist_ok=True)

    return project_storage


def resolve_project_from_hash(config: Config, project_hash: str) -> Path | None:
    """Resolve original project path from hash."""
    project_storage = config.projects_path / project_hash
    ref_file = project_storage / ".project_path"
    if ref_file.exists():
        return Path(ref_file.read_text().strip())
    return None


def find_descendant_project_paths(
    config: Config,
    parent_dir: Path,
    max_results: int = 20,
) -> list[tuple[Path, Path]]:
    """Find stored projects that are strict descendants of parent_dir.

    Scans ~/.agent-memory/projects/, reads each .project_path ref file, and
    returns those whose original path is a strict child of parent_dir.

    Args:
        config: Configuration object
        parent_dir: The parent directory to search descendants for
        max_results: Maximum number of results to return

    Returns:
        List of (original_project_path, storage_path) tuples
    """
    parent_resolved = parent_dir.resolve()

    # Safety: skip if parent has <= 2 path components (e.g. "/" or "/Users")
    if len(parent_resolved.parts) <= 2:
        return []

    projects_dir = config.projects_path
    if not projects_dir.exists():
        return []

    results: list[tuple[Path, Path]] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ref_file = project_dir / ".project_path"
        if not ref_file.exists():
            continue

        try:
            original_path = Path(ref_file.read_text().strip())
        except Exception:
            continue

        # Must be a strict descendant (not equal to parent)
        try:
            original_path.relative_to(parent_resolved)
        except ValueError:
            continue

        if original_path == parent_resolved:
            continue

        results.append((original_path, project_dir))

        if len(results) >= max_results:
            break

    return results
