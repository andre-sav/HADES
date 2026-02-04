# Product Requirements Document (PRD)
# ZoomInfo Intent & Geography Lead Pipeline

## Document Information
| Field | Value |
|-------|-------|
| Project Name | ZoomInfo Lead Pipeline |
| Version | 1.0 |
| Status | Draft |
| Created | 2026-01-27 |
| Owner | Andre (Data Engineering & Automation Specialist) |
| Sponsor | Damione (Head of Call Center) |

---

## 1. Introduction

### 1.1 Purpose
This document defines the product requirements for the ZoomInfo Intent & Geography Lead Pipeline—an automated system that extracts leads from ZoomInfo's API, applies ICP filters and scoring, and exports VanillaSoft-ready CSV files for the VendTech call center.

### 1.2 Background
VendTech currently uses ZoomInfo for lead acquisition through a manual process: apply firmographic filters in the ZoomInfo UI, export CSV, clean/transform data, upload to VanillaSoft. This process is slow, repetitive, and fails to leverage ZoomInfo's intent data—signals indicating when prospects are actively researching vending solutions.

Industry research shows that intent signals decay in days, not weeks, and first responders see 7x higher qualification rates. VendTech's competitors may already be acting on these signals faster.

### 1.3 Scope
**In Scope:**
- ZoomInfo API integration (Intent + Company Search endpoints)
- Two automated workflows (Intent-based, Geography-based)
- ICP filtering at API level
- Lead scoring and prioritization
- Deduplication
- CSV export in VanillaSoft format
- Cost tracking and budget controls
- Streamlit dashboard UI

**Out of Scope (Phase 2+):**
- Direct POST to VanillaSoft API
- VanillaSoft disposition sync
- Scheduled/automated query execution
- Conversion funnel tracking

---

## 2. Objectives & Success Metrics

### 2.1 Business Objectives
| Objective | Measurable Outcome |
|-----------|-------------------|
| Activate unused intent data | >0 leads sourced from intent workflow |
| Eliminate manual CSV exports | 100% of ZoomInfo leads via automated pipeline |
| Prove ZoomInfo ROI | Track cost-per-lead; conversion data (Phase 2) |
| Maintain same-day calling capability | Leads available in VanillaSoft within hours of query |

### 2.2 Success Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Intent leads per week | 50 | Dashboard counter |
| Intent leads per month | 200 | Dashboard counter |
| Intent conversion rate | ≥10% | Manual tracking → Phase 2 automation |
| Credit budget (Intent) | ≤500/week | Cost tracking dashboard |
| Manual export elimination | 100% | Process audit |

### 2.3 Failure Criteria
- Intent lead conversion rate below 10% (indicates poor ICP or intent topic fit)
- Credit overruns without corresponding lead quality
- Call center unable/unwilling to use exported data

---

## 3. User Personas

### 3.1 Andre (Builder/Operator)
**Role:** Data Engineering & Automation Specialist
**Goals:**
- Build and maintain the pipeline
- Run queries on behalf of Damione
- Monitor system health and costs
- Debug issues quickly

**Needs:**
- Full admin access to all features
- Clear error messages and logs
- Config-driven adjustments (no code changes for filters)
- Pipeline health visibility

**Frustrations:**
- Manual repetitive exports
- Lack of visibility into ZoomInfo intent data
- Time spent on data cleaning

### 3.2 Damione (Sponsor/Stakeholder)
**Role:** Head of Call Center
**Goals:**
- Get qualified leads to call center agents
- Prove ROI on ZoomInfo spend
- Request leads for specific territories on demand

**Needs:**
- Clear metrics on cost and volume
- Ability to request geography-based queries
- Confidence that leads meet ICP criteria

**Frustrations:**
- Not knowing if ZoomInfo is worth the cost
- Can't act on intent data
- Manual process is slow

### 3.3 Call Center Agents
**Role:** Outbound callers
**Goals:**
- Call qualified leads efficiently
- Understand why a lead is prioritized

**Needs:**
- Intent score and age visible in lead record
- Clear lead source identification
- Prioritized call queue

**Frustrations:**
- Calling unqualified leads
- No context on lead source or quality

### 3.4 Executives
**Role:** Oversight
**Goals:**
- Understand spend vs value
- High-level health check

**Needs:**
- Executive summary dashboard
- Cost-per-lead metrics
- Volume trends

---

## 4. Functional Requirements

### 4.1 Intent Workflow

#### FR-INT-001: Intent Query Builder
**Description:** User can construct a ZoomInfo Intent API query with configurable parameters.
**Inputs:**
- Intent topic (default: "Vending"; multi-select for stacking)
- Employee count minimum (default: 50)
- SIC code whitelist (from config)
- Intent signal strength filter (High/Medium/Low)
**Outputs:**
- Query preview with estimated credit cost
- Confirmation before execution

**Acceptance Criteria:**
- [ ] User can select one or more intent topics
- [ ] Hard filters (employee count, SIC) are applied at API level
- [ ] Cost estimate displayed before query execution
- [ ] User must confirm before credits are spent

#### FR-INT-002: Intent Lead Scoring
**Description:** Returned leads are scored based on weighted factors.
**Scoring Weights:**
| Factor | Weight | Scoring Logic |
|--------|--------|---------------|
| Intent signal strength | 50% | High=100, Medium=70, Low=40 |
| On-site presence likelihood | 25% | Based on industry code |
| Intent freshness | 25% | 0-3d=100%, 4-7d=70%, 8-14d=40%, 15+d=exclude |

**Acceptance Criteria:**
- [ ] Each lead has a composite score (0-100)
- [ ] Leads older than 14 days are excluded
- [ ] Score visible in preview and export

#### FR-INT-003: Intent Lead Source Tagging
**Description:** Each lead includes a source tag for VanillaSoft tracking.
**Format:** `ZoomInfo Intent - [Topic] - [Score] - [Age]d`
**Example:** `ZoomInfo Intent - Vending - 85 - 2d`

**Acceptance Criteria:**
- [ ] Lead source tag populated for every exported lead
- [ ] Tag includes topic, score, and age in days

---

### 4.2 Geography Workflow

#### FR-GEO-001: Geography Query Builder
**Description:** User can construct a ZoomInfo Company Search query by location.
**Inputs:**
- Zip code(s) (single or multi-zip batch)
- Radius (10, 25, 50, or 100 miles)
- Employee count minimum (default: 50)
- SIC code whitelist (from config)
**Outputs:**
- Query preview with estimated credit cost
- Confirmation before execution

**Acceptance Criteria:**
- [ ] User can enter single zip or comma-separated list
- [ ] Radius selection from predefined options
- [ ] Hard filters applied at API level
- [ ] Cost estimate displayed before execution

#### FR-GEO-002: Multi-Zip Batch Query
**Description:** User can input multiple zip codes and execute as a batch.
**Behavior:**
- If API supports multi-zip: single query
- If API requires single-zip: loop with aggregated results

**Acceptance Criteria:**
- [ ] User can paste list of zip codes
- [ ] Results aggregated across all zips
- [ ] Deduplication across zips (same company near multiple zips)

#### FR-GEO-003: Geography Lead Scoring
**Description:** Returned leads are scored based on weighted factors.
**Scoring Weights:**
| Factor | Weight | Scoring Logic |
|--------|--------|---------------|
| Proximity to target zip | 50% | Closer = higher score |
| On-site presence likelihood | 30% | Based on industry code |
| Employee count (above min) | 20% | 50-100=base, 100-500=boost, 500+=max |

**Acceptance Criteria:**
- [ ] Each lead has a composite score (0-100)
- [ ] Score visible in preview and export

#### FR-GEO-004: Saved Location Templates
**Description:** User can save and recall frequently used zip/radius combinations.
**Examples:**
- "Dallas Metro" → [75201, 75202, 75203] + 25mi
- "Bay Area" → [94102, 94103, 95110] + 50mi

**Acceptance Criteria:**
- [ ] User can save current query as named template
- [ ] User can load template to populate query builder
- [ ] Templates persist across sessions (stored in Turso)

#### FR-GEO-005: Geography Lead Source Tagging
**Description:** Each lead includes a source tag for VanillaSoft tracking.
**Format:** `ZoomInfo Geo - [Zip] - [Radius]mi`
**Example:** `ZoomInfo Geo - 75201 - 25mi`

**Acceptance Criteria:**
- [ ] Lead source tag populated for every exported lead
- [ ] For multi-zip, use primary/first zip in tag

---

### 4.3 Shared Pipeline Features

#### FR-PIP-001: ZoomInfo API Client
**Description:** Authenticated client for ZoomInfo API requests.
**Capabilities:**
- OAuth authentication
- Intent API queries
- Company Search API queries
- Pagination handling
- Rate limiting
- Error handling with retries

**Acceptance Criteria:**
- [ ] Successful authentication with stored credentials
- [ ] Handles pagination for large result sets
- [ ] Respects rate limits
- [ ] Graceful error handling with user feedback

#### FR-PIP-002: Hard ICP Filters
**Description:** Non-negotiable filters applied at API level.
**Filters:**
| Filter | Requirement | Applied At |
|--------|-------------|------------|
| Employee count | ≥50 | API query |
| SIC codes | Whitelist match | API query |

**Acceptance Criteria:**
- [ ] Filters sent with every API request
- [ ] No credits spent on leads outside ICP
- [ ] Filters loaded from config file

#### FR-PIP-003: Lead Caching
**Description:** Query results cached to avoid redundant API calls.
**Behavior:**
- Cache key: hash of query parameters
- TTL: 7 days
- Cache-first: check cache before API call
- Manual refresh: user can force fresh query

**Acceptance Criteria:**
- [ ] Cached results returned instantly
- [ ] Cache expires after 7 days
- [ ] User can bypass cache with "Refresh" option
- [ ] Cache stored in Turso

#### FR-PIP-004: Cross-Workflow Deduplication
**Description:** Prevent same company from appearing in both workflows.
**Logic:**
- Match on: normalized phone + fuzzy company name
- If duplicate: keep higher-scored version
- Flag duplicates in preview

**Acceptance Criteria:**
- [ ] Duplicates identified across workflows
- [ ] User sees duplicate flag in preview
- [ ] Only one version exported

#### FR-PIP-005: Phone Deduplication
**Description:** Remove duplicate phone numbers within a result set.
**Logic:**
- Normalize phone format
- Keep first occurrence
- Remove extensions before comparison

**Acceptance Criteria:**
- [ ] Extensions stripped (e.g., x123)
- [ ] Duplicates removed
- [ ] Count of removed duplicates shown

#### FR-PIP-006: CSV Export
**Description:** Export leads in VanillaSoft import format.
**Format:** CSV matching VanillaSoft template columns
**Includes:**
- All mapped lead fields
- Lead source tag
- Intent score and age (for Intent workflow)
- Operator metadata

**Acceptance Criteria:**
- [ ] CSV downloads via browser
- [ ] Columns match VanillaSoft template exactly
- [ ] File named with timestamp and workflow type

#### FR-PIP-007: Operator Metadata Injection
**Description:** Add operator information to each lead.
**Fields:**
- Vending Business Name
- Operator Name
- Operator Phone
- Operator Email
- Operator Zip
- Operator Website
- Team

**Acceptance Criteria:**
- [ ] Operator selected before export
- [ ] All operator fields populated in export
- [ ] Operators managed in Turso database

---

### 4.4 Cost Controls

#### FR-COST-001: Query Cost Preview
**Description:** Display estimated credit cost before execution.
**Calculation:** Estimated results × 1 credit per record
**Display:** "This query will use approximately X credits"

**Acceptance Criteria:**
- [ ] Estimate shown before confirmation
- [ ] User must acknowledge before proceeding

#### FR-COST-002: Credit Budget Caps
**Description:** Enforce weekly credit limits by workflow.
**Limits:**
| Workflow | Weekly Cap |
|----------|------------|
| Intent | 500 credits |
| Geography | Unlimited |

**Behavior:** Block query if cap would be exceeded

**Acceptance Criteria:**
- [ ] Intent queries blocked when cap reached
- [ ] Clear message explaining block
- [ ] Cap resets weekly (configurable day)

#### FR-COST-003: Budget Alerts
**Description:** Notify user at budget thresholds.
**Thresholds:** 50%, 80%, 95% of weekly cap
**Notification:** In-app banner/toast

**Acceptance Criteria:**
- [ ] Alert displayed when threshold crossed
- [ ] Alert shows current usage and remaining budget

#### FR-COST-004: Credit Usage Tracking
**Description:** Log all credit consumption.
**Logged Data:**
- Timestamp
- Workflow type
- Query parameters
- Credits used
- Leads returned

**Acceptance Criteria:**
- [ ] Every query logged to Turso
- [ ] Usage queryable for reporting

---

### 4.5 Dashboard & Reporting

#### FR-DASH-001: Usage Dashboard
**Description:** Display credit usage and query history.
**Metrics:**
- Credits used this week (by workflow)
- Credits remaining (Intent cap)
- Queries run this week
- Leads exported this week

**Acceptance Criteria:**
- [ ] Real-time data from Turso
- [ ] Filterable by date range
- [ ] Breakdown by workflow type

#### FR-DASH-002: Executive Summary
**Description:** High-level view for executives.
**Metrics:**
- Total credits used (month-to-date)
- Total leads exported (month-to-date)
- Cost per lead
- Trend chart (weekly)

**Acceptance Criteria:**
- [ ] Single-page summary
- [ ] No drill-down required
- [ ] Accessible without admin permissions

#### FR-DASH-003: Pipeline Health
**Description:** Operational health indicators.
**Indicators:**
- Last successful query (timestamp)
- Cache freshness
- API connection status
- Error log (last 10)

**Acceptance Criteria:**
- [ ] Green/yellow/red status indicators
- [ ] Errors displayed with timestamps
- [ ] Refresh button to recheck status

---

## 5. Non-Functional Requirements

### 5.1 Performance
| Requirement | Target |
|-------------|--------|
| Query response time | <30 seconds for typical query |
| CSV export time | <5 seconds for 500 leads |
| Dashboard load time | <3 seconds |
| Cache lookup | <500ms |

### 5.2 Reliability
| Requirement | Target |
|-------------|--------|
| Uptime | 99% (Streamlit Community Cloud SLA) |
| Data persistence | No data loss on redeploy (Turso) |
| Error recovery | Graceful degradation with user feedback |

### 5.3 Security
| Requirement | Implementation |
|-------------|----------------|
| API credentials | Streamlit secrets (encrypted) |
| Database credentials | Streamlit secrets (encrypted) |
| No PII in logs | Sanitize before logging |
| HTTPS only | Enforced by Streamlit Cloud |

### 5.4 Scalability
| Requirement | Notes |
|-------------|-------|
| Concurrent users | 1-2 (Andre, occasionally Damione) |
| Data volume | Thousands of cached leads |
| Growth path | Turso scales; can add PostgreSQL if needed |

### 5.5 Usability
| Requirement | Implementation |
|-------------|----------------|
| No training required | Intuitive UI with clear labels |
| Error messages | Actionable, non-technical language |
| Confirmation dialogs | Before credit-consuming actions |
| Mobile support | Responsive Streamlit layout |

---

## 6. Constraints & Assumptions

### 6.1 Constraints
| Constraint | Impact |
|------------|--------|
| Streamlit Community Cloud hosting | Ephemeral filesystem—must use Turso |
| ZoomInfo API rate limits | TBD—must handle gracefully |
| Andre's availability (7-9 hrs/week) | Limits scope and timeline |
| Single operator (Andre) | No backup—must document well |

### 6.2 Assumptions
| Assumption | Risk if Wrong |
|------------|---------------|
| ZoomInfo API supports employee filter | Must filter locally (waste credits) |
| ZoomInfo API supports SIC filter | Must filter locally (waste credits) |
| ZoomInfo API supports multi-zip query | Must loop single-zip queries |
| "Vending" intent topic is relevant | Poor lead quality |
| Turso free tier is sufficient | Must upgrade or switch |

### 6.3 Dependencies
| Dependency | Owner | Status |
|------------|-------|--------|
| ZoomInfo API credentials | Andre | ✅ Have |
| ZoomInfo API documentation | ZoomInfo | Available |
| Turso account | Andre | To create |
| SIC whitelist | Andre | To provide |

---

## 7. Release Plan

### 7.1 MVP (Phase 1)
**Target:** 3-4 weeks
**Features:**
- Intent workflow (full)
- Geography workflow (full, including multi-zip)
- Hard ICP filters
- Lead scoring
- Deduplication
- CSV export
- Cost controls
- Usage dashboard
- Executive summary

**Exit Criteria:**
- [ ] Both workflows operational
- [ ] CSV exports import cleanly to VanillaSoft
- [ ] Cost tracking accurate
- [ ] Damione approves for production use

### 7.2 Phase 2
**Target:** Post-MVP validation
**Features:**
- VanillaSoft direct POST
- VanillaSoft disposition sync
- Conversion funnel tracking
- Scheduled intent sweeps
- Damione self-service

### 7.3 Phase 3
**Target:** Future
**Features:**
- Intent + Geography combo query
- Route optimization map
- Predictive ML scoring
- Auto-ICP refinement

---

## 8. Open Questions

| Question | Owner | Due |
|----------|-------|-----|
| Complete SIC whitelist | Andre | Before first query |
| ZoomInfo API multi-zip support | Andre | Week 1 |
| Additional intent topics to stack | Damione | Before expanding scope |

---

## Appendix A: VanillaSoft CSV Template Columns

```
List Source
Last Name
First Name
Title
Home
Email
Mobile
Company
Web site
Business
Number of Employees
Primary SIC
Primary Line of Business
Address
City
State
ZIP code
Square Footage
Contact Owner
Lead Source
Vending Business Name
Operator Name
Operator Phone #
Operator Email Address
Operator Zip Code
Operator Website Address
Best Appts Time
Unavailable for appointments
Team
Call Priority
Import Notes
```

---

## Appendix B: Intent Freshness Tiers

| Age | Label | Score Multiplier | Action |
|-----|-------|------------------|--------|
| 0-3 days | 🔥 Hot | 100% | First priority |
| 4-7 days | 🟡 Warm | 70% | Standard priority |
| 8-14 days | 🟠 Cooling | 40% | Lower priority |
| 15+ days | ❄️ Stale | 0% | Exclude |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-27 | Andre | Initial PRD |
