# Story 5: Lead Scoring Engine

## Description
As a user, I need leads to be scored based on configurable weights so that I can prioritize the highest-quality leads for calling.

## Acceptance Criteria
- [x] Intent scoring: signal strength (50%), on-site likelihood (25%), freshness (25%)
- [x] Geography scoring: proximity (50%), on-site likelihood (30%), employee scale (20%)
- [x] Composite score 0-100 for each lead
- [x] Freshness tiers: Hot (0-3d), Warm (4-7d), Cooling (8-14d), Stale (15+d excluded)
- [x] On-site likelihood based on SIC code mapping
- [x] Weights loaded from config file

## Technical Notes
- Module: `scoring.py`
- Scoring weights in `config/icp.yaml`
- On-site likelihood: High SICs=100%, Medium=70%, Low=40%

## Dependencies
- Story 3 (ICP config)

## Files to Create/Modify
- `scoring.py`
