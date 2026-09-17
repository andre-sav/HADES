# Session start — ms addendum

<!-- multi-session:status rules_version=2026-09-18.2 -->
## Multi-session rules: what is live here today

Generic rules: `~/Projects/Recursive-Improvement/docs/multi-session/RULES.md`, version 2026-09-18.2.
Project facts: `.claude/multi-session.json`. Lanes run `/lane-start` and `/lane-close`.
If you read nothing else: **your role is your checkout, a lane writes only its own worktree and PR, and nothing
shared rides a code PR.**

**Live now, as convention:** U1 to U11, and T1 to T7 for the tracker.

**Mechanisms this project has:**
- none

**Mechanisms this project does not have. Do not act as if they exist:**
- a push guard for stranded tracker writes: nothing stops a push that leaves bead writes behind; the director lands the export by hand
- a close-runner config: `/session-close` runs by hand here
- a CI guard on shared paths: rule U4 binds only sessions that read it, and a cloud or Codex clone is bound by nothing
- a director lock: two sessions in the primary checkout can both believe they are the director; say who you are in your first report
- publish from a close worktree: a close still moves the primary checkout's HEAD

**Director today:** the session in the primary checkout that ran `/session-start` first. It says so in its first
report. A second session in the primary checkout that finds a director named is a lane and works from a worktree.

**Reaching the director:** a comment on your PR naming the head SHA; the director reads open PRs at its next start
<!-- multi-session:status-end -->
