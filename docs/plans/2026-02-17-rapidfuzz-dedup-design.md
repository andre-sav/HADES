# Rapidfuzz Fuzzy Matching for Cross-Workflow Dedup

**Date:** 2026-02-17
**Bead:** HADES-1wk
**Story:** 2.6 — Cross-Workflow Deduplication

## Problem

`dedup.py` uses exact normalized string matching via `get_dedup_key()`. After suffix-stripping and punctuation removal, "Acme Inc" and "ACME Corporation" match. But typos ("Acmee Services"), abbreviations ("St Joseph" vs "Saint Joseph"), and word reordering won't match. This causes duplicate leads across Intent and Geography exports.

## Design

### Algorithm

`rapidfuzz.fuzz.token_sort_ratio` — sorts words alphabetically before comparing, handling word reorder and typos. Runs after existing `normalize_company_name()` (suffix strip, lowercase, punctuation removal).

### Threshold

Default **85**, configurable in `icp.yaml` at `dedup.fuzzy_threshold`. After normalization already strips "Inc/LLC/Corp", 85 catches typos and abbreviations without false-matching genuinely different companies.

### Two-Tier Matching

- **Tier 1 (exact)**: Same normalized phone + same normalized company → definite duplicate (current behavior, unchanged)
- **Tier 2 (fuzzy)**: Same normalized phone + fuzzy company ≥ threshold → probable duplicate
- **Tier 3 (fuzzy, no phone)**: No phone overlap but fuzzy company ≥ threshold → possible duplicate (flagged but not auto-excluded)

### Scope

Fuzzy matching applies **only to cross-workflow functions**: `find_duplicates()`, `merge_lead_lists()`, `flag_duplicates_in_list()`. Within-workflow dedup (`dedupe_leads()`, `dedupe_by_phone()`) stays exact match — ZoomInfo returns consistent names within a single search.

### Performance

rapidfuzz is C-optimized. With <200 leads per workflow, O(n×m) comparison is <1ms.

## Files Changed

| File | Change |
|---|---|
| `dedup.py` | Add `fuzzy_company_match()`, update `find_duplicates()`, `merge_lead_lists()`, `flag_duplicates_in_list()` |
| `config/icp.yaml` | Add `dedup.fuzzy_threshold: 85` |
| `tests/test_dedup.py` | Fuzzy matching tests (typos, abbreviations, word reorder, below-threshold) |
| `requirements.txt` | Add `rapidfuzz>=3.0` |

## What Stays the Same

- `dedupe_leads()`, `dedupe_by_phone()` — within-workflow, exact match only
- `normalize_company_name()` — unchanged, first pass before fuzzy
- `get_dedup_key()` — unchanged, still used for exact matching
- UI in `pages/4_CSV_Export.py` — already shows cross-workflow duplicates
