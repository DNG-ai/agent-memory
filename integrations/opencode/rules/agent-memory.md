# Agent Memory

You have access to long-term memory via the `agent-memory` CLI. Use it to persist learnings, decisions, and context across sessions.

## Memory Scopes (Three-Scope Model)

| Scope | Storage | Visibility |
|-------|---------|------------|
| **project** | Project DB | Current project only (default) |
| **group** | Global DB | Only projects in matching groups (opt-in via `--groups`) |
| **global** | Global DB | All projects, always |

## Session Start (ALWAYS DO THIS)

At the beginning of EVERY session, run:

```bash
agent-memory startup --json
```

This loads:
- Pinned project memories (critical context for this project)
- Pinned global memories (cross-project context)
- Previous session info

**Note:** Group-scoped memories are NOT loaded by default. Only include them when the user requests via `--groups`.

## When to Search Memory

Search proactively — don't wait until you're stuck:

- **Before starting any task** — check for prior work, decisions, or patterns related to the task
- **Before asking the user a question** — the answer may already be saved
- **When encountering unfamiliar code** — check for saved navigation aids or architecture notes
- **When debugging** — search for known error patterns and past fixes

```bash
agent-memory search "topic to search for"

# Include group memories in search (works from any directory)
agent-memory search "pattern" --group=backend-team
```

## Auto-Save Triggers

Save memories automatically when:

1. **Completing a significant task** — Record what was done and key decisions
2. **User says "remember this"** — Save the referenced information
3. **Learning something important** — Architecture decisions, patterns, user preferences
4. **Fixing a non-obvious bug** — Save the error-cause-fix pattern so it's not re-debugged
5. **Discovering project conventions** — Build commands, test patterns, file organization

```bash
# Save to current project (default)
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"

# Save a user decision/preference with rationale
agent-memory save --category=decision --meta rationale="performance" --meta alternatives="Redis,Memcached" \
  "Use in-memory caching for session data"

# Pin critical information (always loaded at startup)
agent-memory save --pin "CRITICAL: Never modify the legacy auth module directly"

# Save globally (visible to all projects)
agent-memory save --global "User prefers tabs over spaces"

# Save a debugging pattern
agent-memory save "Tests fail with ECONNREFUSED when Redis is not running — start with: docker compose up redis"

# Attach structured metadata to any memory
agent-memory save --meta status=approved --meta decided_by=user "Deploy via GitHub Actions, not CircleCI"
```

## Writing Good Memories

**Be specific and searchable:**
- GOOD: `"Auth middleware is in src/middleware/auth.ts — validates JWT from Authorization header"`
- BAD: `"There's an auth file somewhere"`

**Include the WHY, not just the WHAT:**
- GOOD: `"Using Zustand over Redux — simpler API, less boilerplate for our small state needs"`
- BAD: `"We use Zustand"`

**Save error-fix patterns with context:**
- GOOD: `"'Cannot read property of undefined' in UserProfile — caused by API returning null when user has no avatar. Fix: add optional chaining on user.avatar?.url"`
- BAD: `"Fixed a bug in UserProfile"`

**Don't save:**
- Transient state (current git branch, temporary workarounds being actively changed)
- Obvious things the codebase makes clear (e.g., "this is a React project" when package.json shows it)
- Exact code snippets that will change — describe the pattern instead

## Memory Maintenance

When you notice a memory is wrong or outdated:

```bash
# Remove outdated memories
agent-memory forget mem_abc123

# Update a memory with fresh content
# (search → forget old → save new)
agent-memory search "outdated topic"
agent-memory forget mem_abc123
agent-memory save "Updated information about the topic"
```

## Workspace Groups (IMPORTANT - Read Carefully)

**Workspace groups are collections of PROJECTS, not memories.**

A group allows multiple project directories to share memories with each other. When a user mentions "group" with project names, they want to organize projects together.

### Interpreting User Requests

| User says | Meaning | Action |
|-----------|---------|--------|
| "Create a group X with projects A, B, C" | Create group and add projects | `group create X` then `group join X --project <path>` for each |
| "Add project Y to group X" | Add a project to existing group | `group join X --project <path>` |
| "Share this memory with group X" | Save with group scope | `save --group=X "content"` |
| "Create a memory for group X" | Save with group scope | `save --group=X "content"` |

### Group Management (User Request Only)

**Only manage workspace groups when the user explicitly asks.**

```bash
# Create a group
agent-memory group create backend-team

# Add projects to a group (find paths first if needed)
agent-memory group join backend-team --project /path/to/project1
agent-memory group join backend-team --project /path/to/project2

# Show group with its projects
agent-memory group show backend-team

# Save a memory with group scope (visible to group members)
agent-memory save --group=backend-team "API versioning pattern for all services"
```

### Managing Group-Scoped Memories

```bash
# Add owner groups to a group-scoped memory
agent-memory add-groups <id> group1 group2

# Remove owner groups
agent-memory remove-groups <id> group1

# Replace all owner groups
agent-memory set-groups <id> group1 group2

# Change scope entirely
agent-memory set-scope <id> global          # group → global
agent-memory set-scope <id> group --group=X # global → group
```

## Responding to Group Preferences

If the user says:
- "Use memories from [group]" → `agent-memory startup --json --groups=[group]`
- "Use all group memories" → `agent-memory startup --json --groups=all`
- "Use all groups except [group]" → `agent-memory startup --json --groups=all --exclude-groups=[group]`
- "Don't use group memories" → Default behavior (no flags needed)

## Promote/Unpromote

Move memories between scopes:

```bash
# project → global
agent-memory promote <id>

# project → group
agent-memory promote <id> --to-group=backend-team

# global/group → project
agent-memory unpromote <id> --to-project /path/to/project
```

## Session End

Before ending a session, summarize the work accomplished:

```bash
agent-memory session summarize "Brief summary of what was done and key decisions made"
```

A good session summary includes:
- What tasks were completed
- Key decisions made (and why)
- Anything left unfinished or blocked
- New patterns or conventions established

## Quick Group Memory Access

View group memories from anywhere (no need to be in a member project):

```bash
# Quick view of group info + memories
agent-memory groups backend-team

# All group memories
agent-memory groups all

# Group-scoped pinned memories only
agent-memory groups backend-team --pinned

# List group memories directly
agent-memory list --group=backend-team
agent-memory list --group=all  # all groups
```

## Error-Fix Pattern Analysis

After a debugging session, extract and save error-fix patterns automatically:

```bash
# Analyze inline text
agent-memory session analyze "Hit TypeError in auth.ts, null check missing, fixed with optional chaining"

# Analyze last session summaries
agent-memory session analyze --last

# Preview without saving
agent-memory session analyze --last --dry-run
```

If error-detection hooks are enabled, you'll see reminders when errors occur in command output. Save the pattern when you fix it:

```bash
agent-memory save --meta error="ECONNREFUSED" --meta root_cause="Redis not running" \
  "Tests fail with ECONNREFUSED — start Redis with: docker compose up redis"
```

## Full Documentation

For complete command reference and advanced usage, load the skill: `/skill agent-memory`
