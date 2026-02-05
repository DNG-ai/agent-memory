# Agent Memory

Long-term memory store for AI agents. Enables agents (OpenCode, Claude Code) to save, search, and manage persistent memories across sessions.

## Features

- **Persistent Memory** - Save learnings, decisions, and context that persist across sessions
- **Semantic Search** - Find relevant memories using vector similarity (via Vertex AI or Voyage AI)
- **Session Management** - Track sessions and create summaries
- **Multi-scope** - Project-specific and global memories
- **Pinned Memories** - Mark critical information to always load at startup
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

### Other Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize memory for current project |
| `startup` | Get startup context for agents |
| `export` | Export memories to file |
| `cleanup` | Remove expired memories |

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

### OpenCode

Copy the skill to your OpenCode skills directory:

```bash
cp -r integrations/opencode ~/.config/opencode/skills/agent-memory
```

Then load it with `/skill agent-memory` or it will auto-load when relevant.

### Claude Code

Add the CLAUDE.md content to your project's CLAUDE.md file:

```bash
cat integrations/claude-code/CLAUDE.md >> /path/to/project/CLAUDE.md
```

## Storage Layout

```
~/.agent-memory/
├── config.yaml           # Configuration
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
