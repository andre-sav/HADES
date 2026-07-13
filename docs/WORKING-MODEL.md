# HADES Working Model — how to run agent-assisted work on this tool

> Operating rules for any Claude Code instance working on HADES. HADES is a
> **single production lead-generation tool with one primary operator** — it
> pushes contacts to live dialers, so the blast radius of a bad change is high.
> The whole point of these rules is: **never let work that only *looks* done ship
> unverified.** That is the failure mode the 2026-06-15 blank-enrichment incident
> was made of.

---

## The three ways to split work (don't conflate them)

| Layer | Mechanism | Isolation | Use for |
|---|---|---|---|
| **Subagents** (in-session) | Agents spawned inside one conversation; they report back, the parent keeps the conclusion | Share the session goal, not the context window | Fan-out reads, parallel review, research — bounded "return this" tasks |
| **Separate instances** | Independent Claude Code sessions (separate terminals, or a spun-off session + git worktree) | Full context **and** working-tree isolation | Genuinely independent workstreams that should not share context |
| **Background / scheduled** | `/loop` (recurring in-session), background runs, or scheduled cloud agents (cron) | Runs without a human watching | Polling, recurring maintenance, monitoring |

**Instances don't share memory — so the durable artifact IS the coordination
channel.** On HADES that channel is: **beads** (the resume/handoff anchor) +
**the branch** (in-flight code) + **`docs/HARDENING_LEDGER.md`** (what's audited
/ ruled out / deferred). A fresh instance reads the anchor bead and resumes with
zero dependence on a prior conversation. This is the contract — keep it current.

## The trade-off that governs every "should I parallelize?" decision

Parallelism buys wall-clock speed; it costs **coordination + verification**.
Break-even depends on three things — all three must hold to parallelize:

1. **Truly independent tasks.** Overlapping file edits → merge conflicts. Use
   worktree isolation if parallel agents must mutate files; otherwise serialize.
2. **Cheap, trustworthy verification.** An agent's output is only as good as the
   gate behind it. On HADES the gates are non-negotiable: **TDD, force-fail tests
   (feed the bad input, assert it's caught), the full suite green, and an
   adversarial review for anything non-trivial.**
3. **A stable, decomposable work-list.** Swarms shine over N known-independent
   items; they flail on open-ended "make it better."

## Swarms (many agents at once)

**Use them when** the work-list is decomposable and verifiable:
- N adversarial reviewers over one diff (this caught the phone-only-leads bug).
- One auditor per independent boundary, each returning a findings report to triage.
- Bulk migration across many call sites, worktree-isolated.

**Do not use them for** open-ended hardening with no test gate — that generates
plausible-but-unverifiable noise and churn. (A second-opinion review explicitly
flagged the open-ended 12-surface autonomous sweep as over-engineering for a tool
this size; that judgment stands.)

## Autonomy (leave agents running)

Autonomy **amplifies whatever discipline you've encoded.** With strong gates it's
a force multiplier; without them it's "confidently wrong at scale, unsupervised"
— the original incident's risk profile.

- **Safe:** narrow, deterministic, human-alerting jobs — e.g. the scheduled
  `scripts/check_zoominfo_health.py` credit/entitlement check. Bounded `/loop`
  with a hard token budget and an explicit stop rule.
- **Unsafe:** a long-lived agent with commit/push authority and no human review
  gate, especially near code that feeds dialers.

## The standing rules for HADES

1. **One instance at a time** for code changes. Resume from the beads anchor.
2. **Swarm only the bounded review step** (e.g. 3-layer adversarial review of a
   diff), not the implementation.
3. **Reserve full autonomy for monitoring**, never for code edits.
4. **Every fix: TDD + force-fail test + full suite green.** No exceptions for
   "small" changes — small changes caused this incident.
5. **Adversarial review before merge**, and a second-opinion model when the
   change is load-bearing or you're uncertain.
6. **Work on a branch, never commit to `main` directly.** Surface push/PR/merge
   as a human decision.
7. **Operational/account issues get escalated to a human, not papered over**
   (e.g. ZoomInfo credit/entitlement — the incident's actual trigger).
8. **No silent caps or swallowed errors.** Validate content, not just the
   container; fail loud, degrade gracefully (conventions C1–C6 in the ledger).

## Why human-paced is a feature here, not a bottleneck

For a single production tool with one operator, the constraint is **trust per
change**, not throughput. The discipline above is what makes each change safe to
push to a system that calls real people. Speed from autonomy is only worth it
where verification is cheap and blast radius is low — which on HADES is the
monitoring layer, and little else.
