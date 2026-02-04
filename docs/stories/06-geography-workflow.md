# Story 6: Geography Workflow

## Description
As a user, I need a Geography Workflow page where I can query ZoomInfo for companies by zip code and radius, preview scored results, and export to CSV.

## Acceptance Criteria
- [x] Streamlit page with query builder UI
- [x] Single or multi-zip input (comma-separated)
- [x] Radius selection (10, 25, 50, 100 miles)
- [x] Query preview with estimated credit cost
- [x] Confirmation dialog before execution
- [x] Results displayed in sortable table
- [x] Multi-zip deduplication (same company near multiple zips)
- [x] Lead source tag format: `ZoomInfo Geo - [Zip] - [Radius]mi`

## Technical Notes
- Page: `pages/2_Geography_Workflow.py`
- Must apply ICP filters from config
- Handle API multi-zip support (or loop if needed)

## Dependencies
- Story 2 (ZoomInfo client)
- Story 3 (ICP config)
- Story 5 (Scoring engine)

## Files to Create/Modify
- `pages/2_Geography_Workflow.py`
