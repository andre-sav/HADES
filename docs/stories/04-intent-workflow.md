# Story 4: Intent Workflow

## Description
As a user, I need an Intent Workflow page where I can query ZoomInfo for companies showing intent signals for "Vending" topics, preview scored results, and export to CSV.

## Acceptance Criteria
- [x] Streamlit page with query builder UI
- [x] Intent topic selection (default: "Vending")
- [x] Signal strength filter (High/Medium/Low)
- [x] Query preview with estimated credit cost
- [x] Confirmation dialog before execution
- [x] Results displayed in sortable table
- [x] Lead source tag format: `ZoomInfo Intent - [Topic] - [Score] - [Age]d`

## Technical Notes
- Page: `pages/1_Intent_Workflow.py`
- Must apply ICP filters from config
- Exclude leads older than 14 days

## Dependencies
- Story 2 (ZoomInfo client)
- Story 3 (ICP config)
- Story 5 (Scoring engine)

## Files to Create/Modify
- `pages/1_Intent_Workflow.py`
