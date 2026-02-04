# Story 8: CSV Export with Operator Metadata

## Description
As a user, I need to export leads as a CSV file in VanillaSoft format with operator metadata so that I can import directly into VanillaSoft without manual data cleanup.

## Acceptance Criteria
- [x] CSV matches VanillaSoft template columns exactly
- [x] Operator selection dropdown before export
- [x] All operator fields populated (business name, phone, email, zip, website, team)
- [x] Lead source tag included
- [x] Intent score and age included (for Intent workflow)
- [x] File named with timestamp and workflow type
- [x] Download via browser

## Technical Notes
- Module: `export.py`
- Column list in PRD Appendix A
- Operators stored in Turso `operators` table

## Dependencies
- Story 1 (Turso - for operators table)
- Story 4 or 6 (workflow pages to trigger export)

## Files to Create/Modify
- `export.py`
- `pages/3_Operators.py` (CRUD for operator management)
- `pages/4_CSV_Export.py` (export page with operator selection)
