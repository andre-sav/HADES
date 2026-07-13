# HADES Hardening Protocol — recursive root-cause self-prompt

> **How to run me.** Paste the block under "THE PROMPT" into a fresh Claude Code
> session in this repo (or run via `/loop` for autonomous iteration). I am
> self-contained: I rebuild my own context from this file, `HARDENING_LEDGER.md`,
> and beads epic **HADES-zz6** every iteration, so I survive compaction and
> session boundaries. One iteration = one boundary audited to completion.

---

## Why this exists (read once, then it's in the ledger)

On 2026-06-15 the primary operator (Mike) pulled a Geography list and got 28
blank rows, every one scoring an identical 64%. Root cause: ZoomInfo enrichment
returned matched-but-fieldless records; HADES scored them at the empty-lead
baseline and **presented them as valid leads**. See
`docs/INCIDENT-2026-06-15-blank-enrichment.md`.

That bug was not special. It is one instance of a **class**:

> **HADES silently turns a degraded input into authoritative-looking output.**

The git history already contains a "silent-failure audit — 24 fixes across 9
files." The class keeps recurring because fixes were applied instance-by-instance
with no durable, recursive sweep and no convention that prevents reintroduction.
This protocol exists to kill the *class*, on every boundary, and leave behind
guards + conventions so it cannot silently return.

**Stakes:** this is the business's lead engine. A silent failure here ships bad
data to callers and burns trust (and budget). Fail **loud**, never silent.

---

## THE PROMPT

```
You are hardening HADES against silent failures. This is a recursive, multi-pass
campaign. Read docs/HARDENING_PROTOCOL.md (this file), docs/HARDENING_LEDGER.md,
and `bd show HADES-zz6` before doing anything — they are your durable memory.

MISSION
Eliminate the CLASS of failures where HADES presents degenerate, empty, partial,
stale, or wrong output as if it were valid — or lets an external dependency
degrade without surfacing it. Fix classes, not instances. Leave guards and
conventions behind so the class cannot silently return.

NON-NEGOTIABLE RULES
1. True root cause first. Use the systematic-debugging skill. No fix before you
   can state WHAT breaks and WHY, traced to origin. Symptom patches are failures.
2. TDD always. Every fix gets a FORCE-FAIL test FIRST: feed the BAD input
   (empty/partial/malformed/error-but-200/stale) and assert HADES rejects or
   surfaces it. A happy-path test that proves "doesn't crash" is NOT acceptance —
   it must prove the bad case is caught. Watch it fail (RED) before you fix.
3. Fail loud, degrade gracefully. At every boundary: validate CONTENT not just
   the container; surface the problem to the operator with an actionable message;
   where possible fall back to lower-confidence-but-real data (like search-phase
   backfill) instead of blanks. Never let empty/degenerate output reach display,
   export, or push.
4. Do not break working behavior. Run the full suite (`pytest -q`) after each
   fix; it must stay green. Run ruff on touched files; do not "fix" pre-existing
   lint outside your change.
5. Stay in your lane. Do NOT draft business/marketing/legal copy. Do NOT guess at
   external account state (credits, entitlements, API keys) — when a finding's
   true cause is operational (e.g. "ZoomInfo credits lapsed"), flag it for a human
   via `bd human` / escalation, don't paper over it.
6. Git hygiene: work on a branch (never commit to main directly). Reference past
   commits by TITLE, not SHA.

THE RECURSIVE LOOP (one boundary per iteration)
Maintain durable state in docs/HARDENING_LEDGER.md and under epic HADES-zz6.

  STEP 1 — ORIENT. Read the ledger. Pick the highest-risk surface NOT yet marked
  DONE in the inventory below (or one newly discovered). State which and why.

  STEP 2 — ENUMERATE FAILURE MODES. For the chosen surface, list every way its
  input/dependency can degrade:
    - returns 200 but empty / fieldless (the enrichment bug)
    - returns partial (some records good, some empty)
    - returns malformed / schema-changed / renamed fields
    - returns an error envelope the code treats as data
    - returns stale / cached data presented as fresh
    - auth/token/quota/entitlement degraded (works for X, silently not for Y)
    - swallowed exception -> empty list/dict indistinguishable from "no results"
    - default values that make degenerate input look valid (e.g. distance=15,
      employees=50 -> constant baseline score; the "uniform 64" smell)
    - Streamlit rerun wiping state mid-flow (a known recurring HADES class)
    - counts/metrics that count containers, not validated content

  STEP 3 — DETECT & TRIAGE. For each mode, READ THE CODE and determine: is it
  currently SILENT (produces plausible-but-wrong output / no signal), LOUD
  (already raises/warns), or N/A (cannot occur). Verify by reading, not assuming.
  Detection heuristics to grep/scan for at this surface:
    - `except` blocks that `pass` / `return []` / `return {}` / log-and-continue
    - `.get(key, default)` on fields that are load-bearing downstream
    - parsing that ignores `matchStatus` / `success` / `error` / `noMatch`
    - functions whose empty-on-error return is indistinguishable from empty-on-success
    - output handed to display/export/push without an invariant check

  STEP 4 — ROOT CAUSE (recurse with 5 Whys). For each CONFIRMED silent mode, ask
  "why does this exist / why wasn't it caught" until you reach a SYSTEMIC answer
  (e.g. "no convention requires boundary content-validation"). Capture the class.

  STEP 5 — HARDEN (TDD). For each confirmed mode worth fixing:
    a. Write the force-fail test (RED). Run it; confirm it fails for the right reason.
    b. Minimal fix: validate content + fail loud + graceful fallback (GREEN).
    c. Run full suite; stay green. Ruff touched files.
    d. Create a child bead under HADES-zz6 (or close if trivial+done) and record
       the fix + test names.

  STEP 6 — PREVENT THE CLASS. If this mode reveals a class with siblings elsewhere,
  either (a) propose/add a reusable guard helper + a CONVENTION line in the ledger,
  and (b) note the sibling surfaces to sweep. A class fixed once should be greppable
  everywhere.

  STEP 7 — LEDGER. Update docs/HARDENING_LEDGER.md: mark the surface DONE with a
  one-line summary of modes found, fixed, and RULED OUT (so future passes don't
  redo it). List newly-discovered surfaces. Commit the branch.

  STEP 8 — RE-PRIORITIZE & LOOP. Return to STEP 1. 
  STOP CONDITIONS (whichever first):
    - 2 consecutive surfaces yield zero new silent-failure modes (loop-until-dry), OR
    - the inventory is fully DONE, OR
    - a token/turn budget you were given is exhausted.
  On stop: write a SUMMARY section to the ledger (surfaces audited, modes fixed,
  conventions added, sibling sweeps remaining, anything escalated to humans) and
  run the bmad-code-review skill over the full branch diff. Report and ask before
  merging to main.

PRIORITIZED INVENTORY (seed — extend as you discover; mark DONE in the ledger)
  P0 external boundaries (untrusted responses presented as truth):
    1. ZoomInfo Contact Enrich        -> DONE (HADES-mcx: stamp pid + fail-loud)
    2. ZoomInfo Contact/Company Search (preview the operator trusts)
    3. ZoomInfo Company Enrich        (silent merge gaps -> SIC/industry blanks)
    4. ZoomInfo Intent pipeline       (headless; failures must alert, not vanish)
    5. ZoomInfo auth/token + usage    (degraded entitlement that works partially)
    6. VanillaSoft push               (claims success on partial/failed push?)
    7. Zoho client / sync / auth
    8. DB layer (Turso/libsql)        (empty read vs error read; stale cache)
  P1 internal degenerate-data transforms:
    9. Scoring                        (constant/baseline scores from empty inputs,
                                       anywhere besides geography; the "uniform" smell)
   10. Export / CSV                   (silent column drops, encoding, truncation)
   11. Cost tracker / usage logging   (counts containers not validated leads)
   12. Streamlit rerun state loss     (mid-flow state wiped -> wrong/blank output)
   13. Dedup / merge                  (over-merge or drop without signal)
   14. Calibration                    (silently trains on degenerate data)

OUTPUT EACH ITERATION (concise — this is data, not prose):
  - Surface audited + why chosen
  - Failure modes: found / ruled-out (with one-line evidence each)
  - Root-cause class (5-whys endpoint)
  - Fix(es) + force-fail test name(s) + suite status
  - Convention/guard added (if any) + sibling surfaces to sweep
  - Next surface + whether a stop condition is near
  - Anything escalated to a human (operational/account issues)
```

---

## Invocation options

- **One pass, supervised:** paste THE PROMPT; I do one boundary, report, you steer.
- **Autonomous sweep:** `/loop <THE PROMPT>` (self-paced) — I iterate until a stop
  condition, updating the ledger and beads each pass. Give me a token budget if you
  want a hard ceiling.
- **Heavy parallel audit:** ask for a workflow (`ultracode` / "use a workflow") and
  I'll fan out one auditor agent per boundary, adversarially verify findings, then
  pipeline force-fail-test + fix per confirmed mode.

## Definition of done for the campaign
Every P0/P1 surface marked DONE in the ledger; each confirmed silent mode has a
force-fail regression test; reusable guards + conventions documented; remaining
work is either scheduled child beads or escalations to a human — nothing silent
left in the dark.
