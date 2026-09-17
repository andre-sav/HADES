# Agent Instructions

<!-- multi-session:begin rules_version=2026-09-18.3 — managed block; edit the template in Recursive-Improvement, not here -->
## Multi-session rules — READ FIRST

Several agent sessions share this repo at once. The project's deltas, and **what is live today versus pending**,
are in [`SESSION_START.md`](./SESSION_START.md). The generic rules are in
`~/Projects/Recursive-Improvement/docs/multi-session/RULES.md`. If you read nothing else, these five hold:

1. **Your role is your checkout.** Compare `git rev-parse --path-format=absolute --git-dir` with
   `git rev-parse --path-format=absolute --git-common-dir`.
   You are the **DIRECTOR** only if they are the same string **and** `.beads/embeddeddolt` exists at the top of this checkout:
   run `/session-start`. If they differ you are in a linked worktree; and in any repo you cloned yourself the marker
   is absent. Either way you are a **LANE**: run `/lane-start`.
2. **A lane writes only its own worktree, branch and PR.** Worktrees live under `/Users/boss/Projects/HADES-worktrees/<work id>-<short stamp>`,
   cut from `origin/main` with `--no-track`, never under `/tmp`. A lane never edits, stages, commits or
   switches branches in the primary checkout, never runs `/session-start` or `/session-close`, and ends with `/lane-close`.
3. **Tracker.** Every `bd` call is `/Users/boss/.local/bin/bd` written out and carries `--actor <your session name>`; an exported `BEADS_ACTOR` does not survive between tool calls. A lane may run `bd create`, `bd remember` with a **new key only**, any read, and one state write: `bd update <id> --claim` on the item it is taking. Every other `bd update`, and `bd close`, `bd reopen`, `bd import`, `bd dolt`, belong to the director. `.beads/issues.jsonl` is generated: never hand-edit it, never hand-merge it, and a lane never commits it. If this file also has a bd-managed `BEADS INTEGRATION` block whose Session Completion tells you to close issues and push: these rules win. A lane pushes only its own branch and closes no item; bd owns that text and rewrites it.
4. **Nothing shared rides a code PR**: `SESSION_START.md`, nor the tracker export. The director lands those. On seeing a PR, worktree, work item
   or red CI run that is not yours: report it in one line and act on nothing.
5. **`main` moves by PR.** Merges, pushes to it, deploys, settings changes and live DDL stay with the
   operator, per named PR, asked in chat. This project declares no review-receipt rule.
<!-- multi-session:end -->

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
```

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
