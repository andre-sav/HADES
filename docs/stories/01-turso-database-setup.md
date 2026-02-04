# Story 1: Turso Database Setup

## Description
As a developer, I need to set up the Turso database connection and schema so that the application has persistent storage for operators, cached leads, credit usage, and query history.

## Acceptance Criteria
- [ ] Turso database created with auth token
- [x] Database connection module (`turso_db.py`) implemented
- [x] All tables created: `operators`, `zoominfo_cache`, `credit_usage`, `location_templates`, `query_history`
- [x] Connection uses Streamlit secrets for credentials
- [x] Basic CRUD operations working

## Technical Notes
- Use `libsql-experimental` package for Turso connection
- Cache database connection with `@st.cache_resource`
- Schema defined in `docs/architecture.md` section 4.1.2

## Dependencies
None - this is foundational

## Files to Create/Modify
- `turso_db.py`
- `.streamlit/secrets.toml` (template)
