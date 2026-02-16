"""Flask web UI for agent-memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from agent_memory.config import Config, load_config
from agent_memory.event_log import EventLog
from agent_memory.groups import GroupManager
from agent_memory.store import MemoryStore
from agent_memory.utils import get_current_project_path, truncate_text


def create_app(config: Config | None = None, project_path: Path | None = None) -> Flask:
    """Create and configure the Flask app.

    Args:
        config: Configuration object. Loaded from defaults if None.
        project_path: Current project path. Auto-detected if None.
    """
    if config is None:
        config = load_config()
    if project_path is None:
        project_path = get_current_project_path()

    app = Flask(__name__)
    app.config["config"] = config
    app.config["project_path"] = project_path

    def get_store() -> MemoryStore:
        return MemoryStore(config, project_path)

    def get_groups() -> GroupManager:
        return GroupManager(config)

    # ── HTML ────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Memories CRUD ───────────────────────────────────────────

    @app.route("/api/memories")
    def list_memories():
        scope = request.args.get("scope", "project")
        category = request.args.get("category") or None
        pinned = request.args.get("pinned")
        q = request.args.get("q")
        limit = int(request.args.get("limit", "50"))

        with get_store() as store:
            if scope == "project":
                # Project scope with optional multi-project filter
                project_filter = request.args.get("projects", "")
                selected_paths = [
                    p.strip() for p in project_filter.split(",") if p.strip()
                ] if project_filter else None

                if q:
                    results = store.search_all_projects(q, limit_per_project=limit)
                else:
                    results = store.list_all_projects(
                        category=category,
                        pinned_only=pinned == "true",
                        limit_per_project=limit,
                        include_global=False,
                    )

                if selected_paths:
                    # Filter to only selected projects
                    selected_set = set(selected_paths)
                    memories = [
                        m for proj, mems in results
                        if proj is not None and str(proj) in selected_set
                        for m in mems
                    ]
                else:
                    # All projects (exclude the global=None entry)
                    memories = [
                        m for proj, mems in results
                        if proj is not None
                        for m in mems
                    ]
            elif scope == "group":
                group_name = request.args.get("group") or None
                if q:
                    group_memories = store.list_by_group(limit=limit * 2)
                    query_terms = q.lower().split()
                    memories = [
                        m for m in group_memories
                        if all(t in m.content.lower() for t in query_terms)
                    ]
                    if group_name:
                        memories = [m for m in memories if group_name in m.groups]
                else:
                    memories = store.list_by_group(
                        group_name=group_name,
                        pinned_only=pinned == "true",
                        category=category,
                        limit=limit,
                    )
            elif scope == "global":
                if q:
                    memories = store.search_keyword(q, "global", limit)
                else:
                    memories = store.list(
                        scope="global",
                        category=category,
                        pinned_only=pinned == "true",
                        limit=limit,
                    )
            else:
                memories = []
        return jsonify([m.to_dict() for m in memories])

    @app.route("/api/memories/search")
    def search_memories():
        q = request.args.get("q", "")
        scope = request.args.get("scope", "project")
        limit = int(request.args.get("limit", "20"))
        if not q.strip():
            return jsonify([])
        with get_store() as store:
            memories = store.search_keyword(q, scope, limit)
        return jsonify([m.to_dict() for m in memories])

    @app.route("/api/memories/<memory_id>")
    def get_memory(memory_id: str):
        with get_store() as store:
            memory = store.get_by_id(memory_id)
        if memory is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(memory.to_dict())

    @app.route("/api/memories", methods=["POST"])
    def create_memory():
        data: dict[str, Any] = request.get_json() or {}
        content = data.get("content", "").strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400

        scope = data.get("scope", "project")
        groups = data.get("groups") or None

        with get_store() as store:
            memory = store.save(
                content=content,
                category=data.get("category") or None,
                scope=scope,
                pinned=data.get("pinned", False),
                source="web_ui",
                metadata=data.get("metadata") or None,
                groups=groups,
            )
        return jsonify(memory.to_dict()), 201

    @app.route("/api/memories/<memory_id>", methods=["PUT"])
    def update_memory(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        with get_store() as store:
            memory = store.get_by_id(memory_id)
            if memory is None:
                return jsonify({"error": "Not found"}), 404
            updated = store.update(
                memory_id,
                scope=memory.scope,
                content=data.get("content"),
                category=data.get("category"),
                metadata=data.get("metadata"),
            )
        if updated is None:
            return jsonify({"error": "Update failed"}), 500
        return jsonify(updated.to_dict())

    @app.route("/api/memories/<memory_id>", methods=["DELETE"])
    def delete_memory(memory_id: str):
        with get_store() as store:
            deleted = store.delete_by_id(memory_id)
        if not deleted:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"ok": True})

    # ── Pin / Unpin ─────────────────────────────────────────────

    @app.route("/api/memories/<memory_id>/pin", methods=["POST"])
    def pin_memory(memory_id: str):
        with get_store() as store:
            memory = store.get_by_id(memory_id)
            if memory is None:
                return jsonify({"error": "Not found"}), 404
            result = store.pin(memory_id, memory.scope)
        if result is None:
            return jsonify({"error": "Pin failed"}), 500
        return jsonify(result.to_dict())

    @app.route("/api/memories/<memory_id>/unpin", methods=["POST"])
    def unpin_memory(memory_id: str):
        with get_store() as store:
            memory = store.get_by_id(memory_id)
            if memory is None:
                return jsonify({"error": "Not found"}), 404
            result = store.unpin(memory_id, memory.scope)
        if result is None:
            return jsonify({"error": "Unpin failed"}), 500
        return jsonify(result.to_dict())

    # ── Promote / Unpromote ─────────────────────────────────────

    @app.route("/api/memories/<memory_id>/promote", methods=["POST"])
    def promote_memory(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        to_group = data.get("to_group") or None
        with get_store() as store:
            result = store.promote(memory_id, to_group=to_group)
        if result is None:
            return jsonify({"error": "Not found or not in project scope"}), 404
        return jsonify(result.to_dict())

    @app.route("/api/memories/<memory_id>/unpromote", methods=["POST"])
    def unpromote_memory(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        to_project = data.get("to_project")
        if not to_project:
            to_project = str(project_path) if project_path else None
        if not to_project:
            return jsonify({"error": "to_project is required"}), 400
        with get_store() as store:
            result = store.unpromote(memory_id, Path(to_project))
        if result is None:
            return jsonify({"error": "Not found or not in global/group scope"}), 404
        return jsonify(result.to_dict())

    # ── Scope / Group management on a memory ────────────────────

    @app.route("/api/memories/<memory_id>/scope", methods=["PUT"])
    def set_memory_scope(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        new_scope = data.get("scope")
        groups = data.get("groups") or None
        if not new_scope:
            return jsonify({"error": "scope is required"}), 400
        try:
            with get_store() as store:
                result = store.set_scope(memory_id, new_scope, groups=groups)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result.to_dict())

    @app.route("/api/memories/<memory_id>/groups", methods=["POST"])
    def add_memory_groups(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        group_names = data.get("groups", [])
        if not group_names:
            return jsonify({"error": "groups list is required"}), 400
        try:
            with get_store() as store:
                result = store.add_groups(memory_id, group_names)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result.to_dict())

    @app.route("/api/memories/<memory_id>/groups", methods=["DELETE"])
    def remove_memory_groups(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        group_names = data.get("groups", [])
        if not group_names:
            return jsonify({"error": "groups list is required"}), 400
        try:
            with get_store() as store:
                result = store.remove_groups(memory_id, group_names)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result.to_dict())

    @app.route("/api/memories/<memory_id>/groups", methods=["PUT"])
    def set_memory_groups(memory_id: str):
        data: dict[str, Any] = request.get_json() or {}
        group_names = data.get("groups", [])
        if not group_names:
            return jsonify({"error": "groups list is required"}), 400
        try:
            with get_store() as store:
                result = store.set_groups(memory_id, group_names)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result.to_dict())

    # ── Groups ──────────────────────────────────────────────────

    @app.route("/api/groups")
    def list_groups():
        gm = get_groups()
        groups = gm.list_groups()
        return jsonify([g.to_dict() for g in groups])

    @app.route("/api/groups/<name>")
    def get_group(name: str):
        gm = get_groups()
        group = gm.get(name)
        if group is None:
            return jsonify({"error": "Not found"}), 404

        result = group.to_dict()
        # Include group memories
        with get_store() as store:
            memories = store.list_by_group(group_name=name, limit=100)
        result["memories"] = [m.to_dict() for m in memories]
        return jsonify(result)

    # ── Projects ────────────────────────────────────────────────

    @app.route("/api/projects")
    def list_projects():
        with get_store() as store:
            stats = store.get_all_project_stats()
        result = []
        for s in stats:
            result.append({
                "project_path": str(s["project_path"]),
                "memory_count": s["memory_count"],
                "last_updated": s["last_updated"].isoformat() if s["last_updated"] else None,
            })
        return jsonify(result)

    # ── Stats ───────────────────────────────────────────────────

    @app.route("/api/stats")
    def get_stats():
        with get_store() as store:
            # Per-project stats
            all_project_stats = store.get_all_project_stats()
            projects_total = sum(s["memory_count"] for s in all_project_stats)

            # Global (excludes group-scoped)
            global_memories = store.list("global", limit=10000)
            global_count = len(global_memories)

            # Group-scoped
            group_memories = store.list_by_group(limit=10000)
            group_count = len(group_memories)

            # Category breakdown across all visible scopes
            categories: dict[str, int] = {}
            all_results = store.list_all_projects(
                limit_per_project=10000, include_global=False,
            )
            for _, mems in all_results:
                for m in mems:
                    if m.scope == "project":
                        categories[m.category] = categories.get(m.category, 0) + 1
            for m in global_memories:
                categories[m.category] = categories.get(m.category, 0) + 1
            for m in group_memories:
                categories[m.category] = categories.get(m.category, 0) + 1

        gm = get_groups()
        groups = gm.list_groups()

        # Build per-project info for the sidebar picker
        project_list = []
        for s in all_project_stats:
            project_list.append({
                "path": str(s["project_path"]),
                "name": s["project_path"].name,
                "count": s["memory_count"],
            })

        return jsonify({
            "projects_total": projects_total,
            "global_count": global_count,
            "group_count": group_count,
            "total": projects_total + global_count + group_count,
            "categories": categories,
            "group_names": [g.name for g in groups],
            "project_list": project_list,
            "current_project": str(project_path) if project_path else None,
        })

    # ── Usage / Analytics ─────────────────────────────────────────

    @app.route("/api/usage")
    def get_usage():
        since_days = int(request.args.get("since_days", "30"))
        event_log = EventLog(config)

        try:
            command_counts = event_log.get_command_counts(since_days)
            search_stats = event_log.get_search_stats(since_days)
            session_stats = event_log.get_session_stats(since_days)
        finally:
            event_log.close()

        # Memory effectiveness from store
        from datetime import timedelta
        from agent_memory.utils import get_timestamp

        now = get_timestamp()
        total_memories = 0
        never_accessed = 0
        most_accessed = []
        pin_candidates = []

        with get_store() as store:
            for check_scope in ["project", "global"]:
                try:
                    memories = store.list(scope=check_scope, limit=100000)
                    total_memories += len(memories)
                    never_accessed += sum(1 for m in memories if m.access_count == 0)
                except Exception:
                    continue

            for check_scope in ["project", "global"]:
                try:
                    most_accessed.extend(store.get_most_accessed(check_scope, 5))
                except Exception:
                    continue
            most_accessed.sort(key=lambda m: m.access_count, reverse=True)
            most_accessed = most_accessed[:5]

            for check_scope in ["project", "global"]:
                try:
                    pin_candidates.extend(store.get_pin_candidates(check_scope, 5, 5))
                except Exception:
                    continue
            pin_candidates.sort(key=lambda m: m.access_count, reverse=True)
            pin_candidates = pin_candidates[:5]

        # Recommendations
        recommendations: list[dict[str, str]] = []
        for m in pin_candidates:
            recommendations.append({
                "action": "pin",
                "memory_id": m.id,
                "reason": f"Accessed {m.access_count} times but not pinned",
            })
        if search_stats["total_searches"] > 0 and search_stats["zero_result_rate"] > 0.15:
            pct = int(search_stats["zero_result_rate"] * 100)
            recommendations.append({
                "action": "search",
                "reason": f"{pct}% of searches return 0 results",
            })

        # Search insights
        recent_searches = event_log.get_recent_searches(since_days, limit=50)
        top_queries = event_log.get_top_queries(since_days, limit=20)

        return jsonify({
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
            "search_insights": {
                "recent_searches": recent_searches,
                "top_queries": top_queries,
            },
            "recommendations": recommendations,
        })

    # ── Config ──────────────────────────────────────────────────

    @app.route("/api/config")
    def get_config():
        return jsonify({
            "base_path": str(config.base_path),
            "current_project": str(project_path) if project_path else None,
            "semantic_enabled": config.semantic.enabled,
            "expiration_enabled": config.expiration.enabled,
        })

    return app
