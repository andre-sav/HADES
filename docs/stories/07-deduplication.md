# Story 7: Deduplication

## Description
As a user, I need duplicate leads removed so that the call center doesn't waste time calling the same company multiple times.

## Acceptance Criteria
- [x] Phone number normalization (strip extensions, format consistently)
- [x] Remove duplicate phone numbers within result set
- [x] Cross-workflow deduplication (Intent vs Geography)
- [x] Keep higher-scored version when duplicate found
- [x] Show count of removed duplicates
- [x] Flag duplicates in preview table

## Technical Notes
- Module: `dedup.py`
- Match on: normalized phone + fuzzy company name
- Reuse phone cleaning logic from VSDP if available

## Dependencies
- Story 5 (Scoring - to determine which duplicate to keep)

## Files to Create/Modify
- `dedup.py`
- `utils.py` (phone normalization functions)
