"""Command-line interface for agent-memory."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from agent_memory.config import (
    Config,
    get_base_path,
    load_config,
    update_config,
)
from agent_memory.store import Memory, MemoryStore
from agent_memory.utils import (
    format_timestamp,
    get_category_display_name,
    get_current_project_path,
    is_valid_category,
    truncate_text,
)

console = Console()


def _record_access_for_memories(store: MemoryStore, memories: list[Memory]) -> None:
    """Record access for memories, grouped by scope. Never raises."""
    try:
        by_scope: dict[str, list[str]] = {}
        for m in memories:
            by_scope.setdefault(m.scope, []).append(m.id)
        for scope, ids in by_scope.items():
            store.record_access_batch(ids, scope)
    except Exception:
        pass


def get_store(config: Config, project_path: Path | None = None) -> MemoryStore:
    """Get a memory store instance."""
    if project_path is None:
        project_path = get_current_project_path()
    return MemoryStore(config, project_path)


def get_vector_store(config: Config, project_path: Path | None = None):
    """Get a vector store instance if semantic search is enabled."""
    if not config.semantic.enabled:
        return None

    try:
        from agent_memory.vector_store import VectorStore

        if project_path is None:
            project_path = get_current_project_path()
        return VectorStore(config, project_path)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not initialize vector store: {e}[/yellow]")
        return None


def display_memory(memory: Memory, verbose: bool = False) -> None:
    """Display a single memory."""
    pin_indicator = "[red]*[/red] " if memory.pinned else ""
    category_label = get_category_display_name(memory.category)

    console.print(f"\n{pin_indicator}[bold]{memory.id}[/bold] [{category_label}]")
    console.print(f"  {memory.content}")

    if verbose:
        console.print(f"  [dim]Created: {format_timestamp(memory.created_at)}[/dim]")
        console.print(f"  [dim]Scope: {memory.scope}[/dim]")
        console.print(f"  [dim]Source: {memory.source}[/dim]")
        if memory.metadata:
            console.print(f"  [dim]Metadata: {json.dumps(memory.metadata)}[/dim]")


def display_memories_table(memories: list[Memory], title: str = "Memories") -> None:
    """Display memories in a table."""
    if not memories:
        console.print("[dim]No memories found.[/dim]")
        return

    table = Table(title=title)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Pin", style="red", width=3)
    table.add_column("Category", style="green")
    table.add_column("Content", style="white")
    table.add_column("Created", style="dim")

    for memory in memories:
        table.add_row(
            memory.id,
            "*" if memory.pinned else "",
            memory.category,
            truncate_text(memory.content, 60),
            memory.created_at.strftime("%Y-%m-%d"),
        )

    console.print(table)


def display_cross_project_memories(
    results: list[tuple[Path | None, list[Memory]]],
    title: str = "Memories (All Projects)",
) -> None:
    """Display memories from multiple projects, grouped by project."""
    total_count = sum(len(memories) for _, memories in results)
    if total_count == 0:
        console.print("[dim]No memories found.[/dim]")
        return

    console.print(f"\n[bold]{title}[/bold] ({total_count} total)\n")

    for project_path, memories in results:
        if not memories:
            continue

        # Project header with full path
        project_label = (
            "[yellow]GLOBAL[/yellow]" if project_path is None else f"[blue]{project_path}[/blue]"
        )
        console.print(f"{'─' * 60}")
        console.print(project_label)
        console.print(f"{'─' * 60}")

        # Table for this project's memories
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Pin", style="red", width=3)
        table.add_column("Category", style="green")
        table.add_column("Content", style="white")
        table.add_column("Created", style="dim")

        for memory in memories:
            table.add_row(
                memory.id,
                "*" if memory.pinned else "",
                memory.category,
                truncate_text(memory.content, 50),
                memory.created_at.strftime("%Y-%m-%d"),
            )

        console.print(table)
        console.print("")  # Blank line between projects


@click.group()
@click.version_option()
@click.pass_context
def main(ctx: click.Context) -> None:
    """Agent Memory - Long-term memory store for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()

    from agent_memory.event_log import EventLog

    ctx.obj["event_log"] = EventLog(ctx.obj["config"])


# ─────────────────────────────────────────────────────────────
# PROJECTS COMMAND (cross-project visibility for users)
# ─────────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def projects(ctx: click.Context) -> None:
    """List all tracked projects with memory counts."""
    config: Config = ctx.obj["config"]

    with get_store(config) as store:
        stats = store.get_all_project_stats()

        if not stats:
            console.print("[dim]No projects with memories found.[/dim]")
            return

        console.print("\n[bold]Tracked Projects[/bold]\n")

        for stat in stats:
            last_updated = (
                stat["last_updated"].strftime("%Y-%m-%d %H:%M") if stat["last_updated"] else "Never"
            )
            memory_count = stat["memory_count"]
            project_path = stat["project_path"]

            # Color based on memory count
            count_style = "green" if memory_count > 0 else "dim"

            console.print(f"[blue]{project_path}[/blue]")
            console.print(
                f"  [{count_style}]{memory_count} memories[/{count_style}] | Last updated: {last_updated}"
            )
            console.print("")


# ─────────────────────────────────────────────────────────────
# SAVE COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("content")
@click.option("--global", "is_global", is_flag=True, help="Save to global scope (true global)")
@click.option(
    "--group", "group_names", help="Save to group scope with comma-separated owner groups"
)
@click.option("--pin", is_flag=True, help="Pin this memory")
@click.option(
    "--category",
    type=click.Choice(["factual", "decision", "task_history", "session_summary"]),
    help="Memory category (auto-detected if not specified)",
)
@click.option(
    "--meta",
    multiple=True,
    help="Add metadata as key=value (repeatable, e.g. --meta rationale='...' --meta status=approved)",
)
@click.pass_context
def save(
    ctx: click.Context,
    content: str,
    is_global: bool,
    group_names: str | None,
    pin: bool,
    category: str | None,
    meta: tuple[str, ...],
) -> None:
    """Save a new memory.

    Scopes:
        (default)  Project scope - private to current project
        --group=X  Group scope - visible only with --groups=X on startup
        --global   Global scope - visible to all projects always
    """
    config: Config = ctx.obj["config"]

    # Determine scope
    if is_global and group_names:
        console.print("[red]Cannot use both --global and --group[/red]")
        sys.exit(1)

    if group_names:
        scope = "group"
        groups = [g.strip() for g in group_names.split(",")]
    elif is_global:
        scope = "global"
        groups = None
    else:
        scope = "project"
        groups = None

    # Parse --meta key=value pairs
    metadata: dict[str, Any] | None = None
    if meta:
        metadata = {}
        for item in meta:
            if "=" not in item:
                console.print(f"[red]Invalid metadata format: '{item}'. Use key=value[/red]")
                sys.exit(1)
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                console.print("[red]Metadata key cannot be empty[/red]")
                sys.exit(1)
            metadata[key] = value

    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        memory = store.save(
            content=content,
            category=category,
            scope=scope,
            pinned=pin,
            source="user_explicit",
            metadata=metadata,
            groups=groups,
        )

        # Add to vector store
        vector_store = get_vector_store(config, project_path)
        if vector_store:
            try:
                vector_store.add(
                    memory_id=memory.id,
                    content=content,
                    category=memory.category,
                    scope=scope,
                    groups=groups,
                )
            except Exception as e:
                console.print(f"[yellow]Warning: Could not add to vector store: {e}[/yellow]")

    console.print(f"[green]Saved memory:[/green] {memory.id}")
    console.print(f"  Scope: {scope}")
    console.print(f"  Category: {get_category_display_name(memory.category)}")
    console.print(f"  Content: {truncate_text(content, 80)}")
    if pin:
        console.print("  [red]Pinned[/red]")
    if groups:
        console.print(f"  [blue]Groups: {', '.join(groups)}[/blue]")
    if metadata:
        console.print(f"  [dim]Metadata: {json.dumps(metadata)}[/dim]")

    try:
        ctx.obj["event_log"].log(
            "save",
            project_path=str(project_path) if project_path else None,
            metadata={"scope": scope, "category": memory.category, "pinned": pin},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# SEARCH COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("query")
@click.option("--limit", default=5, help="Maximum results")
@click.option("--threshold", type=float, help="Similarity threshold (0.0-1.0)")
@click.option("--global", "include_global", is_flag=True, help="Include global memories")
@click.option(
    "--category",
    type=click.Choice(["factual", "decision", "task_history", "session_summary"]),
    help="Filter by category",
)
@click.option(
    "--all-projects",
    is_flag=True,
    help="Search across all projects (user visibility, not for agents)",
)
@click.option(
    "--group",
    "group_name",
    help="Include memories from this group in search (works from any directory)",
)
@click.option(
    "--exact",
    is_flag=True,
    help="Only search the exact current project (no descendant lookup)",
)
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    limit: int,
    threshold: float | None,
    include_global: bool,
    category: str | None,
    all_projects: bool,
    group_name: str | None,
    exact: bool,
) -> None:
    """Search memories by query.

    By default, includes memories from descendant projects (hierarchical lookup).
    Use --exact to only search the current project directory.
    """
    config: Config = ctx.obj["config"]

    # Cross-project mode (for users, not agents)
    if all_projects:
        with get_store(config) as store:
            results = store.search_all_projects(
                query=query,
                limit_per_project=limit,
                include_global=True,
            )

            # Filter by category if specified
            if category:
                filtered_results = []
                for project_path, memories in results:
                    filtered = [m for m in memories if m.category == category]
                    if filtered:
                        filtered_results.append((project_path, filtered))
                results = filtered_results

            display_cross_project_memories(results, f"Search Results: '{query}'")
        return

    # Group search mode - search across project + global + specified group
    if group_name:
        with get_store(config) as store:
            groups = [group_name] if group_name.lower() != "all" else None
            keyword_results = store.search_with_groups(
                query=query,
                include_project=True,
                include_global=True,
                include_groups=groups,
                limit=limit,
            )

            if category:
                keyword_results = [m for m in keyword_results if m.category == category]

            if keyword_results:
                _record_access_for_memories(store, keyword_results)
                title = f"Search Results: '{query}'"
                if group_name.lower() != "all":
                    title += f" (including group '{group_name}')"
                else:
                    title += " (including all groups)"
                console.print(f"\n[bold]{title}[/bold] ({len(keyword_results)} found)")
                display_memories_table(keyword_results)
            else:
                console.print("[dim]No memories found matching your query.[/dim]")

            try:
                ctx.obj["event_log"].log(
                    "search",
                    project_path=str(get_current_project_path()),
                    result_count=len(keyword_results),
                    metadata={"query": query},
                )
            except Exception:
                pass
        return

    # Standard mode
    project_path = get_current_project_path()
    results_found = False

    # Try semantic search first
    vector_store = get_vector_store(config, project_path)
    if vector_store and vector_store.is_enabled():
        try:
            from agent_memory.vector_store import VectorSearchResult

            results = vector_store.search_combined(
                query=query,
                limit=limit,
                threshold=threshold,
                category=category,
                include_descendants=not exact,
            )

            if results:
                results_found = True
                console.print(f"\n[bold]Semantic Search Results[/bold] ({len(results)} found)")
                for result in results:
                    console.print(
                        f"\n[cyan]{result.memory_id}[/cyan] [dim](score: {result.score:.2f})[/dim]"
                    )
                    console.print(f"  [{result.category}] {result.content}")

        except Exception as e:
            console.print(f"[yellow]Semantic search failed: {e}[/yellow]")

    # Keyword fallback
    with get_store(config, project_path) as store:
        if exact:
            keyword_results = store.search_keyword(query, "project", limit)
        else:
            keyword_results = store.search_with_descendants(query, limit)

        if include_global:
            keyword_results.extend(store.search_keyword(query, "global", limit))

        if category:
            keyword_results = [m for m in keyword_results if m.category == category]

        # Deduplicate
        seen_ids: set[str] = set()
        unique_results: list[Memory] = []
        for m in keyword_results:
            if m.id not in seen_ids:
                unique_results.append(m)
                seen_ids.add(m.id)
        keyword_results = unique_results[:limit]

        if keyword_results:
            results_found = True
            _record_access_for_memories(store, keyword_results)
            console.print(f"\n[bold]Keyword Search Results[/bold] ({len(keyword_results)} found)")
            display_memories_table(keyword_results)

    if not results_found:
        console.print("[dim]No memories found matching your query.[/dim]")

    try:
        total_results = len(keyword_results) if keyword_results else 0
        ctx.obj["event_log"].log(
            "search",
            project_path=str(project_path),
            result_count=total_results,
            metadata={"query": query},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# LIST COMMAND
# ─────────────────────────────────────────────────────────────
@main.command("list")
@click.option("--global", "is_global", is_flag=True, help="List global memories")
@click.option("--pinned", is_flag=True, help="Show only pinned memories")
@click.option(
    "--category",
    type=click.Choice(["factual", "decision", "task_history", "session_summary"]),
    help="Filter by category",
)
@click.option("--limit", default=20, help="Maximum results")
@click.option(
    "--all-projects",
    is_flag=True,
    help="List from all projects (user visibility, not for agents)",
)
@click.option(
    "--group",
    "group_name",
    help="List memories owned by a group (use 'all' for all groups). Works from any directory.",
)
@click.option("--group-owned", is_flag=True, help="Show only group-scoped memories")
@click.option("--owned-by", "owned_by_group", help="Show memories owned by a specific group")
@click.option(
    "--include-group-owned",
    is_flag=True,
    help="With --global, also include group-scoped memories",
)
@click.option(
    "--exact",
    is_flag=True,
    help="Only show memories from the exact current project (no descendant lookup)",
)
@click.pass_context
def list_memories(
    ctx: click.Context,
    is_global: bool,
    pinned: bool,
    category: str | None,
    limit: int,
    all_projects: bool,
    group_name: str | None,
    group_owned: bool,
    owned_by_group: str | None,
    include_group_owned: bool,
    exact: bool,
) -> None:
    """List memories.

    By default, includes memories from descendant projects (hierarchical lookup).
    Use --exact to only list memories from the current project directory.
    """
    config: Config = ctx.obj["config"]

    # Cross-project mode (for users, not agents)
    if all_projects:
        with get_store(config) as store:
            results = store.list_all_projects(
                category=category,
                pinned_only=pinned,
                limit_per_project=limit,
                include_global=True,
            )

            # Filter by group ownership if requested
            if group_owned or owned_by_group:
                filtered_results = []
                for project_path, memories in results:
                    if owned_by_group:
                        filtered = [m for m in memories if owned_by_group in m.groups]
                    else:
                        filtered = [m for m in memories if m.scope == "group"]
                    if filtered:
                        filtered_results.append((project_path, filtered))
                results = filtered_results

            title = "Memories (All Projects)"
            if pinned:
                title += " - Pinned"
            if group_owned:
                title += " - Group-scoped"
            if owned_by_group:
                title += f" - Owned by '{owned_by_group}'"
            if category:
                title += f" [{category}]"

            display_cross_project_memories(results, title)
        return

    # Group mode - list memories by group name (works from any directory)
    if group_name:
        with get_store(config) as store:
            memories = store.list_by_group(
                group_name=group_name,
                pinned_only=pinned,
                category=category,
                limit=limit,
            )
            title = "Group Memories"
            if group_name.lower() != "all":
                title = f"Group '{group_name}' Memories"
            if pinned:
                title += " (Pinned)"
            if category:
                title += f" [{category}]"
            display_memories_table(memories, title)
        return

    # Standard mode
    project_path = None if is_global else get_current_project_path()

    with get_store(config, project_path) as store:
        if is_global:
            # Get global scope memories
            memories = store.list(
                scope="global",
                category=category,
                pinned_only=pinned,
                limit=limit,
            )
            # Optionally include group-scoped memories
            if include_group_owned:
                group_memories = store.list(
                    scope="group",
                    category=category,
                    pinned_only=pinned,
                    limit=limit,
                )
                memories.extend(group_memories)
        elif exact:
            # Exact mode: only current project
            memories = store.list(
                scope="project",
                category=category,
                pinned_only=pinned,
                limit=limit,
            )
        else:
            # Default: include descendant projects
            memories = store.list_with_descendants(
                category=category,
                pinned_only=pinned,
                limit=limit,
            )

        # Filter by group ownership if requested
        if group_owned:
            memories = [m for m in memories if m.scope == "group"]
        if owned_by_group:
            memories = [m for m in memories if owned_by_group in m.groups]

        title = f"{'Global' if is_global else 'Project'} Memories"
        if is_global and include_group_owned:
            title = "Global + Group Memories"
        if pinned:
            title += " (Pinned)"
        if group_owned:
            title += " (Group-scoped)"
        if owned_by_group:
            title += f" (Owned by '{owned_by_group}')"
        if category:
            title += f" [{category}]"

        display_memories_table(memories, title)

    try:
        scope_label = "global" if is_global else "project"
        ctx.obj["event_log"].log(
            "list",
            result_count=len(memories),
            metadata={"scope": scope_label},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# GET COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("memory_id")
@click.pass_context
def get(ctx: click.Context, memory_id: str) -> None:
    """Get a specific memory by ID."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        memory = store.get_by_id(memory_id)

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        try:
            store.record_access(memory_id, memory.scope)
        except Exception:
            pass

        display_memory(memory, verbose=True)

    try:
        ctx.obj["event_log"].log(
            "get",
            project_path=str(project_path),
            result_count=1,
            metadata={"memory_id": memory_id},
        )
    except Exception:
        pass


@main.command()
@click.argument("memory_id")
@click.pass_context
def show(ctx: click.Context, memory_id: str) -> None:
    """Show a specific memory by ID (alias for 'get')."""
    ctx.invoke(get, memory_id=memory_id)


# ─────────────────────────────────────────────────────────────
# PIN/UNPIN COMMANDS
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("memory_id")
@click.pass_context
def pin(ctx: click.Context, memory_id: str) -> None:
    """Pin a memory."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        # Try project first, then global
        memory = store.pin(memory_id, "project")
        if memory is None:
            memory = store.pin(memory_id, "global")

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Pinned memory: {memory_id}[/green]")


@main.command()
@click.argument("memory_id")
@click.pass_context
def unpin(ctx: click.Context, memory_id: str) -> None:
    """Unpin a memory."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        # Try project first, then global
        memory = store.unpin(memory_id, "project")
        if memory is None:
            memory = store.unpin(memory_id, "global")

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Unpinned memory: {memory_id}[/green]")


# ─────────────────────────────────────────────────────────────
# FORGET COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("memory_id", required=False)
@click.option("--search", "search_query", help="Delete memories matching this query")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def forget(
    ctx: click.Context,
    memory_id: str | None,
    search_query: str | None,
    confirm: bool,
) -> None:
    """Delete a memory or memories matching a query."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    if not memory_id and not search_query:
        console.print("[red]Provide a memory ID or --search query[/red]")
        sys.exit(1)

    with get_store(config, project_path) as store:
        if memory_id:
            # Delete single memory
            deleted = store.delete_by_id(memory_id)

            if deleted:
                # Also delete from vector store
                vector_store = get_vector_store(config, project_path)
                if vector_store:
                    vector_store.delete_by_id(memory_id)

                console.print(f"[green]Deleted memory: {memory_id}[/green]")
            else:
                console.print(f"[red]Memory not found: {memory_id}[/red]")
                sys.exit(1)

        elif search_query:
            # Preview what will be deleted
            matches = store.search_keyword(search_query, "project", 100)
            matches.extend(store.search_keyword(search_query, "global", 100))

            if not matches:
                console.print("[dim]No memories match the query.[/dim]")
                return

            console.print(
                f"[yellow]Found {len(matches)} memories matching '{search_query}':[/yellow]"
            )
            for m in matches[:10]:
                console.print(f"  {m.id}: {truncate_text(m.content, 50)}")
            if len(matches) > 10:
                console.print(f"  ... and {len(matches) - 10} more")

            if not confirm:
                if not click.confirm("Delete these memories?"):
                    console.print("[dim]Cancelled.[/dim]")
                    return

            # Delete matching
            count = store.delete_matching(search_query, "project")
            count += store.delete_matching(search_query, "global")

            console.print(f"[green]Deleted {count} memories.[/green]")

    try:
        deleted_count = 1 if memory_id else count if search_query else 0
        ctx.obj["event_log"].log(
            "forget",
            project_path=str(project_path),
            result_count=deleted_count,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# RESET COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option("--project", "reset_project", is_flag=True, help="Reset project memories")
@click.option("--global", "reset_global", is_flag=True, help="Reset global memories")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reset(
    ctx: click.Context,
    reset_project: bool,
    reset_global: bool,
    confirm: bool,
) -> None:
    """Delete all memories in a scope."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    if not reset_project and not reset_global:
        console.print("[red]Specify --project or --global[/red]")
        sys.exit(1)

    if not confirm:
        scope_name = "project" if reset_project else "global"
        if not click.confirm(f"Delete ALL {scope_name} memories? This cannot be undone."):
            console.print("[dim]Cancelled.[/dim]")
            return

    with get_store(config, project_path) as store:
        if reset_project:
            count = store.reset("project")
            console.print(f"[green]Deleted {count} project memories.[/green]")

            vector_store = get_vector_store(config, project_path)
            if vector_store:
                vector_store.reset("project")

        if reset_global:
            count = store.reset("global")
            console.print(f"[green]Deleted {count} global memories.[/green]")

            vector_store = get_vector_store(config, project_path)
            if vector_store:
                vector_store.reset("global")


# ─────────────────────────────────────────────────────────────
# SESSION COMMANDS
# ─────────────────────────────────────────────────────────────
@main.group()
def session() -> None:
    """Session management commands."""
    pass


@session.command("start")
@click.pass_context
def session_start(ctx: click.Context) -> None:
    """Start a new session."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.session import SessionManager

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)
        manager = SessionManager(config, store, vector_store, project_path)

        session = manager.start_session()
        console.print(f"[green]Started session: {session.id}[/green]")

    try:
        ctx.obj["event_log"].log("session", subcommand="start", project_path=str(project_path))
    except Exception:
        pass


@session.command("end")
@click.pass_context
def session_end(ctx: click.Context) -> None:
    """End the current session."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.session import SessionManager

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)
        manager = SessionManager(config, store, vector_store, project_path)

        last_session = manager.get_last_session()
        if last_session and last_session.ended_at is None:
            session = manager.end_session(last_session.id)
            if session:
                console.print(f"[green]Ended session: {session.id}[/green]")
        else:
            console.print("[dim]No active session to end.[/dim]")

    try:
        ctx.obj["event_log"].log("session", subcommand="end", project_path=str(project_path))
    except Exception:
        pass


@session.command("summarize")
@click.argument("content")
@click.pass_context
def session_summarize(ctx: click.Context, content: str) -> None:
    """Add a session summary."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.session import SessionManager

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)
        manager = SessionManager(config, store, vector_store, project_path)

        memory = manager.add_summary(content)
        console.print(f"[green]Added summary: {memory.id}[/green]")

    try:
        ctx.obj["event_log"].log(
            "session", subcommand="summarize", project_path=str(project_path)
        )
    except Exception:
        pass


@session.command("list")
@click.option("--limit", default=10, help="Maximum sessions to show")
@click.pass_context
def session_list(ctx: click.Context, limit: int) -> None:
    """List recent sessions."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.session import SessionManager

    with get_store(config, project_path) as store:
        manager = SessionManager(config, store, None, project_path)

        sessions = manager.list_sessions(limit)

        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return

        table = Table(title="Recent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Started", style="white")
        table.add_column("Ended", style="white")
        table.add_column("Summaries", style="green")

        for s in sessions:
            table.add_row(
                s.id,
                s.started_at.strftime("%Y-%m-%d %H:%M"),
                s.ended_at.strftime("%Y-%m-%d %H:%M") if s.ended_at else "Active",
                str(s.summary_count),
            )

        console.print(table)


@session.command("load")
@click.option("--last", is_flag=True, help="Load the last session")
@click.argument("session_id", required=False)
@click.pass_context
def session_load(ctx: click.Context, last: bool, session_id: str | None) -> None:
    """Load session summaries."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.session import SessionManager

    with get_store(config, project_path) as store:
        manager = SessionManager(config, store, None, project_path)

        if last:
            summaries = manager.load_last_session_context()
        elif session_id:
            summaries = manager.get_session_summaries(session_id)
        else:
            console.print("[red]Specify --last or a session ID[/red]")
            sys.exit(1)

        if not summaries:
            console.print("[dim]No summaries found for this session.[/dim]")
            return

        _record_access_for_memories(store, summaries)

        console.print(f"[bold]Session Summaries[/bold] ({len(summaries)} found)")
        for summary in summaries:
            console.print(f"\n[dim]{format_timestamp(summary.created_at)}[/dim]")
            console.print(f"  {summary.content}")

    try:
        ctx.obj["event_log"].log(
            "session",
            subcommand="load",
            project_path=str(project_path),
            result_count=len(summaries),
        )
    except Exception:
        pass


@session.command("analyze")
@click.argument("content", required=False)
@click.option("--last", is_flag=True, help="Analyze the last session")
@click.option("--session", "session_id", help="Analyze a specific session")
@click.option("--dry-run", is_flag=True, help="Show patterns without saving")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def session_analyze(
    ctx: click.Context,
    content: str | None,
    last: bool,
    session_id: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Extract error-fix patterns from session content.

    Analyzes session content using LLM and saves discovered
    error-fix patterns as memories.

    Examples:
        agent-memory session analyze "Hit TypeError in auth.ts, fixed with optional chaining"
        agent-memory session analyze --last --dry-run
        agent-memory session analyze --session sess_abc123 --json
    """
    config: Config = ctx.obj["config"]

    # Determine content source
    if content:
        analyze_content = content
        source_label = "text"
    elif last or session_id:
        project_path = get_current_project_path()
        from agent_memory.session import SessionManager

        with get_store(config, project_path) as store:
            manager = SessionManager(config, store, None, project_path)

            if last:
                summaries = manager.load_last_session_context()
                source_label = "last_session"
            else:
                summaries = manager.get_session_summaries(session_id)
                source_label = session_id or "unknown"

            if not summaries:
                console.print("[dim]No session summaries found to analyze.[/dim]")
                sys.exit(1)

            analyze_content = "\n".join(s.content for s in summaries)
    else:
        console.print("[red]Provide content text, --last, or --session[/red]")
        sys.exit(1)

    # Require LLM
    from agent_memory.llm import get_llm_provider

    llm = get_llm_provider(config)
    if llm is None:
        console.print("[red]LLM provider not available. Enable semantic search first.[/red]")
        console.print("  agent-memory config set semantic.enabled=true")
        sys.exit(1)

    # Extract patterns
    patterns = llm.extract_patterns(analyze_content)

    if not patterns:
        if as_json:
            console.print(json.dumps([]))
        else:
            console.print("[dim]No error-fix patterns found.[/dim]")
        return

    if dry_run:
        if as_json:
            console.print(json.dumps(patterns, indent=2))
        else:
            console.print(f"\n[bold]Found {len(patterns)} error-fix patterns (dry run)[/bold]\n")
            for i, p in enumerate(patterns, 1):
                console.print(f"  [{i}] Error: {p.get('error', 'N/A')}")
                console.print(f"      Cause: {p.get('cause', 'N/A')}")
                console.print(f"      Fix: {p.get('fix', 'N/A')}")
                console.print(f"      Context: {p.get('context', 'N/A')}")
                console.print()
        return

    # Save patterns as memories
    project_path = get_current_project_path()
    saved_ids: list[str] = []

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)

        for p in patterns:
            error = p.get("error", "Unknown error")
            cause = p.get("cause", "Unknown cause")
            fix = p.get("fix", "Unknown fix")
            ctx_field = p.get("context", "Unknown context")

            memory_content = f"Error→Fix: {error} in {ctx_field} — {fix}"

            metadata = {
                "error": error,
                "cause": cause,
                "fix": fix,
                "context": ctx_field,
                "analyzed_from": source_label,
            }

            memory = store.save(
                content=memory_content,
                category="factual",
                scope="project",
                source="auto_analysis",
                metadata=metadata,
            )

            if vector_store:
                try:
                    vector_store.add(
                        memory_id=memory.id,
                        content=memory_content,
                        category="factual",
                        scope="project",
                        groups=None,
                    )
                except Exception:
                    pass

            saved_ids.append(memory.id)

    if as_json:
        output = []
        for p, mid in zip(patterns, saved_ids):
            p["memory_id"] = mid
            output.append(p)
        console.print(json.dumps(output, indent=2))
    else:
        console.print(f"\n[green]Saved {len(saved_ids)} error-fix patterns:[/green]\n")
        for p, mid in zip(patterns, saved_ids):
            console.print(f"  [cyan]{mid}[/cyan]")
            console.print(f"    Error: {p.get('error', 'N/A')}")
            console.print(f"    Fix: {p.get('fix', 'N/A')}")
            console.print()

    try:
        ctx.obj["event_log"].log(
            "session",
            subcommand="analyze",
            result_count=len(patterns),
            metadata={"dry_run": dry_run},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# HOOK COMMANDS
# ─────────────────────────────────────────────────────────────
@main.group()
def hook() -> None:
    """Hook commands for agent integration."""
    pass


@hook.command("check-error")
@click.pass_context
def hook_check_error(ctx: click.Context) -> None:
    """Check tool output for errors and emit a nudge if found.

    Reads JSON from stdin (tool output from agent hooks).
    If errors detected and hooks.error_nudge is enabled, prints a reminder.
    """
    config: Config = ctx.obj["config"]

    # Check config toggle
    if not config.hooks.error_nudge:
        return

    # Read stdin
    try:
        stdin_text = sys.stdin.read()
        if not stdin_text.strip():
            return
    except Exception:
        return

    # Try to extract output text from JSON
    output_text = ""
    try:
        data = json.loads(stdin_text)
        # Support various JSON shapes from different hooks
        if isinstance(data, dict):
            output_text = (
                data.get("tool_response", "")
                or data.get("stdout", "")
                or data.get("output", "")
                or data.get("result", "")
                or str(data)
            )
        elif isinstance(data, str):
            output_text = data
        else:
            output_text = str(data)
    except (json.JSONDecodeError, ValueError):
        # Not JSON, treat raw text as output
        output_text = stdin_text

    if not output_text:
        return

    # Scan for error indicators
    error_keywords = [
        "Error", "ERROR", "error:",
        "FAILED", "FAIL",
        "fatal:", "Fatal:",
        "panic:",
        "Traceback",
        "Exception", "exception:",
        "ECONNREFUSED", "ENOENT", "EACCES", "EPERM",
        "segfault", "Segmentation fault",
        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "TypeError",
        "ValueError",
        "KeyError",
        "AttributeError",
        "RuntimeError",
        "FileNotFoundError",
        "PermissionError",
        "ConnectionError",
        "TimeoutError",
        "command not found",
        "No such file or directory",
    ]

    found = any(kw in output_text for kw in error_keywords)
    if not found:
        return

    # Emit nudge
    click.echo(
        "[agent-memory] Error detected in command output. "
        "If you resolved this error, consider saving the pattern:\n"
        '  agent-memory save --meta error="..." --meta root_cause="..." '
        '"Description of the fix"'
    )


# ─────────────────────────────────────────────────────────────
# GROUP COMMANDS
# ─────────────────────────────────────────────────────────────
@main.group()
def group() -> None:
    """Workspace group management for cross-project sharing."""
    pass


@group.command("create")
@click.argument("name")
@click.pass_context
def group_create(ctx: click.Context, name: str) -> None:
    """Create a new workspace group."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)

    try:
        grp = manager.create(name)
        console.print(f"[green]Created group: {name}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


@group.command("delete")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def group_delete(ctx: click.Context, name: str, confirm: bool) -> None:
    """Delete a workspace group."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)

    if not confirm:
        if not click.confirm(f"Delete group '{name}'? Memories will become project-private."):
            console.print("[dim]Cancelled.[/dim]")
            return

    if manager.delete(name):
        console.print(f"[green]Deleted group: {name}[/green]")
    else:
        console.print(f"[red]Group not found: {name}[/red]")
        sys.exit(1)


@group.command("join")
@click.argument("name")
@click.option("--project", type=click.Path(exists=True), help="Project path (default: current)")
@click.pass_context
def group_join(ctx: click.Context, name: str, project: str | None) -> None:
    """Add a project to a workspace group."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)
    project_path = Path(project) if project else get_current_project_path()

    try:
        grp = manager.add_project(name, project_path)
        console.print(f"[green]Added {project_path} to group '{name}'[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


@group.command("leave")
@click.argument("name")
@click.option("--project", type=click.Path(exists=True), help="Project path (default: current)")
@click.pass_context
def group_leave(ctx: click.Context, name: str, project: str | None) -> None:
    """Remove a project from a workspace group."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)
    project_path = Path(project) if project else get_current_project_path()

    try:
        grp = manager.remove_project(name, project_path)
        console.print(f"[green]Removed {project_path} from group '{name}'[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


@group.command("list")
@click.pass_context
def group_list(ctx: click.Context) -> None:
    """List all workspace groups."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)
    groups = manager.list_groups()

    if not groups:
        console.print("[dim]No workspace groups found.[/dim]")
        return

    console.print("\n[bold]Workspace Groups[/bold]\n")
    for grp in groups:
        console.print(f"[cyan]{grp.name}[/cyan]")
        console.print(f"  Created: {grp.created_at.strftime('%Y-%m-%d')}")
        console.print(f"  Projects: {len(grp.projects)}")
        for proj in grp.projects:
            console.print(f"    - {proj}")
        console.print("")


@group.command("show")
@click.argument("name")
@click.pass_context
def group_show(ctx: click.Context, name: str) -> None:
    """Show details of a workspace group."""
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    manager = GroupManager(config)
    grp = manager.get(name)

    if grp is None:
        console.print(f"[red]Group not found: {name}[/red]")
        sys.exit(1)

    console.print(f"\n[bold]{grp.name}[/bold]")
    console.print(f"  Created: {grp.created_at.strftime('%Y-%m-%d %H:%M')}")
    console.print(f"\n[cyan]Projects ({len(grp.projects)}):[/cyan]")
    for proj in grp.projects:
        console.print(f"  - {proj}")


# ─────────────────────────────────────────────────────────────
# GROUPS SHORTHAND COMMAND
# ─────────────────────────────────────────────────────────────
@main.command("groups")
@click.argument("name")
@click.option("--pinned", is_flag=True, help="Show only pinned memories")
@click.option("--limit", default=20, help="Maximum memories to show")
@click.pass_context
def groups_shorthand(ctx: click.Context, name: str, pinned: bool, limit: int) -> None:
    """Quick view of a group's info and memories.

    This is a shorthand for viewing a workspace group and its memories.
    Works from any directory.

    Examples:
        agent-memory groups backend-team
        agent-memory groups all --pinned
    """
    config: Config = ctx.obj["config"]

    from agent_memory.groups import GroupManager

    # First show group info (if it's a specific group, not "all")
    if name.lower() != "all":
        manager = GroupManager(config)
        grp = manager.get(name)

        if grp is None:
            console.print(f"[red]Group not found: {name}[/red]")
            sys.exit(1)

        console.print(f"\n[bold]Group: {grp.name}[/bold]")
        console.print(f"  Projects: {len(grp.projects)}")
        for proj in grp.projects:
            console.print(f"    - [dim]{proj}[/dim]")

    # Then show group memories
    with get_store(config) as store:
        memories = store.list_by_group(
            group_name=name,
            pinned_only=pinned,
            limit=limit,
        )

        title = "\nGroup Memories"
        if name.lower() != "all":
            title = f"\nMemories in '{name}'"
        else:
            title = "\nAll Group Memories"
        if pinned:
            title += " (Pinned only)"

        if memories:
            console.print(f"[bold]{title}[/bold] ({len(memories)} found)")
            display_memories_table(memories, "")
        else:
            console.print(f"[dim]{title}: No memories found.[/dim]")


# ─────────────────────────────────────────────────────────────
# GROUP MANAGEMENT COMMANDS (for group-scoped memories)
# ─────────────────────────────────────────────────────────────
@main.command("add-groups")
@click.argument("memory_id")
@click.argument("groups", nargs=-1, required=True)
@click.pass_context
def add_groups(ctx: click.Context, memory_id: str, groups: tuple[str, ...]) -> None:
    """Add owner groups to a group-scoped memory."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        try:
            memory = store.add_groups(memory_id, list(groups))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Added groups to {memory_id}: {', '.join(groups)}[/green]")
        console.print(f"  Owner groups: {', '.join(memory.groups)}")


@main.command("remove-groups")
@click.argument("memory_id")
@click.argument("groups", nargs=-1, required=True)
@click.pass_context
def remove_groups(ctx: click.Context, memory_id: str, groups: tuple[str, ...]) -> None:
    """Remove owner groups from a group-scoped memory."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        try:
            memory = store.remove_groups(memory_id, list(groups))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Removed groups from {memory_id}: {', '.join(groups)}[/green]")
        console.print(f"  Owner groups: {', '.join(memory.groups) or 'none'}")


@main.command("set-groups")
@click.argument("memory_id")
@click.argument("groups", nargs=-1, required=True)
@click.pass_context
def set_groups_cmd(ctx: click.Context, memory_id: str, groups: tuple[str, ...]) -> None:
    """Set owner groups for a group-scoped memory (replaces all)."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        try:
            memory = store.set_groups(memory_id, list(groups))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Set groups for {memory_id}: {', '.join(groups)}[/green]")
        console.print(f"  Owner groups: {', '.join(memory.groups)}")


@main.command("set-scope")
@click.argument("memory_id")
@click.argument("scope", type=click.Choice(["project", "group", "global"]))
@click.option("--group", "group_names", multiple=True, help="Groups (required for group scope)")
@click.option(
    "--to-project", type=click.Path(exists=True), help="Target project (for project scope)"
)
@click.pass_context
def set_scope_cmd(
    ctx: click.Context,
    memory_id: str,
    scope: str,
    group_names: tuple[str, ...],
    to_project: str | None,
) -> None:
    """Change the scope of a memory."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    if scope == "group" and not group_names:
        console.print("[red]Group scope requires --group=<name>[/red]")
        sys.exit(1)

    with get_store(config, project_path) as store:
        try:
            groups_list = list(group_names) if group_names else None
            memory = store.set_scope(memory_id, scope, groups_list)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if memory is None:
            console.print(f"[red]Memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Changed scope of {memory_id} to: {scope}[/green]")
        if scope == "group":
            console.print(f"  Owner groups: {', '.join(memory.groups)}")


# ─────────────────────────────────────────────────────────────
# PROMOTE/UNPROMOTE COMMANDS
# ─────────────────────────────────────────────────────────────
@main.command()
@click.argument("memory_id")
@click.option("--from-project", type=click.Path(exists=True), help="Source project path")
@click.option(
    "--to-group",
    "to_group",
    multiple=True,
    help="Promote to group scope with these owner groups (can specify multiple)",
)
@click.pass_context
def promote(
    ctx: click.Context,
    memory_id: str,
    from_project: str | None,
    to_group: tuple[str, ...],
) -> None:
    """Promote a project memory to global or group scope.

    By default promotes to global scope (visible everywhere).
    Use --to-group to promote to group scope instead.
    """
    config: Config = ctx.obj["config"]
    project_path = Path(from_project) if from_project else get_current_project_path()

    with get_store(config, project_path) as store:
        groups = list(to_group) if to_group else None
        memory = store.promote(
            memory_id,
            from_project=Path(from_project) if from_project else None,
            to_group=groups,
        )

        if memory is None:
            console.print(f"[red]Memory not found in project: {memory_id}[/red]")
            sys.exit(1)

        if groups:
            console.print(f"[green]Promoted to group scope: {memory.id}[/green]")
            console.print(f"  Owner groups: {', '.join(memory.groups)}")
        else:
            console.print(f"[green]Promoted to global scope: {memory.id}[/green]")
        console.print(f"  Content: {truncate_text(memory.content, 60)}")


@main.command()
@click.argument("memory_id")
@click.option(
    "--to-project", type=click.Path(exists=True), required=True, help="Target project path"
)
@click.pass_context
def unpromote(ctx: click.Context, memory_id: str, to_project: str) -> None:
    """Move a global or group memory to a specific project."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        try:
            memory = store.unpromote(memory_id, Path(to_project))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if memory is None:
            console.print(f"[red]Global/group memory not found: {memory_id}[/red]")
            sys.exit(1)

        console.print(f"[green]Moved to project: {memory.id}[/green]")
        console.print(f"  Project: {to_project}")
        console.print(f"  Content: {truncate_text(memory.content, 60)}")


# ─────────────────────────────────────────────────────────────
# CONFIG COMMANDS
# ─────────────────────────────────────────────────────────────
@main.group()
def config() -> None:
    """Configuration management."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    cfg: Config = ctx.obj["config"]

    console.print("\n[bold]Agent Memory Configuration[/bold]")
    console.print(f"  Base path: {cfg.base_path}")
    console.print(f"\n[cyan]Semantic Search[/cyan]")
    console.print(f"  Enabled: {cfg.semantic.enabled}")
    console.print(f"  Provider: {cfg.semantic.provider}")
    console.print(f"  Threshold: {cfg.semantic.threshold}")

    console.print(f"\n[cyan]Autosave[/cyan]")
    console.print(f"  Enabled: {cfg.autosave.enabled}")
    console.print(f"  On task complete: {cfg.autosave.on_task_complete}")
    console.print(f"  Session summary: {cfg.autosave.session_summary}")
    console.print(f"  Summary interval: {cfg.autosave.summary_interval_messages} messages")

    console.print(f"\n[cyan]Startup[/cyan]")
    console.print(f"  Auto-load pinned: {cfg.startup.auto_load_pinned}")
    console.print(f"  Ask load previous: {cfg.startup.ask_load_previous_session}")

    console.print(f"\n[cyan]Expiration[/cyan]")
    console.print(f"  Enabled: {cfg.expiration.enabled}")
    console.print(f"  Default days: {cfg.expiration.default_days}")

    console.print(f"\n[cyan]Relevance[/cyan]")
    console.print(f"  Search limit: {cfg.relevance.search_limit}")
    console.print(f"  Include global: {cfg.relevance.include_global}")


@config.command("set")
@click.argument("key_value")
@click.pass_context
def config_set(ctx: click.Context, key_value: str) -> None:
    """Set a configuration value (e.g., semantic.enabled=true)."""
    cfg: Config = ctx.obj["config"]

    if "=" not in key_value:
        console.print("[red]Format: key=value (e.g., semantic.enabled=true)[/red]")
        sys.exit(1)

    key, value = key_value.split("=", 1)

    try:
        new_config = update_config(cfg, key, value)
        console.print(f"[green]Set {key} = {value}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to update config: {e}[/red]")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
# EXPORT COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option(
    "--format", "output_format", type=click.Choice(["markdown", "json"]), default="markdown"
)
@click.option("--output", "-o", type=click.Path(), help="Output file (stdout if not specified)")
@click.option(
    "--all-projects",
    is_flag=True,
    help="Export from all projects (user visibility, not for agents)",
)
@click.pass_context
def export(
    ctx: click.Context,
    output_format: str,
    output: str | None,
    all_projects: bool,
) -> None:
    """Export memories to file."""
    config: Config = ctx.obj["config"]
    from agent_memory.utils import get_timestamp

    # Cross-project export
    if all_projects:
        with get_store(config) as store:
            results = store.list_all_projects(
                limit_per_project=1000,
                include_global=True,
            )

            if output_format == "json":
                data = {}
                for project_path, memories in results:
                    key = "global" if project_path is None else str(project_path)
                    data[key] = [m.to_dict() for m in memories]
                content = json.dumps(data, indent=2)
            else:
                lines = ["# Agent Memory Export (All Projects)\n"]
                lines.append(f"Exported: {format_timestamp(get_timestamp())}\n")

                for project_path, memories in results:
                    if not memories:
                        continue
                    project_label = "Global" if project_path is None else str(project_path)
                    lines.append(f"\n## {project_label}\n")
                    for m in memories:
                        pin = " [PINNED]" if m.pinned else ""
                        lines.append(f"### {m.id}{pin}\n")
                        lines.append(f"**Category:** {m.category}\n")
                        lines.append(f"**Created:** {format_timestamp(m.created_at)}\n")
                        lines.append(f"\n{m.content}\n")

                content = "\n".join(lines)

            if output:
                Path(output).write_text(content)
                console.print(f"[green]Exported to {output}[/green]")
            else:
                console.print(content)
        return

    # Standard export (current project + global)
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        project_memories = store.list("project", limit=1000)
        global_memories = store.list("global", limit=1000)

        if output_format == "json":
            data = {
                "project": [m.to_dict() for m in project_memories],
                "global": [m.to_dict() for m in global_memories],
            }
            content = json.dumps(data, indent=2)
        else:
            lines = ["# Agent Memory Export\n"]
            lines.append(f"Project: {project_path}\n")

            lines.append(f"Exported: {format_timestamp(get_timestamp())}\n")

            if project_memories:
                lines.append("\n## Project Memories\n")
                for m in project_memories:
                    pin = " [PINNED]" if m.pinned else ""
                    lines.append(f"### {m.id}{pin}\n")
                    lines.append(f"**Category:** {m.category}\n")
                    lines.append(f"**Created:** {format_timestamp(m.created_at)}\n")
                    lines.append(f"\n{m.content}\n")

            if global_memories:
                lines.append("\n## Global Memories\n")
                for m in global_memories:
                    pin = " [PINNED]" if m.pinned else ""
                    lines.append(f"### {m.id}{pin}\n")
                    lines.append(f"**Category:** {m.category}\n")
                    lines.append(f"**Created:** {format_timestamp(m.created_at)}\n")
                    lines.append(f"\n{m.content}\n")

            content = "\n".join(lines)

        if output:
            Path(output).write_text(content)
            console.print(f"[green]Exported to {output}[/green]")
        else:
            console.print(content)


# ─────────────────────────────────────────────────────────────
# CLEANUP COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def cleanup(ctx: click.Context) -> None:
    """Remove expired memories."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        project_count = store.cleanup_expired("project")
        global_count = store.cleanup_expired("global")

        total = project_count + global_count
        if total > 0:
            console.print(f"[green]Removed {total} expired memories.[/green]")
        else:
            console.print("[dim]No expired memories found.[/dim]")


# ─────────────────────────────────────────────────────────────
# INIT COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize memory for the current project."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.config import get_project_path

    project_storage = get_project_path(config, project_path)

    console.print(f"[green]Initialized memory for project: {project_path}[/green]")
    console.print(f"  Storage: {project_storage}")


# ─────────────────────────────────────────────────────────────
# STARTUP COMMAND (for agent integration)
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--groups",
    help="Comma-separated list of groups to include, or 'all' for all groups",
)
@click.option(
    "--exclude-groups",
    help="Comma-separated list of groups to exclude",
)
@click.pass_context
def startup(
    ctx: click.Context,
    as_json: bool,
    groups: str | None,
    exclude_groups: str | None,
) -> None:
    """Get startup context for agent session.

    By default, only project and global memories are loaded.
    Use --groups to opt-in to group-shared memories.

    Examples:
        agent-memory startup --json
        agent-memory startup --json --groups=backend-team
        agent-memory startup --json --groups=all
        agent-memory startup --json --groups=all --exclude-groups=legacy
    """
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from agent_memory.relevance import RelevanceEngine

    # Parse comma-separated groups
    groups_list = [g.strip() for g in groups.split(",")] if groups else None
    exclude_list = [g.strip() for g in exclude_groups.split(",")] if exclude_groups else None

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)
        engine = RelevanceEngine(config, store, vector_store)

        context = engine.get_startup_context(
            project_path,
            groups=groups_list,
            exclude_groups=exclude_list,
        )

        _record_access_for_memories(
            store, context.pinned_memories + context.group_memories
        )

        if as_json:
            data = {
                "pinned_memories": [m.to_dict() for m in context.pinned_memories],
                "group_memories": [m.to_dict() for m in context.group_memories],
                "has_previous_session": context.has_previous_session,
                "previous_session_id": context.previous_session_id,
                "previous_session_summaries": [
                    m.to_dict() for m in context.previous_session_summaries
                ],
            }
            console.print(json.dumps(data, indent=2))
        else:
            if context.pinned_memories:
                console.print(f"\n[bold]Pinned Memories[/bold] ({len(context.pinned_memories)})")
                for m in context.pinned_memories:
                    console.print(f"  [red]*[/red] {truncate_text(m.content, 70)}")

            if context.group_memories:
                console.print(f"\n[bold]Group Memories[/bold] ({len(context.group_memories)})")
                for m in context.group_memories:
                    # Show owner groups
                    groups_str = ", ".join(m.groups) if m.groups else "none"
                    console.print(f"  [blue]*[/blue] {truncate_text(m.content, 60)}")
                    console.print(f"      [dim]groups: {groups_str}[/dim]")

            if context.has_previous_session:
                console.print(f"\n[bold]Previous Session[/bold]: {context.previous_session_id}")
                if context.previous_session_summaries:
                    console.print(
                        "  Summaries available. Load with: agent-memory session load --last"
                    )

    try:
        ctx.obj["event_log"].log(
            "startup",
            project_path=str(project_path),
            result_count=len(context.pinned_memories) + len(context.group_memories),
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# STATS COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option(
    "--scope",
    type=click.Choice(["project", "group", "global"]),
    help="Filter by scope",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def stats(ctx: click.Context, scope: str | None, as_json: bool) -> None:
    """Show memory statistics and recommendations."""
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    from datetime import timedelta

    from agent_memory.utils import get_timestamp

    now = get_timestamp()

    with get_store(config, project_path) as store:
        # Gather all memories
        all_memories: list[Memory] = []
        scopes_to_check = [scope] if scope else ["project", "group", "global"]

        for check_scope in scopes_to_check:
            try:
                memories = store.list(
                    scope=check_scope,
                    pinned_only=False,
                    limit=100000,
                )
                all_memories.extend(memories)
            except Exception:
                continue

        if not all_memories:
            if as_json:
                console.print(json.dumps({"error": "No memories found"}))
            else:
                console.print("[dim]No memories found.[/dim]")
            return

        # Calculate statistics
        total_count = len(all_memories)
        pinned_count = sum(1 for m in all_memories if m.pinned)

        # Estimate size (rough: content length in bytes)
        size_bytes = sum(len(m.content.encode("utf-8")) for m in all_memories)

        # By scope
        by_scope: dict[str, dict[str, int]] = {}
        for m in all_memories:
            if m.scope not in by_scope:
                by_scope[m.scope] = {"count": 0, "pinned": 0}
            by_scope[m.scope]["count"] += 1
            if m.pinned:
                by_scope[m.scope]["pinned"] += 1

        # By category
        by_category: dict[str, int] = {}
        for m in all_memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1

        # By age
        by_age = {"lt_7d": 0, "7d_30d": 0, "30d_90d": 0, "gt_90d": 0}
        for m in all_memories:
            age = now - m.created_at
            if age < timedelta(days=7):
                by_age["lt_7d"] += 1
            elif age < timedelta(days=30):
                by_age["7d_30d"] += 1
            elif age < timedelta(days=90):
                by_age["30d_90d"] += 1
            else:
                by_age["gt_90d"] += 1

        # Access patterns
        access_patterns = {"never_accessed": 0, "accessed_1_5": 0, "accessed_gt_5": 0}
        for m in all_memories:
            if m.access_count == 0:
                access_patterns["never_accessed"] += 1
            elif m.access_count <= 5:
                access_patterns["accessed_1_5"] += 1
            else:
                access_patterns["accessed_gt_5"] += 1

        # Generate recommendations
        recommendations: list[dict[str, Any]] = []

        # Recommend pruning old, never-accessed memories
        old_never_accessed = sum(
            1
            for m in all_memories
            if m.access_count == 0 and (now - m.created_at) >= timedelta(days=90) and not m.pinned
        )
        if old_never_accessed > 0:
            recommendations.append(
                {
                    "type": "prune",
                    "count": old_never_accessed,
                    "reason": "Memories older than 90 days that have never been accessed",
                }
            )

        # Recommend compaction for session_summary category
        session_summaries = sum(1 for m in all_memories if m.category == "session_summary")
        if session_summaries > 10:
            recommendations.append(
                {
                    "type": "compact",
                    "count": session_summaries,
                    "reason": "Session summaries could be consolidated into fewer entries",
                }
            )

        # Build result
        result = {
            "totals": {
                "count": total_count,
                "pinned": pinned_count,
                "size_bytes": size_bytes,
            },
            "by_scope": by_scope,
            "by_category": by_category,
            "by_age": by_age,
            "access_patterns": access_patterns,
            "recommendations": recommendations,
        }

        if as_json:
            console.print(json.dumps(result, indent=2))
        else:
            console.print("\n[bold]Memory Statistics[/bold]\n")

            console.print("[cyan]Totals[/cyan]")
            console.print(f"  Total memories: {total_count}")
            console.print(f"  Pinned: {pinned_count}")
            console.print(f"  Estimated size: {size_bytes:,} bytes")

            console.print("\n[cyan]By Scope[/cyan]")
            for s, counts in by_scope.items():
                console.print(f"  {s}: {counts['count']} ({counts['pinned']} pinned)")

            console.print("\n[cyan]By Category[/cyan]")
            for cat, count in sorted(by_category.items()):
                console.print(f"  {cat}: {count}")

            console.print("\n[cyan]By Age[/cyan]")
            console.print(f"  < 7 days: {by_age['lt_7d']}")
            console.print(f"  7-30 days: {by_age['7d_30d']}")
            console.print(f"  30-90 days: {by_age['30d_90d']}")
            console.print(f"  > 90 days: {by_age['gt_90d']}")

            console.print("\n[cyan]Access Patterns[/cyan]")
            console.print(f"  Never accessed: {access_patterns['never_accessed']}")
            console.print(f"  Accessed 1-5 times: {access_patterns['accessed_1_5']}")
            console.print(f"  Accessed >5 times: {access_patterns['accessed_gt_5']}")

            if recommendations:
                console.print("\n[yellow]Recommendations[/yellow]")
                for rec in recommendations:
                    console.print(f"  [{rec['type']}] {rec['count']} memories: {rec['reason']}")


# ─────────────────────────────────────────────────────────────
# PRUNE COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option("--older-than", help="Prune memories older than (e.g., 90d)")
@click.option("--never-accessed", is_flag=True, help="Prune memories never accessed")
@click.option(
    "--category",
    type=click.Choice(["factual", "decision", "task_history", "session_summary"]),
    help="Filter by category",
)
@click.option(
    "--scope",
    type=click.Choice(["project", "group", "global"]),
    help="Filter by scope",
)
@click.option("--include-pinned", is_flag=True, help="Include pinned memories (dangerous)")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def prune(
    ctx: click.Context,
    older_than: str | None,
    never_accessed: bool,
    category: str | None,
    scope: str | None,
    include_pinned: bool,
    dry_run: bool,
    confirm: bool,
) -> None:
    """Remove old or unused memories.

    Examples:
        agent-memory prune --older-than=90d --dry-run
        agent-memory prune --never-accessed --older-than=30d
        agent-memory prune --category=session_summary --older-than=60d
    """
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    if not older_than and not never_accessed:
        console.print("[red]Specify at least one of: --older-than, --never-accessed[/red]")
        sys.exit(1)

    # Parse older_than
    older_than_days: int | None = None
    if older_than:
        if older_than.endswith("d"):
            try:
                older_than_days = int(older_than[:-1])
            except ValueError:
                console.print(f"[red]Invalid --older-than format: {older_than}[/red]")
                sys.exit(1)
        else:
            console.print("[red]--older-than must end with 'd' (e.g., 90d)[/red]")
            sys.exit(1)

    from agent_memory.pruning import PruningEngine

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)
        engine = PruningEngine(config, store, vector_store)

        # Find candidates
        candidates = engine.find_candidates(
            scope=scope,
            older_than_days=older_than_days,
            never_accessed=never_accessed,
            category=category,
            exclude_pinned=not include_pinned,
        )

        if not candidates:
            console.print("[dim]No memories match the prune criteria.[/dim]")
            return

        # Show summary
        summary = engine.get_prune_summary(candidates)

        console.print(f"\n[bold]Prune Candidates[/bold]: {summary['total']} memories\n")

        console.print("[cyan]By Scope[/cyan]")
        for s, count in summary["by_scope"].items():
            console.print(f"  {s}: {count}")

        console.print("\n[cyan]By Category[/cyan]")
        for cat, count in summary["by_category"].items():
            console.print(f"  {cat}: {count}")

        console.print("\n[cyan]By Reason[/cyan]")
        for reason, count in summary["by_reason"].items():
            console.print(f"  {reason}: {count}")

        # Show preview
        console.print("\n[cyan]Preview (first 10)[/cyan]")
        for i, candidate in enumerate(candidates[:10]):
            m = candidate.memory
            reasons = ", ".join(candidate.reasons)
            console.print(f"  {m.id}: {truncate_text(m.content, 40)} [{reasons}]")
        if len(candidates) > 10:
            console.print(f"  ... and {len(candidates) - 10} more")

        if dry_run:
            console.print("\n[yellow]Dry run - no memories deleted.[/yellow]")
            return

        # Confirm
        if not confirm:
            if not click.confirm(f"\nDelete {len(candidates)} memories?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        # Execute prune
        deleted = engine.prune(candidates)
        console.print(f"\n[green]Deleted {deleted} memories.[/green]")

    try:
        ctx.obj["event_log"].log(
            "prune",
            project_path=str(project_path),
            result_count=deleted if not dry_run else len(candidates),
            metadata={"dry_run": dry_run},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# COMPACT COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option(
    "--category",
    type=click.Choice(["factual", "decision", "task_history", "session_summary"]),
    help="Filter by category",
)
@click.option("--older-than", help="Only memories older than (e.g., 30d)")
@click.option(
    "--scope",
    type=click.Choice(["project", "group", "global"]),
    help="Filter source memories by scope",
)
@click.option("--similarity", type=float, default=0.8, help="Similarity threshold (0.0-1.0)")
@click.option("--min-cluster", type=int, default=3, help="Minimum memories per cluster")
@click.option(
    "--target-scope",
    type=click.Choice(["project", "group", "global"]),
    required=True,
    help="Scope for compacted memories",
)
@click.option("--target-groups", help="Groups for compacted memories (if target-scope=group)")
@click.option("--dry-run", is_flag=True, help="Show clusters without compacting")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def compact(
    ctx: click.Context,
    category: str | None,
    older_than: str | None,
    scope: str | None,
    similarity: float,
    min_cluster: int,
    target_scope: str,
    target_groups: str | None,
    dry_run: bool,
    confirm: bool,
) -> None:
    """Compact similar memories into summaries using LLM.

    Uses DBSCAN clustering to find similar memories and summarizes them.
    The original memories are deleted and replaced with a single summary.

    Examples:
        agent-memory compact --category=session_summary --target-scope=project --dry-run
        agent-memory compact --older-than=30d --similarity=0.85 --target-scope=global
    """
    config: Config = ctx.obj["config"]
    project_path = get_current_project_path()

    # Validate target-groups
    if target_scope == "group" and not target_groups:
        console.print("[red]--target-groups required when --target-scope=group[/red]")
        sys.exit(1)

    groups_list = [g.strip() for g in target_groups.split(",")] if target_groups else None

    # Parse older_than
    older_than_days: int | None = None
    if older_than:
        if older_than.endswith("d"):
            try:
                older_than_days = int(older_than[:-1])
            except ValueError:
                console.print(f"[red]Invalid --older-than format: {older_than}[/red]")
                sys.exit(1)
        else:
            console.print("[red]--older-than must end with 'd' (e.g., 30d)[/red]")
            sys.exit(1)

    from agent_memory.compaction import CompactionEngine

    with get_store(config, project_path) as store:
        vector_store = get_vector_store(config, project_path)

        if not vector_store:
            console.print("[red]Compaction requires semantic search to be enabled.[/red]")
            console.print("Enable it with: agent-memory config set semantic.enabled=true")
            sys.exit(1)

        engine = CompactionEngine(config, store, vector_store)

        # Find clusters
        try:
            clusters = engine.find_clusters(
                scope=scope,
                category=category,
                older_than_days=older_than_days,
                similarity_threshold=similarity,
                min_cluster_size=min_cluster,
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        if not clusters:
            console.print("[dim]No clusters found matching criteria.[/dim]")
            return

        # Show cluster summary
        summary = engine.get_cluster_summary(clusters)

        console.print(f"\n[bold]Found {summary['cluster_count']} clusters[/bold]")
        console.print(f"Total memories: {summary['total_memories']}")
        console.print(f"Avg cluster size: {summary['avg_cluster_size']}")

        console.print("\n[cyan]Cluster Details[/cyan]")
        for cluster_info in summary["clusters"]:
            console.print(
                f"\n  Cluster {cluster_info['index'] + 1} ({cluster_info['size']} memories):"
            )
            for preview in cluster_info["previews"][:3]:
                console.print(f"    - {preview['id']}: {preview['content']}")
            if len(cluster_info["previews"]) > 3:
                console.print(f"    ... and {len(cluster_info['previews']) - 3} more")

        if dry_run:
            console.print("\n[yellow]Dry run - no compaction performed.[/yellow]")
            return

        # Confirm
        if not confirm:
            if not click.confirm(
                f"\nCompact {summary['total_memories']} memories into "
                f"{summary['cluster_count']} summaries?"
            ):
                console.print("[dim]Cancelled.[/dim]")
                return

        # Execute compaction
        console.print("\n[cyan]Compacting clusters...[/cyan]")
        compacted_count = 0

        for i, cluster in enumerate(clusters):
            console.print(f"  Processing cluster {i + 1}/{len(clusters)}...")

            try:
                # Generate summary (may raise on LLM error)
                summary_text = engine.generate_summary(cluster)

                # Compact cluster
                new_memory = engine.compact_cluster(
                    cluster=cluster,
                    summary=summary_text,
                    target_scope=target_scope,
                    target_groups=groups_list,
                )

                console.print(f"    Created: {new_memory.id} (from {cluster.size} memories)")
                compacted_count += cluster.size

            except Exception as e:
                console.print(f"\n[red]LLM error during compaction: {e}[/red]")
                console.print(
                    "[red]Aborting compaction. Some clusters may have been processed.[/red]"
                )
                sys.exit(1)

        console.print(
            f"\n[green]Compacted {compacted_count} memories into {len(clusters)} summaries.[/green]"
        )

    try:
        ctx.obj["event_log"].log(
            "compact",
            project_path=str(project_path),
            result_count=compacted_count if not dry_run else summary["total_memories"],
            metadata={"dry_run": dry_run},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# USAGE COMMAND
# ─────────────────────────────────────────────────────────────
@main.command()
@click.option("--since", default="30d", help="Time period (e.g., 7d, 30d, 90d)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def usage(ctx: click.Context, since: str, as_json: bool) -> None:
    """Show usage tracking and effectiveness analytics.

    Examples:
        agent-memory usage
        agent-memory usage --since 7d
        agent-memory usage --since 90d
        agent-memory usage --json
    """
    config: Config = ctx.obj["config"]
    event_log = ctx.obj["event_log"]

    # Parse --since
    if since.endswith("d"):
        try:
            since_days = int(since[:-1])
        except ValueError:
            console.print(f"[red]Invalid --since format: {since}[/red]")
            sys.exit(1)
    else:
        console.print("[red]--since must end with 'd' (e.g., 30d)[/red]")
        sys.exit(1)

    from datetime import timedelta

    from agent_memory.utils import get_timestamp

    now = get_timestamp()

    # 1. Command frequency
    command_counts = event_log.get_command_counts(since_days)

    # 2. Search effectiveness
    search_stats = event_log.get_search_stats(since_days)

    # 3. Session compliance
    session_stats = event_log.get_session_stats(since_days)

    # 4. Memory effectiveness (from memory stores)
    project_path = get_current_project_path()
    total_memories = 0
    never_accessed = 0
    most_accessed: list[Memory] = []
    pin_candidates: list[Memory] = []
    old_never_accessed = 0

    with get_store(config, project_path) as store:
        for check_scope in ["project", "global"]:
            try:
                memories = store.list(scope=check_scope, limit=100000)
                total_memories += len(memories)
                never_accessed += sum(1 for m in memories if m.access_count == 0)
                old_never_accessed += sum(
                    1
                    for m in memories
                    if m.access_count == 0
                    and (now - m.created_at) >= timedelta(days=90)
                    and not m.pinned
                )
            except Exception:
                continue

        # Get most accessed across scopes
        for check_scope in ["project", "global"]:
            try:
                most_accessed.extend(store.get_most_accessed(check_scope, 5))
            except Exception:
                continue
        most_accessed.sort(key=lambda m: m.access_count, reverse=True)
        most_accessed = most_accessed[:5]

        # Get pin candidates
        for check_scope in ["project", "global"]:
            try:
                pin_candidates.extend(store.get_pin_candidates(check_scope, 5, 5))
            except Exception:
                continue
        pin_candidates.sort(key=lambda m: m.access_count, reverse=True)
        pin_candidates = pin_candidates[:5]

    # 5. Build recommendations
    recommendations: list[dict[str, str]] = []

    for m in pin_candidates:
        recommendations.append({
            "action": "pin",
            "memory_id": m.id,
            "reason": f"Accessed {m.access_count} times but not pinned",
        })

    if old_never_accessed > 0:
        recommendations.append({
            "action": "prune",
            "reason": f"{old_never_accessed} memories are >90d old and never accessed",
        })

    if search_stats["total_searches"] > 0 and search_stats["zero_result_rate"] > 0.15:
        pct = int(search_stats["zero_result_rate"] * 100)
        recommendations.append({
            "action": "search",
            "reason": f"{pct}% of searches return 0 results",
        })

    if as_json:
        result = {
            "period_days": since_days,
            "command_frequency": command_counts,
            "search_effectiveness": search_stats,
            "session_compliance": session_stats,
            "memory_effectiveness": {
                "total_memories": total_memories,
                "never_accessed": never_accessed,
                "never_accessed_pct": round(never_accessed / max(total_memories, 1) * 100, 1),
                "most_accessed": [
                    {"id": m.id, "access_count": m.access_count, "content": truncate_text(m.content, 60)}
                    for m in most_accessed
                ],
            },
            "recommendations": recommendations,
        }
        console.print(json.dumps(result, indent=2))
    else:
        console.print(f"\n[bold]Usage Report (last {since_days}d)[/bold]\n")

        # Command frequency
        console.print("[cyan]Command Frequency[/cyan]")
        if command_counts:
            for cmd, count in command_counts.items():
                console.print(f"  {cmd + ':':<25} {count}")
        else:
            console.print("  [dim]No commands recorded yet.[/dim]")

        # Search effectiveness
        console.print("\n[cyan]Search Effectiveness[/cyan]")
        if search_stats["total_searches"] > 0:
            console.print(f"  Total searches:      {search_stats['total_searches']}")
            console.print(f"  Avg results/search:  {search_stats['avg_result_count']}")
            zero_pct = int(search_stats["zero_result_rate"] * 100)
            console.print(
                f"  Zero-result rate:    {zero_pct}% ({search_stats['zero_result_count']}/{search_stats['total_searches']})"
            )
        else:
            console.print("  [dim]No searches recorded yet.[/dim]")

        # Memory effectiveness
        console.print("\n[cyan]Memory Effectiveness[/cyan]")
        console.print(f"  Total memories:      {total_memories}")
        if total_memories > 0:
            never_pct = round(never_accessed / total_memories * 100)
            console.print(f"  Never accessed:      {never_accessed} ({never_pct}%)")
        if most_accessed:
            console.print("  Most-used:")
            for m in most_accessed:
                console.print(f"    {m.id} ({m.access_count}x): \"{truncate_text(m.content, 50)}\"")

        # Agent compliance
        console.print("\n[cyan]Agent Compliance[/cyan]")
        console.print(f"  Startup calls:             {session_stats['startup_count']}")
        if session_stats["startup_count"] > 0 or session_stats["session_starts"] > 0:
            total_sessions = max(session_stats["startup_count"], session_stats["session_starts"])
            summarize_pct = int(session_stats["summarize_rate"] * 100)
            console.print(
                f"  Sessions with summaries:   {summarize_pct}% ({session_stats['summarize_count']}/{total_sessions})"
            )
        else:
            console.print("  [dim]No sessions recorded yet.[/dim]")

        # Recommendations
        if recommendations:
            console.print("\n[yellow]Recommendations[/yellow]")
            for rec in recommendations:
                action = rec["action"]
                reason = rec["reason"]
                memory_id = rec.get("memory_id", "")
                if memory_id:
                    console.print(f"  [{action}]  {memory_id}: {reason}")
                else:
                    console.print(f"  [{action}]  {reason}")


if __name__ == "__main__":
    main()
