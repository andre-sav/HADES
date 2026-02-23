# Intent Pipeline Yield Expansion

**Date:** 2026-02-23
**Status:** Approved

## Problem

The intent pipeline returns 25 total results per run (ZoomInfo's entire matching pool for 2 topics). After freshness filtering, 0-8 survive. After dedup and contact resolution, 0-3 leads export. The pipeline averages ~2 leads/week.

Additionally, the pipeline fails at Step 4 (contact search) due to `excludeOrgExportedContacts` being an invalid ZoomInfo API field (400 error since 2026-02-23).

## Funnel Analysis (6 runs, Feb 17-23)

```
Intent Results → Scored → Dedup → Selected → Contacts → Enriched → Exported
     25           0-8      0-2      0-8        0-25       0-3        0-3
```

Drop-off points:
1. **Freshness filter** kills most leads (>14 days = score 0, excluded)
2. **Company ID resolution** is lossy (hashed → numeric via enrich)
3. **Contact search → Enrich** has a massive funnel drop

## Changes

### 1. Expand automation topics

Add expansion topics to the automation config. Companies researching coffee services or water coolers are adjacent buyers for vending.

```yaml
automation:
  intent:
    topics: ["Vending Machines", "Breakroom Solutions", "Coffee Services", "Water Coolers"]
```

### 2. Increase Intent page size

`IntentQueryParams.page_size`: 25 → 100. Reduces API round-trips when the pool grows beyond 25 results. Geography and Contact search already use 100.

### 3. Fix excludeOrgExportedContacts 400 error

Remove the invalid field from the Contact Search request body. ZoomInfo's `/search/contact` endpoint does not accept this parameter. HADES uses its own cross-session dedup via `export_dedup.py`.

## What doesn't change

- Scoring weights, freshness thresholds, dedup logic
- Automation schedule (Mon-Fri 7 AM ET)
- Manual Intent Workflow UI (topics selected interactively)

## Expected impact

- **Immediate:** Pipeline stops failing (fix #3)
- **Short-term:** Larger intent pool → more leads surviving the scoring funnel
- **Measurable after 1 week:** Compare intent results count and leads exported vs. the 25/2-3 baseline

## Files changed

| File | Change |
|------|--------|
| `config/icp.yaml` | Add 2 topics to `automation.intent.topics` |
| `zoominfo_client.py` | `IntentQueryParams.page_size` 25→100, remove `excludeOrgExportedContacts` |
| `tests/test_zoominfo_client.py` | Update exclude test, rpp assertion |
| `tests/test_run_intent_pipeline.py` | Update automation config assertion |
| `CLAUDE.md` | Clarify `exclude_org_exported` is cache-key only |
