# Agent Memory

You have access to long-term memory via the `agent-memory` CLI. Use it to persist learnings, decisions, and context across sessions.

## Session Start (ALWAYS DO THIS)

At the beginning of EVERY session, run:

```bash
agent-memory startup --json
```

This loads pinned memories (critical context) and offers to restore previous session context.

## Auto-Save Triggers

Save memories automatically when:

1. **Completing a significant task** - Record what was done and key learnings
2. **User says "remember this"** - Save the referenced information
3. **Learning something important** - Architecture decisions, patterns, user preferences

```bash
# Save a factual learning
agent-memory save "The billing service uses Stripe webhooks at /api/webhooks/stripe"

# Save a user decision/preference
agent-memory save --category=decision "User prefers functional components over classes"

# Pin critical information (always loaded at startup)
agent-memory save --pin "CRITICAL: Never modify the legacy auth module directly"
```

## Session End

Before ending a session, summarize the work accomplished:

```bash
agent-memory session summarize "Brief summary of what was done and key decisions made"
```

## Search Before Asking

Before asking the user about something, check if you have relevant memories:

```bash
agent-memory search "topic to search for"
```

## Full Documentation

For complete command reference and advanced usage, load the skill: `/skill agent-memory`
