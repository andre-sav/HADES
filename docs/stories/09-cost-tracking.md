# Story 9: Cost Tracking and Budget Controls

## Description
As a user, I need credit usage tracked and budget caps enforced so that I don't accidentally overspend on ZoomInfo API credits.

## Acceptance Criteria
- [x] Log every query: timestamp, workflow type, credits used, leads returned
- [x] Display estimated credit cost before query execution
- [x] Intent workflow weekly cap: 500 credits
- [x] Block query if cap would be exceeded
- [x] Budget alerts at 50%, 80%, 95% thresholds
- [x] Show current usage vs remaining budget

## Technical Notes
- Module: `cost_tracker.py`
- Usage stored in Turso `credit_usage` table
- Budget caps configured in `config/icp.yaml`
- 1 credit = 1 lead returned

## Dependencies
- Story 1 (Turso)
- Story 3 (ICP config for budget caps)

## Files to Create/Modify
- `cost_tracker.py`
