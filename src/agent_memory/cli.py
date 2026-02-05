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
@click.pass_context
def save(
    ctx: click.Context,
    content: str,
    is_global: bool,
    group_names: str | None,
    pin: bool,
    category: str | None,
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

    project_path = get_current_project_path()

    with get_store(config, project_path) as store:
        memory = store.save(
            content=content,
            category=category,
            scope=scope,
            pinned=pin,
            source="user_explicit",
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
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    limit: int,
    threshold: float | None,
    include_global: bool,
    category: str | None,
    all_projects: bool,
) -> None:
    """Search memories by query."""
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
        keyword_results = store.search_keyword(query, "project", limit)

        if include_global:
            keyword_results.extend(store.search_keyword(query, "global", limit))

        if category:
            keyword_results = [m for m in keyword_results if m.category == category]

        keyword_results = keyword_results[:limit]

        if keyword_results:
            results_found = True
            console.print(f"\n[bold]Keyword Search Results[/bold] ({len(keyword_results)} found)")
            display_memories_table(keyword_results)

    if not results_found:
        console.print("[dim]No memories found matching your query.[/dim]")


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
@click.option("--group-owned", is_flag=True, help="Show only group-scoped memories")
@click.option("--owned-by", "owned_by_group", help="Show memories owned by a specific group")
@click.option(
    "--include-group-owned",
    is_flag=True,
    help="With --global, also include group-scoped memories",
)
@click.pass_context
def list_memories(
    ctx: click.Context,
    is_global: bool,
    pinned: bool,
    category: str | None,
    limit: int,
    all_projects: bool,
    group_owned: bool,
    owned_by_group: str | None,
    include_group_owned: bool,
) -> None:
    """List memories."""
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
        else:
            memories = store.list(
                scope="project",
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

        display_memory(memory, verbose=True)


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

        console.print(f"[bold]Session Summaries[/bold] ({len(summaries)} found)")
        for summary in summaries:
            console.print(f"\n[dim]{format_timestamp(summary.created_at)}[/dim]")
            console.print(f"  {summary.content}")


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


if __name__ == "__main__":
    main()
