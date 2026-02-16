# Agent Memory

Long-term memory store for AI agents. Enables agents (OpenCode, Claude Code) to save, search, and manage persistent memories across sessions.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [When to Use What: Memory Store vs CLAUDE.md vs Skills](#when-to-use-what-memory-store-vs-claudemd-vs-skills)
  - [CLAUDE.md / agents.md (Static Instructions)](#claudemd--agentsmd-static-instructions)
  - [Skills (On-Demand Instructions)](#skills-on-demand-instructions)
  - [Memory Store (agent-memory)](#memory-store-agent-memory)
  - [Decision Matrix](#decision-matrix)
  - [Rule of Thumb](#rule-of-thumb)
- [CLI Reference](#cli-reference)
  - [Core Commands](#core-commands)
  - [Session Commands](#session-commands)
  - [Configuration](#configuration)
  - [Group Commands](#group-commands)
  - [Sharing Commands](#sharing-commands)
  - [Other Commands](#other-commands)
  - [Cross-Project Visibility (User Only)](#cross-project-visibility-user-only)
- [Workspace Groups](#workspace-groups)
  - [Creating and Managing Groups](#creating-and-managing-groups)
  - [Sharing Memories with Groups](#sharing-memories-with-groups)
  - [How Sharing Works](#how-sharing-works)
  - [Promote/Unpromote](#promoteunpromote)
- [Memory Categories](#memory-categories)
- [Configuration](#configuration-1)
- [Embedding Providers](#embedding-providers)
  - [Vertex AI (for OpenCode)](#vertex-ai-for-opencode)
  - [Voyage AI (for Claude Code)](#voyage-ai-for-claude-code)
- [Integration](#integration)
  - [OpenCode](#opencode)
  - [Claude Code](#claude-code)
- [Storage Layout](#storage-layout)
- [Development](#development)
- [Architecture](#architecture)
- [License](#license)

## Features

- **Persistent Memory** - Save learnings, decisions, and context that persist across sessions
- **Semantic Search** - Find relevant memories using vector similarity (via Vertex AI or Voyage AI)
- **Session Management** - Track sessions and create summaries
- **Multi-scope** - Project-specific and global memories
- **Pinned Memories** - Mark critical information to always load at startup
- **Workspace Groups** - Group related projects to share memories between them
- **Cross-Project Sharing** - Share specific memories with project groups
- **Promote/Unpromote** - Move memories between project and global scope
- **Auto-expiration** - Optionally expire old memories

## Installation

```bash
# Clone the repository
git clone https://github.com/your-org/agent-memory.git
cd agent-memory

# Run the install script
./install.sh

# Or install with development dependencies
./install.sh --dev
```

After installation, add to your shell profile:

```bash
export AGENT_MEMORY_PATH="$HOME/.agent-memory"
export PATH="$AGENT_MEMORY_PATH/bin:$PATH"
```

## Quick Start

```bash
# Initialize for current project
agent-memory init

# Save a memory
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"

# Save a decision
agent-memory save --category=decision "User prefers functional components over classes"

# Save and pin critical information
agent-memory save --pin "CRITICAL: Never modify the legacy auth module directly"

# Search memories
agent-memory search "how does authentication work"

# List memories
agent-memory list
agent-memory list --pinned
agent-memory list --category=decision

# Get startup context (for agent integration)
agent-memory startup --json
```

## When to Use What: Memory Store vs CLAUDE.md vs Skills

AI coding agents have three mechanisms for persistent knowledge. Each serves a different purpose — using the right one avoids context bloat and keeps information where it's most useful.

### CLAUDE.md / agents.md (Static Instructions)

**What it is:** Markdown files checked into your repo (or in `~/.claude/rules/`) that are loaded into the agent's context every session.

**Use when the knowledge is:**
- Fixed project conventions that rarely change ("always use `bun`, never `npm`")
- Build/test/lint commands the agent should always know
- Architectural rules and guardrails ("never modify the legacy auth module directly")
- Coding standards (formatting, naming, import ordering)
- Repo structure orientation ("API routes are in `src/routes/`, DB models in `src/models/`")

**Characteristics:**
- Always loaded — no search needed, always in context
- Version-controlled with the project
- Same for every contributor
- Limited by context window — keep it concise

**Examples:**
```markdown
# CLAUDE.md
- Run tests: `pytest -x --tb=short`
- This project uses SQLAlchemy 2.0 async style
- All API endpoints must return JSON:API format
```

### Skills (On-Demand Instructions)

**What it is:** Detailed reference docs loaded only when explicitly invoked (e.g., `/agent-memory`, `/commit`).

**Use when the knowledge is:**
- Detailed command reference or API documentation
- Complex multi-step workflows (deployment procedures, release checklists)
- Specialized tool usage guides
- Anything too large to justify loading every session

**Characteristics:**
- Loaded on demand — keeps context clean until needed
- Static content, authored by humans
- Good for lengthy reference material that would bloat CLAUDE.md
- Invoked by name when the agent (or user) needs it

**Examples:**
- Full CLI reference for a tool (`/agent-memory` loads the complete command docs)
- PR creation workflow with templates and checklists
- Database migration procedures

### Memory Store (agent-memory)

**What it is:** A dynamic, searchable database of learned knowledge that accumulates across sessions.

**Use when the knowledge is:**
- Discovered during work, not known upfront
- Decisions made collaboratively that need rationale preserved
- Evolving — may be updated or invalidated as the project changes
- Personal to the developer, not the repo
- Cross-project or cross-team
- Contextual and needs semantic search

**Characteristics:**
- Dynamic — grows and changes across sessions
- Searchable via semantic similarity
- Scoped (project, group, or global)
- Not version-controlled — lives in `~/.agent-memory/`
- Agent-driven — the agent saves, searches, and maintains memories

**Use Cases:**

**1. Architectural decisions and rationale**
Track why choices were made so future sessions don't revisit settled debates.
```bash
agent-memory save --category=decision \
  --meta alternatives="Redis,Memcached" --meta rationale="performance" \
  "Using in-memory caching for session data — Redis overkill for our scale, revisit at 10k DAU"
```

**2. Error-fix patterns and debugging insights**
Save the error-cause-fix chain so the same bug isn't re-debugged from scratch.
```bash
agent-memory save --meta error="CORS 403" --meta root_cause="missing content-type" \
  "CORS errors on /api/upload — caused by missing multipart/form-data in allowed content types. Fix: add to CORS config in src/middleware/cors.ts"
```

**3. Codebase navigation aids**
Bookmark hard-to-find code paths so the agent doesn't re-explore every session.
```bash
agent-memory save "Auth flow: request hits src/middleware/auth.ts → validates JWT → attaches user to req.ctx → routes check req.ctx.user.role for RBAC"
```

**4. User preferences and workflow habits**
Remember how the developer likes to work, globally across all projects.
```bash
agent-memory save --global "User prefers detailed commit messages with bullet points for each change"
agent-memory save --global "Always suggest running tests before committing"
```

**5. Team and cross-project conventions**
Share patterns across related services using workspace groups.
```bash
agent-memory save --group=backend-services --pin \
  "All backend services must use structured JSON logging with request_id correlation"
agent-memory save --group=backend-services \
  "API versioning: use URL path /v1/, /v2/ — never header-based versioning"
```

**6. Environment and infrastructure gotchas**
Capture tribal knowledge about dev environment quirks.
```bash
agent-memory save "Local dev requires Docker for Postgres and Redis — run: docker compose up -d db redis"
agent-memory save "CI tests flake on the billing module when run in parallel — use: pytest tests/billing/ -p no:xdist"
```

**7. Incomplete work and continuation context**
Leave breadcrumbs for the next session to pick up where you left off.
```bash
agent-memory session summarize "Implemented webhook handler for Stripe events. Still TODO: add idempotency check using event ID, and retry logic for failed deliveries. See src/webhooks/stripe.ts:45"
```

**8. Project-specific patterns the codebase doesn't make obvious**
Document implicit conventions that aren't enforced by linters or types.
```bash
agent-memory save "All database queries go through the repository pattern — never call prisma directly from route handlers. Repos are in src/repos/"
agent-memory save "Feature flags are managed via LaunchDarkly. Check flags in src/flags.ts before adding conditionals"
```

### Decision Matrix

| Scenario | Use |
|----------|-----|
| "Always run `make lint` before committing" | CLAUDE.md |
| "Our API uses JSON:API format" | CLAUDE.md |
| "Full `agent-memory` CLI reference" | Skill |
| "Step-by-step release process with 12 steps" | Skill |
| "We chose Postgres over MongoDB because..." | Memory Store |
| "TypeError in auth.ts — fixed by adding null check" | Memory Store |
| "User prefers tabs over spaces" | Memory Store (global) |
| "All backend services must use structured logging" | Memory Store (group) |
| "The test DB resets between runs, don't cache fixtures" | Memory Store or CLAUDE.md* |

*\*If it's a permanent project rule, put it in CLAUDE.md. If it was discovered during a session and might evolve, save it as a memory.*

### Rule of Thumb

- **Will every session need this?** → CLAUDE.md
- **Is it reference material loaded on demand?** → Skill
- **Was it learned, decided, or discovered?** → Memory Store

## CLI Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `save <content>` | Save a new memory |
| `search <query>` | Search memories |
| `list` | List memories |
| `get <id>` | Get a specific memory |
| `pin <id>` | Pin a memory |
| `unpin <id>` | Unpin a memory |
| `forget <id>` | Delete a memory |
| `reset` | Delete all memories in a scope |

### Session Commands

| Command | Description |
|---------|-------------|
| `session start` | Start a new session |
| `session end` | End the current session |
| `session summarize <text>` | Add a session summary |
| `session list` | List recent sessions |
| `session load --last` | Load last session context |

### Configuration

| Command | Description |
|---------|-------------|
| `config show` | Show current configuration |
| `config set <key>=<value>` | Update configuration |

### Group Commands

| Command | Description |
|---------|-------------|
| `group create <name>` | Create a new workspace group |
| `group delete <name>` | Delete a workspace group |
| `group join <name>` | Add current project to a group |
| `group leave <name>` | Remove current project from a group |
| `group list` | List all workspace groups |
| `group show <name>` | Show group details |

### Sharing Commands

| Command | Description |
|---------|-------------|
| `share <id> <groups...>` | Share a memory with groups |
| `unshare <id> [groups...]` | Remove a memory from groups |
| `promote <id>` | Move project memory to global scope |
| `unpromote <id>` | Move global memory to a project |

### Other Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize memory for current project |
| `startup` | Get startup context for agents |
| `export` | Export memories to file |
| `cleanup` | Remove expired memories |
| `projects` | List all tracked projects |

### Cross-Project Visibility (User Only)

These flags provide visibility across ALL projects for users. Agents only access current project + global memories.

| Flag | Commands | Description |
|------|----------|-------------|
| `--all-projects` | `list`, `search`, `export` | Include memories from all projects |

```bash
# List all tracked projects with memory counts
agent-memory projects

# List all memories across all projects (includes global)
agent-memory list --all-projects

# Search across all projects
agent-memory search "authentication" --all-projects

# Export all memories from all projects
agent-memory export --all-projects --format=json -o all-memories.json
```

Note: The `--all-projects` flag is for user visibility and management. Agents (OpenCode, Claude Code) only have access to the current project's memories plus global memories.

## Workspace Groups

Workspace groups allow you to create collections of related projects that can share memories with each other. This is useful for microservices architectures, monorepos, or any collection of related projects.

### Creating and Managing Groups

```bash
# Create a workspace group
agent-memory group create backend-services

# Add projects to the group
cd /path/to/project-a
agent-memory group join backend-services

cd /path/to/project-b
agent-memory group join backend-services

# List all groups
agent-memory group list

# Show group details
agent-memory group show backend-services
```

### Sharing Memories with Groups

Memories are private by default. You can explicitly share memories with groups:

```bash
# Save and share with a group
agent-memory save --pin --share=backend-services "All services must use structured logging"

# Share an existing memory
agent-memory share mem_abc123 backend-services

# Unshare from specific groups
agent-memory unshare mem_abc123 backend-services

# Unshare from all groups
agent-memory unshare mem_abc123 --all
```

### How Sharing Works

When an agent starts a session:
1. **Project memories** - Always loaded (from current project)
2. **Global memories** - Always loaded (from ~/.agent-memory/global)
3. **Group-shared memories** - NOT loaded by default (opt-in via `--groups` flag)

Group memories are opt-in. Use `--groups` to include them:

```bash
# Default: project + global only (no groups)
agent-memory startup --json

# Include specific groups
agent-memory startup --json --groups=backend-services

# Include all groups
agent-memory startup --json --groups=all

# Include all groups except one
agent-memory startup --json --groups=all --exclude-groups=legacy
```

This allows teams to share critical decisions, patterns, and conventions across related projects while keeping agents focused on the current project by default.

### Promote/Unpromote

Move memories between project and global scope:

```bash
# Promote a project memory to global (moves, not copies)
agent-memory promote mem_abc123

# Move a global memory back to a specific project
agent-memory unpromote mem_abc123 --to-project /path/to/project
```

## Memory Categories

| Category | Use For |
|----------|---------|
| `factual` | Facts about codebase, architecture, patterns |
| `decision` | User preferences, rejected options, chosen approaches |
| `task_history` | What was completed, implementation details |
| `session_summary` | Condensed summaries of work sessions |

## Configuration

Configuration is stored at `~/.agent-memory/config.yaml`:

```yaml
semantic:
  enabled: true
  provider: vertex  # or "claude" (uses Voyage AI)
  threshold: 0.7
  
  vertex:
    project_id: your-gcp-project
    location: us-central1
    model: text-embedding-004
  
  claude:
    api_key_env: VOYAGE_API_KEY
    model: voyage-3-lite

autosave:
  enabled: true
  on_task_complete: true
  on_remember_request: true
  session_summary: true
  summary_interval_messages: 20

startup:
  auto_load_pinned: true
  ask_load_previous_session: true
  include_group_shared_pins: false  # Groups are opt-in via --groups flag

expiration:
  enabled: false
  default_days: 90
  categories:
    task_history: 30
    session_summary: 60

relevance:
  search_limit: 5
  include_global: true
```

## Embedding Providers

### Vertex AI (for OpenCode)

Requires Google Cloud credentials:

```bash
gcloud auth application-default login
agent-memory config set semantic.provider=vertex
agent-memory config set semantic.vertex.project_id=your-project
```

### Voyage AI (for Claude Code)

Voyage AI is recommended by Anthropic for embeddings:

```bash
export VOYAGE_API_KEY=your-api-key
agent-memory config set semantic.provider=claude
```

## Integration

The install script will prompt you to automatically install integrations. Each integration includes two parts:

1. **Rules** (auto-loaded) - Core behaviors that run every session (startup, auto-save, session end)
2. **Skill** (on-demand) - Full command reference documentation

### OpenCode

```bash
# Rules (auto-loaded every session)
mkdir -p ~/.config/opencode/rules
cp integrations/opencode/rules/agent-memory.md ~/.config/opencode/rules/

# Skill (on-demand, load with /skill agent-memory)
mkdir -p ~/.config/opencode/skills/agent-memory
cp integrations/opencode/skills/agent-memory/SKILL.md ~/.config/opencode/skills/agent-memory/
```

The rules ensure the agent automatically:
- Loads pinned memories at session start
- Saves learnings during work
- Summarizes sessions before ending

Load the full skill with `/skill agent-memory` for detailed command reference.

### Claude Code

```bash
# Rules (auto-loaded every session)
mkdir -p ~/.claude/rules
cp integrations/claude-code/rules/agent-memory.md ~/.claude/rules/

# Skill (on-demand, load with /agent-memory)
mkdir -p ~/.claude/skills/agent-memory
cp integrations/claude-code/skills/agent-memory/SKILL.md ~/.claude/skills/agent-memory/
```

The rules ensure the agent automatically:
- Loads pinned memories at session start
- Saves learnings during work
- Summarizes sessions before ending

Load the full skill with `/agent-memory` for detailed command reference.

## Storage Layout

```
~/.agent-memory/
├── config.yaml           # Configuration
├── groups.yaml           # Workspace group definitions
├── global/
│   ├── memories.db       # Global SQLite database
│   ├── vectors/          # Global LanceDB vectors
│   └── summaries/        # Global session data
└── projects/
    └── <project-hash>/
        ├── memories.db   # Project SQLite database
        ├── vectors/      # Project LanceDB vectors
        └── summaries/    # Project session data
```

## Development

```bash
# Install with dev dependencies
./install.sh --dev

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Memory System                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  CLI (Click)  ──▶  Core Logic  ──▶  Storage                 │
│                         │              │                     │
│  OpenCode     ──▶  Embeddings        SQLite (metadata)      │
│  Skill               │              │                       │
│                   Vertex AI /       LanceDB (vectors)       │
│  Claude Code     Voyage AI                                  │
│  CLAUDE.md                                                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## License

MIT
