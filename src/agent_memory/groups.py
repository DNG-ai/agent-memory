"""Workspace group management for cross-project memory sharing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agent_memory.config import Config
from agent_memory.utils import get_timestamp


@dataclass
class WorkspaceGroup:
    """A workspace group containing related projects."""

    name: str
    created_at: datetime
    projects: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "projects": [str(p) for p in self.projects],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceGroup:
        """Create from dictionary."""
        from agent_memory.utils import parse_timestamp

        return cls(
            name=data["name"],
            created_at=parse_timestamp(data["created_at"]),
            projects=[Path(p) for p in data.get("projects", [])],
        )


class GroupManager:
    """Manages workspace groups for cross-project memory sharing."""

    def __init__(self, config: Config):
        """Initialize the group manager.

        Args:
            config: Configuration object
        """
        self.config = config
        self.groups_file = config.base_path / "groups.yaml"
        self._groups: dict[str, WorkspaceGroup] | None = None

    def _load_groups(self) -> dict[str, WorkspaceGroup]:
        """Load groups from file."""
        if self._groups is not None:
            return self._groups

        if not self.groups_file.exists():
            self._groups = {}
            return self._groups

        try:
            with open(self.groups_file) as f:
                data = yaml.safe_load(f) or {}

            self._groups = {}
            for name, group_data in data.get("groups", {}).items():
                group_data["name"] = name
                self._groups[name] = WorkspaceGroup.from_dict(group_data)
        except Exception:
            self._groups = {}

        return self._groups

    def _save_groups(self) -> None:
        """Save groups to file."""
        groups = self._load_groups()

        data = {
            "groups": {
                name: {
                    "created_at": group.created_at.isoformat(),
                    "projects": [str(p) for p in group.projects],
                }
                for name, group in groups.items()
            }
        }

        self.groups_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.groups_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def create(self, name: str) -> WorkspaceGroup:
        """Create a new workspace group.

        Args:
            name: Group name

        Returns:
            The created group

        Raises:
            ValueError: If group already exists
        """
        groups = self._load_groups()

        if name in groups:
            raise ValueError(f"Group '{name}' already exists")

        group = WorkspaceGroup(
            name=name,
            created_at=get_timestamp(),
            projects=[],
        )
        groups[name] = group
        self._save_groups()

        return group

    def delete(self, name: str) -> bool:
        """Delete a workspace group.

        Args:
            name: Group name

        Returns:
            True if deleted, False if not found
        """
        groups = self._load_groups()

        if name not in groups:
            return False

        del groups[name]
        self._save_groups()
        return True

    def get(self, name: str) -> WorkspaceGroup | None:
        """Get a group by name.

        Args:
            name: Group name

        Returns:
            The group or None if not found
        """
        groups = self._load_groups()
        return groups.get(name)

    def list_groups(self) -> list[WorkspaceGroup]:
        """List all workspace groups.

        Returns:
            List of all groups
        """
        groups = self._load_groups()
        return list(groups.values())

    def add_project(self, group_name: str, project_path: Path) -> WorkspaceGroup:
        """Add a project to a group.

        Args:
            group_name: Group name
            project_path: Path to the project

        Returns:
            The updated group

        Raises:
            ValueError: If group doesn't exist
        """
        groups = self._load_groups()

        if group_name not in groups:
            raise ValueError(f"Group '{group_name}' does not exist")

        group = groups[group_name]
        resolved_path = project_path.resolve()

        if resolved_path not in group.projects:
            group.projects.append(resolved_path)
            self._save_groups()

        return group

    def remove_project(self, group_name: str, project_path: Path) -> WorkspaceGroup:
        """Remove a project from a group.

        Args:
            group_name: Group name
            project_path: Path to the project

        Returns:
            The updated group

        Raises:
            ValueError: If group doesn't exist
        """
        groups = self._load_groups()

        if group_name not in groups:
            raise ValueError(f"Group '{group_name}' does not exist")

        group = groups[group_name]
        resolved_path = project_path.resolve()

        if resolved_path in group.projects:
            group.projects.remove(resolved_path)
            self._save_groups()

        return group

    def get_groups_for_project(self, project_path: Path) -> list[WorkspaceGroup]:
        """Get all groups that contain a project.

        Args:
            project_path: Path to the project

        Returns:
            List of groups containing the project
        """
        groups = self._load_groups()
        resolved_path = project_path.resolve()

        return [group for group in groups.values() if resolved_path in group.projects]

    def get_group_members(self, group_name: str) -> list[Path]:
        """Get all project paths in a group.

        Args:
            group_name: Group name

        Returns:
            List of project paths in the group
        """
        group = self.get(group_name)
        if group is None:
            return []
        return group.projects.copy()

    def get_sibling_projects(self, project_path: Path) -> list[Path]:
        """Get all projects that share a group with the given project.

        Args:
            project_path: Path to the project

        Returns:
            List of sibling project paths (excludes the given project)
        """
        resolved_path = project_path.resolve()
        groups = self.get_groups_for_project(project_path)

        siblings: set[Path] = set()
        for group in groups:
            for proj in group.projects:
                if proj != resolved_path:
                    siblings.add(proj)

        return list(siblings)
