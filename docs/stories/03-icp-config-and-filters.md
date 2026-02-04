# Story 3: ICP Configuration and Filters

## Description
As a user, I need ICP filters (employee count, SIC codes) loaded from a config file so that all API queries automatically apply the correct filtering criteria without code changes.

## Acceptance Criteria
- [x] YAML config file created with ICP filters
- [x] Config includes: employee minimum (50), SIC code whitelist
- [x] Config includes: scoring weights for both workflows
- [x] Config includes: intent freshness tiers
- [x] Config includes: budget caps (500/week for Intent)
- [x] Config loader function implemented
- [x] Filters accessible throughout the application

## Technical Notes
- Config file: `config/icp.yaml`
- Schema defined in `docs/architecture.md` section 4.3.1
- Use PyYAML for parsing

## Dependencies
None

## Files to Create/Modify
- `config/icp.yaml`
- `utils.py` (config loader function)
