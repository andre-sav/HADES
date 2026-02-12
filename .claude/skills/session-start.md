# Session Start Protocol

Execute the full session start protocol. Do all steps — do not skip any.

## Steps

1. **Recover context** — Run `bd prime` to load beads context.

2. **Check for active work** — Run `bd list --status=in_progress` to see if anything was left in progress from a prior session.

3. **Find available work** — Run `bd ready` to see unblocked tasks.

4. **Read handoff notes** — Read `docs/SESSION_HANDOFF.md` to understand what happened last session, what's working, known issues, and next steps.

5. **Report** — Show a brief summary: active work, available tasks, and key context from the handoff doc. Ask what the user wants to tackle.
