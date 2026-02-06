---
name: agent-memory
description: Long-term memory store for AI agents - save, search, and manage persistent memories across sessions. Load this skill for complete command reference.
version: 0.3.0
---

# Agent Memory - Full Reference

This skill provides complete documentation for the `agent-memory` CLI. Core behaviors (startup, auto-save, session end) are handled by the rules file which is always loaded.

## Setup

The agent-memory CLI must be installed and accessible:

```bash
# Check if installed
agent-memory --version

# If not in PATH, activate it
source ~/.agent-memory/bin/activate-memory
```

## Memory Scopes (Three-Scope Model)

| Scope | Storage | Visibility | Use Case |
|-------|---------|------------|----------|
| **project** | Project DB | Current project only | Project-specific decisions, patterns (default) |
| **group** | Global DB | Projects with matching `--groups` flag | Team conventions, shared patterns |
| **global** | Global DB | All projects, always | User preferences, cross-cutting concerns |

## Commands

### Save a Memory

```bash
# Save to current project (default scope)
agent-memory save "authentication uses JWT tokens stored in httpOnly cookies"

# Save with group scope (visible to projects using --groups=backend)
agent-memory save --group=backend "API versioning pattern for all services"

# Save globally (visible to all projects always)
agent-memory save --global "user prefers functional components over classes"

# Save and pin (always loaded at startup)
agent-memory save --pin "CRITICAL: never modify the legacy payment module"

# Save with explicit category
agent-memory save --category=decision "rejected Redux, using Zustand instead"
```

### Search Memories

```bash
# Semantic search (if enabled)
agent-memory search "how does authentication work"

# With stricter threshold
agent-memory search "auth" --threshold=0.8

# Include global memories
agent-memory search "coding style" --global

# Search across all projects (user visibility only)
agent-memory search "api pattern" --all-projects
```

### List Memories

```bash
# List project memories
agent-memory list

# List only pinned memories
agent-memory list --pinned

# List by category
agent-memory list --category=decision

# List global memories only
agent-memory list --global

# List global + group-scoped memories
agent-memory list --global --include-group-owned

# List group-scoped memories only
agent-memory list --group-owned

# List memories owned by a specific group
agent-memory list --owned-by=backend-team

# List from all projects (user visibility only)
agent-memory list --all-projects
```

### Manage Memories

```bash
# Get specific memory
agent-memory get mem_abc123

# Pin/unpin a memory
agent-memory pin mem_abc123
agent-memory unpin mem_abc123

# Delete a memory
agent-memory forget mem_abc123

# Delete memories matching a pattern
agent-memory forget --search "old pattern"
```

### Group Management for Memories

Manage owner groups for group-scoped memories:

```bash
# Add owner groups to a group-scoped memory
agent-memory add-groups mem_abc123 backend-team frontend-team

# Remove owner groups from a group-scoped memory
agent-memory remove-groups mem_abc123 frontend-team

# Replace all owner groups
agent-memory set-groups mem_abc123 backend-team devops

# Change scope of a memory
agent-memory set-scope mem_abc123 global                     # → global scope
agent-memory set-scope mem_abc123 group --group=backend      # → group scope
agent-memory set-scope mem_abc123 project --to-project /path # → project scope
```

### Session Management

```bash
# Start a new session
agent-memory session start

# Add a session summary
agent-memory session summarize "Implemented user authentication with JWT"

# End session
agent-memory session end

# List sessions
agent-memory session list

# Load last session context
agent-memory session load --last
```

### Workspace Groups

**Workspace groups are collections of PROJECTS that can share memories with each other.**

When a user mentions creating a "group with projects", they want to:
1. Create the workspace group
2. Add the listed project directories to it

```bash
# Create a group
agent-memory group create backend-team

# Delete a group
agent-memory group delete backend-team

# Add current project to a group
agent-memory group join backend-team

# Add a specific project to a group
agent-memory group join backend-team --project /path/to/project

# Remove project from a group
agent-memory group leave backend-team

# List all groups
agent-memory group list

# Show group details (includes project list)
agent-memory group show backend-team
```

#### Interpreting User Requests About Groups

| User says | Meaning | Action |
|-----------|---------|--------|
| "Create a group X with projects A, B, C" | Create group and add projects | `group create X` then `group join X --project <path>` for each |
| "Add project Y to group X" | Add a project to existing group | `group join X --project <path>` |
| "Share this memory with group X" | Save with group scope | `save --group=X "content"` |
| "Create a memory for group X" | Save with group scope | `save --group=X "content"` |

### Promote/Unpromote

Move memories between scopes:

```bash
# Promote project memory to global (default)
agent-memory promote mem_abc123

# Promote project memory to group scope
agent-memory promote mem_abc123 --to-group=backend-team

# Promote from a specific project
agent-memory promote mem_abc123 --from-project /path/to/project

# Move a global/group memory to a project (unpromote)
agent-memory unpromote mem_abc123 --to-project /path/to/project
```

### Configuration

```bash
# Show config
agent-memory config show

# Enable/disable semantic search
agent-memory config set semantic.enabled=true

# Set similarity threshold
agent-memory config set semantic.threshold=0.7

# Enable/disable autosave
agent-memory config set autosave.enabled=true
```

### Cross-Project Visibility (Users Only)

View memories across all projects (for users, not agents):

```bash
# List all tracked projects
agent-memory projects

# List memories from all projects
agent-memory list --all-projects

# Search across all projects
agent-memory search "pattern" --all-projects

# Export from all projects
agent-memory export --all-projects
```

## Startup Behavior

At the beginning of each session:

1. **Pinned project memories are automatically loaded**
2. **Pinned global memories are automatically loaded**
3. **Group-scoped memories are NOT loaded by default** - Use `--groups` to opt-in
4. **Ask the user about previous session** - "Would you like me to load the previous session context?"

Use this command to get startup context:

```bash
# Default: project + global memories only (no groups)
agent-memory startup --json

# Include specific groups
agent-memory startup --json --groups=backend-team

# Include multiple specific groups
agent-memory startup --json --groups=backend-team,shared-libs

# Include all groups
agent-memory startup --json --groups=all

# Include all groups except one
agent-memory startup --json --groups=all --exclude-groups=legacy-team
```

## Memory Categories

| Category | When to Use |
|----------|-------------|
| `factual` | Facts about codebase architecture, patterns, how things work |
| `decision` | User preferences, rejected options, chosen approaches |
| `task_history` | What was completed, implementation details |
| `session_summary` | Condensed summaries of work sessions |

## Best Practices

1. **Save decisions, not just facts** - "User rejected X because Y" is more valuable than just facts
2. **Be specific** - Include relevant file paths, function names, context
3. **Pin critical memories** - Things that should always be remembered
4. **Summarize sessions** - Creates searchable context for future sessions
5. **Search before asking** - Check memory for relevant context before asking the user
6. **Don't create groups without permission** - Only manage groups when user explicitly requests
7. **Understand group requests** - When user says "group with projects", they mean add projects to a group

## Example Workflow

```bash
# At session start
agent-memory startup --json

# During work - save learnings
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"
agent-memory save --category=decision "User prefers error handling with Result types over exceptions"

# If user asks to share across team projects:
agent-memory save --pin --group=backend-team "All services must use structured logging with correlation IDs"

# Before ending
agent-memory session summarize "Implemented Stripe webhook handler with signature verification. Added Result type pattern for error handling."
```
