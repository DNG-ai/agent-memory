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
```

### Search Memories

```bash
# Semantic search (if enabled)
agent-memory search "how does authentication work"

# With stricter threshold
agent-memory search "auth" --threshold=0.8

# Include global memories
agent-memory search "coding style" --global
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

## Startup Behavior

At the beginning of each session:

1. **Pinned memories are automatically loaded** - These contain critical context
2. **Ask the user about previous session** - "Would you like me to load the previous session context?"

Use this command to get startup context:

```bash
agent-memory startup --json
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

## Example Workflow

```bash
# At session start
agent-memory startup

# During work - save learnings
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"
agent-memory save --category=decision "User prefers error handling with Result types over exceptions"

# Before ending
agent-memory session summarize "Implemented Stripe webhook handler with signature verification. Added Result type pattern for error handling."
```
