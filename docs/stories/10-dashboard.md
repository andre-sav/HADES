# Story 10: Usage Dashboard and Executive Summary

## Description
As a user, I need dashboards showing credit usage, query history, and pipeline health so that I can monitor costs and system status at a glance.

## Acceptance Criteria
- [x] Usage Dashboard page with:
  - Credits used this week (by workflow)
  - Credits remaining (Intent cap)
  - Queries run this week
  - Leads exported this week
  - Filterable by date range
- [x] Executive Summary page with:
  - Total credits used (month-to-date)
  - Total leads exported (month-to-date)
  - Cost per lead
  - Weekly trend chart
- [x] Pipeline health indicators (last query, API status, errors)

## Technical Notes
- Pages: `pages/5_Usage_Dashboard.py`, `pages/6_Executive_Summary.py`
- Data from Turso `credit_usage` and `query_history` tables
- Use Streamlit charts for visualizations

## Dependencies
- Story 1 (Turso)
- Story 9 (Cost tracking)

## Files to Create/Modify
- `pages/4_Usage_Dashboard.py`
- `pages/5_Executive_Summary.py`
