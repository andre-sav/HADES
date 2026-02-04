# Story 2: ZoomInfo API Client

## Description
As a developer, I need a ZoomInfo API client that handles OAuth authentication and provides methods for Intent and Company Search queries so that the application can fetch leads from ZoomInfo.

## Acceptance Criteria
- [x] OAuth authentication with token refresh
- [x] Intent API query method with pagination
- [x] Company Search API query method with pagination
- [x] Rate limiting and retry logic
- [x] Error handling with user-friendly messages
- [x] Credentials loaded from Streamlit secrets

## Technical Notes
- Base URL: `https://api.zoominfo.com`
- Token should be cached and refreshed when expired
- Include exponential backoff for retries

## Dependencies
- Story 1 (for secrets pattern)

## Files to Create/Modify
- `zoominfo_client.py`
