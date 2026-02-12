# Session Close Protocol

Execute the full session close protocol. Do all steps — do not skip any.

## Steps

1. **Sync beads** — Run `bd sync --flush-only` to export beads to JSONL.

2. **Check git status** — Run `git status` and `git diff --stat HEAD` to identify uncommitted changes.

3. **Gather session context** — Review what was accomplished this session:
   - What tasks were worked on (check beads in_progress and recently closed)
   - What files were modified
   - What's still in progress or unfinished
   - Any bugs discovered or known issues encountered

4. **Update SESSION_HANDOFF.md** — Update `docs/SESSION_HANDOFF.md` with:
   - New session summary section at top of session summaries (date + session number)
   - What was done (bullet points of accomplishments)
   - Key files modified
   - Any uncommitted changes and why
   - Known issues discovered
   - Next steps (priority ordered)
   - Updated beads status section
   - Updated test count if tests were added/removed

5. **Report** — Show a brief summary of what was recorded.
