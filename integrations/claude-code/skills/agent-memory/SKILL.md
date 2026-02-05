---
name: agent-memory
description: Long-term memory store for AI agents - save, search, and manage persistent memories across sessions. Load this skill for complete command reference.
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

## Commands

### Save a Memory

```bash
# Save to current project
agent-memory save "authentication uses JWT tokens stored in httpOnly cookies"

# Save globally (across all projects)
agent-memory save --global "user prefers functional components over classes"

# Save and pin (always loaded at startup)
agent-memory save --pin "CRITICAL: never modify the legacy payment module"

# Save with explicit category
agent-memory save --category=decision "rejected Redux, using Zustand instead"

# Save and share with a group (ONLY when user explicitly asks)
agent-memory save --share=backend-team "API versioning pattern for all services"
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

# List global memories
agent-memory list --global

# List memories shared with any group
agent-memory list --shared

# List memories shared with a specific group
agent-memory list --shared-with=backend-team

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

Groups allow related projects to share memories with each other.

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

# Show group details
agent-memory group show backend-team
```

### Memory Sharing

Share memories with groups so sibling projects can see them at startup.

**IMPORTANT:** DO NOT share memories with groups unless the user explicitly asks.

```bash
# Share a memory with groups
agent-memory share mem_abc123 backend-team frontend-team

# Remove from specific groups
agent-memory unshare mem_abc123 frontend-team

# Remove from all groups
agent-memory unshare mem_abc123 --all
```

### Promote/Unpromote

Move memories between project and global scope.

```bash
# Promote a project memory to global (moves, not copies)
agent-memory promote mem_abc123

# Promote from a specific project
agent-memory promote mem_abc123 --from-project /path/to/project

# Move a global memory to a project (unpromote)
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

# Enable/disable group-shared memories at startup
agent-memory config set startup.include_group_shared_pins=true
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

1. **Pinned memories are automatically loaded** - These contain critical context
2. **Group-shared memories are loaded** - Pinned memories from sibling projects
3. **Ask the user about previous session** - "Would you like me to load the previous session context?"

Use this command to get startup context:

```bash
agent-memory startup --json

# Explicitly include/exclude group-shared memories
agent-memory startup --json --include-group-shared
agent-memory startup --json --no-include-group-shared
```

## Memory Categories

| Category | When to Use |
|----------|-------------|
| `factual` | Facts about codebase architecture, patterns, how things work |
| `decision` | User preferences, rejected options, chosen approaches |
| `task_history` | What was completed, implementation details |
| `session_summary` | Condensed summaries of work sessions |

## Memory Scopes

| Scope | Visibility | Use Case |
|-------|------------|----------|
| Project | Current project only | Project-specific decisions, patterns |
| Global | All projects | User preferences, cross-cutting concerns |
| Group-shared | Sibling projects in same group | Team conventions, shared patterns |

## Best Practices

1. **Save decisions, not just facts** - "User rejected X because Y" is more valuable than just facts
2. **Be specific** - Include relevant file paths, function names, context
3. **Pin critical memories** - Things that should always be remembered
4. **Summarize sessions** - Creates searchable context for future sessions
5. **Search before asking** - Check memory for relevant context before asking the user
6. **Don't share without permission** - Only use `--share` when user explicitly requests

## Example Workflow

```bash
# At session start
agent-memory startup --json

# During work - save learnings
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"
agent-memory save --category=decision "User prefers error handling with Result types over exceptions"

# If user asks to share across team projects:
agent-memory save --pin --share=backend-team "All services must use structured logging with correlation IDs"

# Before ending
agent-memory session summarize "Implemented Stripe webhook handler with signature verification. Added Result type pattern for error handling."
```
