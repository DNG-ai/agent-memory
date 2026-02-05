# Agent Memory Integration

You have access to long-term memory via the `agent-memory` CLI tool. This allows you to save learnings, decisions, and context that persist across sessions.

## Setup

The CLI is located at: `$AGENT_MEMORY_PATH/bin/agent-memory` (default: `~/.agent-memory`)

If not in PATH, use the full path or run:
```bash
source ~/.agent-memory/bin/activate-memory
```

## At Session Start

1. **Load pinned memories** (critical context that's always relevant):
   ```bash
   agent-memory list --pinned
   ```

2. **Ask the user** if they want to load the previous session:
   > "Would you like me to load the previous session context?"
   
   If yes:
   ```bash
   agent-memory session load --last
   ```

3. **Or get full startup context as JSON**:
   ```bash
   agent-memory startup --json
   ```

## During Session

### Searching for Context

Before asking the user about something, check if you already have relevant memories:

```bash
# Semantic search (if enabled)
agent-memory search "how does authentication work"

# Search with specific threshold
agent-memory search "auth patterns" --threshold=0.8

# Include global memories
agent-memory search "coding style" --global
```

### Saving Learnings

When you learn something important about the codebase or user preferences:

```bash
# Save a factual learning
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"

# Save a user decision/preference
agent-memory save --category=decision "User prefers functional components over class components"

# Save and pin critical information
agent-memory save --pin "CRITICAL: The legacy auth module should never be modified directly"

# Save globally (applies to all projects)
agent-memory save --global "User prefers detailed error messages in development"
```

### Memory Categories

| Category | Use For |
|----------|---------|
| `factual` | Facts about codebase architecture, patterns, how things work |
| `decision` | User preferences, rejected approaches, chosen patterns |
| `task_history` | What was completed, implementation details |
| `session_summary` | Condensed summaries of work sessions |

## Auto-save Triggers

Save memories automatically when:

1. **Completing a significant task** - Record what was done and any learnings
2. **User says "remember this"** or similar - Save the referenced information
3. **Every ~20 messages** - Create a session summary

### Session Summaries

Periodically summarize the session work:

```bash
agent-memory session summarize "Implemented user authentication with JWT tokens. Added password reset flow. Fixed bug in token refresh logic."
```

## Managing Memories

```bash
# List all memories
agent-memory list

# List by category
agent-memory list --category=decision

# Get a specific memory
agent-memory get mem_abc123

# Pin/unpin important memories
agent-memory pin mem_abc123
agent-memory unpin mem_abc123

# Delete a memory
agent-memory forget mem_abc123

# Delete memories matching a pattern
agent-memory forget --search "outdated info" --confirm
```

## Session Management

```bash
# Start a new session (optional - helps organize summaries)
agent-memory session start

# End session
agent-memory session end

# List past sessions
agent-memory session list
```

## Configuration

```bash
# Show current configuration
agent-memory config show

# Toggle semantic search
agent-memory config set semantic.enabled=true

# Adjust similarity threshold (0.0-1.0)
agent-memory config set semantic.threshold=0.7

# Configure autosave
agent-memory config set autosave.enabled=true
agent-memory config set autosave.summary_interval_messages=20
```

## Best Practices

1. **Save decisions, not just facts** 
   - Good: "User rejected Redux in favor of Zustand because they prefer simpler state management"
   - Less useful: "The app uses Zustand"

2. **Be specific and include context**
   - Good: "The /api/auth/refresh endpoint expects the refresh token in an httpOnly cookie, not in the request body"
   - Less useful: "Auth uses cookies"

3. **Pin critical memories**
   - Things that should ALWAYS be considered
   - Critical constraints or warnings

4. **Search before asking**
   - Check memory for relevant context before asking the user questions

5. **Summarize sessions**
   - Creates searchable context for future sessions
   - Include what was done and key decisions made

## Example Workflow

```bash
# Start of session
agent-memory startup
# Shows pinned memories and asks about loading previous session

# During work - save learnings as you go
agent-memory save "User model has soft delete implemented via deleted_at timestamp"
agent-memory save --category=decision "Chose to use Prisma over raw SQL for type safety"

# When user says "remember that I prefer..."
agent-memory save --category=decision "User prefers explicit error handling with match statements"

# Before ending session
agent-memory session summarize "Implemented user profile editing. Added avatar upload with S3. Used Prisma for database access. Key decision: chose match-based error handling pattern."

# End of session
agent-memory session end
```
