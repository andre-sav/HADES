# Project Brief: ZoomInfo → VanillaSoft Lead Automation

**Project Name:** ZoomInfo Intent & Geography Lead Pipeline  
**Date:** January 27, 2026  
**Author:** Andre (Data Engineering & Automation Specialist)  
**Sponsor:** Damione (Head of Call Center)  
**Status:** Ready for Development

---

## 1. Executive Summary

Automate ZoomInfo lead extraction and delivery to VanillaSoft call center CRM. This project activates unused intent data while eliminating the manual CSV export process, enabling same-day calling on high-priority leads.

**Key Outcomes:**
- Two automated workflows: Intent-based (nationwide) and Geography-based (radius search)
- Hard ICP filters applied at API level to maximize credit efficiency
- Scored, deduplicated leads exported as VanillaSoft-ready CSV
- Cost controls with budget caps and usage tracking

**Timeline:** ~3 weeks (25 hours)  
**Success Metric:** >10% conversion rate on Intent leads

---

## 2. Business Context

### Current State
- VendTech uses ZoomInfo for lead acquisition via manual firmographic filters + CSV export
- Process is slow, repetitive, and arduous
- Intent data is completely unused despite being available
- Call center also uses Data Axle/Sales Genie, InfoFree
- VanillaSoft database recently cleaned: 281K → 198K records
- Same-day calling capability exists (strength to preserve)

### Problem Statement
Manual CSV exports don't scale, and valuable intent signals are being ignored. Competitors responding faster to intent signals see 7x higher qualification rates.

### Why Now
- ZoomInfo spend already justified—need to maximize ROI
- Intent data decays in days, not weeks
- Existing VSDP codebase provides foundation to build on

---

## 3. Proposed Solution

### Two-Workflow Architecture

#### Workflow 1: Intent-Based (Nationwide)
| Attribute | Value |
|-----------|-------|
| Purpose | Surface leads actively researching "Vending" topic |
| Scope | Nationwide, no geographic filter |
| Trigger | On-demand (scheduled sweeps in Phase 2) |
| Unique Value | Catches prospects at moment of interest |
| Lead Source Tag | `ZoomInfo Intent - Vending - [Score] - [Age]d` |

#### Workflow 2: Geography-Based (Radius Search)
| Attribute | Value |
|-----------|-------|
| Purpose | Automate current manual process—pull leads near target locations |
| Scope | User inputs zip code(s) + radius (10/25/50/100 mi) |
| Trigger | On-demand |
| Unique Value | Eliminates manual CSV exports; supports multi-zip batch |
| Lead Source Tag | `ZoomInfo Geo - [Zip] - [Radius]mi` |

### Hard Filters (Pass/Fail Gates)

Applied at ZoomInfo API level—no credits spent on unqualified leads:

1. **Employee Count:** ≥50 employees (MUST PASS)
2. **Industry:** SIC code on approved whitelist (MUST PASS)

### Scoring Logic

#### Intent-Based Workflow
| Factor | Weight |
|--------|--------|
| Intent signal strength (High/Medium/Low) | 50% |
| On-site presence likelihood | 25% |
| Intent freshness (0-3d: 100%, 4-7d: 70%, 8+d: 40%) | 25% |

#### Geography-Based Workflow
| Factor | Weight |
|--------|--------|
| Proximity to target zip | 50% |
| On-site presence likelihood | 30% |
| Employee count (above threshold) | 20% |

### Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     STREAMLIT DASHBOARD                         │
│   User selects: Intent topic OR Zip(s)+Radius                   │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  QUERY BUILDER                                  │
│   Constructs API request with HARD FILTERS INCLUDED:            │
│   • Employee count ≥50                                          │
│   • SIC codes (approved list only)                              │
│   • Intent topic: "Vending" (Workflow 1)                        │
│   • Geography: Zip(s) + Radius (Workflow 2)                     │
│   → Shows cost estimate before execution                        │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ZOOMINFO API                                 │
│   Returns ONLY pre-filtered, qualified leads                    │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CACHE (Turso)                                │
│   Store results (7-day TTL)                                     │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SCORING ENGINE                                 │
│   Apply priority scoring to qualified leads                     │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  DEDUPLICATION                                  │
│   • Phone normalization                                         │
│   • Fuzzy company name matching                                 │
│   • Cross-workflow dedup                                        │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  CSV EXPORT                                     │
│   VanillaSoft-ready format for manual upload                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Target Users

| User | Role | Access | Key Needs |
|------|------|--------|-----------|
| Andre | Builder/Operator | Full admin | Config, queries, debugging, all dashboards |
| Damione | Sponsor | Viewer (requests via Andre) | ROI metrics, cost visibility, territory requests |
| Call Center Agents | End consumers | VanillaSoft only | Intent score + age visible in lead record |
| Executives | Oversight | Executive Summary page | Spend, volume, cost-per-lead |

### Access Model (MVP)
- **Andre-operated:** Andre runs all queries; Damione requests via Andre
- **Self-service (Phase 2):** Damione can run queries directly with guardrails

---

## 5. Goals & Success Metrics

### Primary Goal
Activate ZoomInfo intent data and automate lead delivery to VanillaSoft, proving ROI on ZoomInfo spend.

### Success Metrics

| Metric | Target |
|--------|--------|
| Intent leads/week | 50 |
| Intent leads/month | 200 |
| Intent credit cap | 500/week |
| Intent conversion rate | ≥10% |
| Geography leads | On-demand (no fixed target) |
| Geography credits | Unlimited (as needed) |
| Manual export elimination | 100% replaced |
| Time-to-lead | Same-day |

### Failure Definition
Intent lead conversion rate below 10%

### MVP Success Criteria
- [ ] Intent workflow operational
- [ ] Geography workflow operational (single + multi-zip)
- [ ] Cost controls active (caps, alerts)
- [ ] CSV export in VanillaSoft format
- [ ] Executive Summary dashboard live

---

## 6. MVP Scope

### Features IN MVP

| Feature | Category |
|---------|----------|
| ZoomInfo Intent API integration | Core |
| ZoomInfo Geography API integration | Core |
| Hard filters at API level (≥50 employees, SIC whitelist) | Core |
| Scoring engine | Core |
| Multi-topic stacking ("Vending" + related topics) | Core |
| 7-day cache (Turso) | Core |
| Cross-workflow deduplication | Core |
| Phone deduplication (VSDP reuse) | Core |
| Multi-zip batch query | Core |
| CSV export (VanillaSoft-ready) | Core |
| Saved location templates | UX |
| Query cost preview | Cost Control |
| Credit budget caps (500/week Intent) | Cost Control |
| Budget alerts (50/80/95%) | Cost Control |
| Usage dashboard | Reporting |
| Executive Summary page | Reporting |
| Pipeline health view | Ops |

### Features OUT of MVP (Phase 2+)

| Feature | Reason |
|---------|--------|
| VanillaSoft direct POST | Need to validate CSV output first |
| VanillaSoft disposition sync | Requires POST + API access |
| Scheduled intent sweeps | Manual trigger acceptable for MVP |
| Intent + Geography combo query | Validate each workflow separately first |
| Conversion funnel tracking | Depends on disposition sync |
| Damione self-service | Andre-operated acceptable for MVP |

---

## 7. Post-MVP Vision

### Phase 2 Features

| Feature | Value |
|---------|-------|
| VanillaSoft direct POST | Eliminate manual upload |
| VanillaSoft disposition sync | Close feedback loop; prove ROI |
| Conversion funnel tracking | Pushed → Contacted → Qualified → Closed |
| Scheduled intent sweeps | Auto-run daily/weekly |
| Intent + Geography combo query | Best of both worlds |
| Lead source comparison dashboard | ZoomInfo vs other vendors |
| Damione self-service | Run queries without Andre |

### Phase 3 Features (Future)

| Feature | Value |
|---------|-------|
| Intent surge alerts | Real-time hot moments |
| Route optimization map | Field sales efficiency |
| Territory heatmap | Visualize lead density |
| Predictive ML scoring | Beyond rules-based |
| Auto-ICP refinement | Continuous optimization |

---

## 8. Technical Considerations

### Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.10+ |
| UI | Streamlit |
| Database | Turso (libsql) |
| Config | YAML + Streamlit secrets |
| Hosting | Streamlit Community Cloud |
| Version Control | Git |

### Storage Strategy

| Data | Storage |
|------|---------|
| ZoomInfo cache | Turso |
| Credit usage log | Turso |
| Query history | Turso |
| Saved location templates | Turso |
| Operator profiles | Turso |
| ICP config (SIC lists) | YAML in repo |

### Turso Schema

```sql
CREATE TABLE operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_name TEXT UNIQUE,
    vending_business_name TEXT,
    operator_phone TEXT,
    operator_email TEXT,
    operator_zip TEXT,
    operator_website TEXT,
    team TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE zoominfo_cache (
    id TEXT PRIMARY KEY,
    company_name TEXT,
    workflow_type TEXT,
    query_params TEXT,
    lead_data TEXT,
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE credit_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_type TEXT,
    query_params TEXT,
    credits_used INTEGER,
    leads_returned INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE location_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    zip_codes TEXT,
    radius_miles INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_type TEXT,
    query_params TEXT,
    leads_returned INTEGER,
    leads_pushed INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### VSDP Reuse Plan

| Component | Action |
|-----------|--------|
| Column mapping (ZoomInfo → VanillaSoft) | Reuse directly |
| Phone cleaning (extension removal, dedup) | Reuse directly |
| Contact owner round-robin assignment | Reuse directly |
| Operator metadata injection | Reuse directly |
| Output schema enforcement | Reuse directly |
| Streamlit app structure | Extend with new screens |
| Google Sheets operator storage | Remove (replace with Turso) |

### New Components to Build

| Component | Description |
|-----------|-------------|
| ZoomInfo API client | Auth, pagination, rate limiting |
| Intent query builder | Topic + firmographic filters |
| Geography query builder | Zip list + radius + filters |
| Scoring engine | Apply weights, rank leads |
| Cache layer | Turso tables, 7-day TTL |
| Cost tracking | Credits used, budget alerts |
| New UI screens | Workflow selector, cost preview, dashboards |

---

## 9. Constraints & Assumptions

### Constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| Streamlit Community Cloud | Ephemeral filesystem | Turso for persistence |
| ZoomInfo credit budget | 500/week Intent | Cost controls, query preview |
| Andre's availability | 7-9 hrs/week | Realistic timeline |
| Single operator | No backup | Simple stack, documentation |

### Assumptions

| Assumption | Validation |
|------------|------------|
| ZoomInfo API supports employee count filter | Check API docs |
| ZoomInfo API supports SIC filter | Check API docs |
| ZoomInfo API supports multi-zip query | Check API docs |
| "Vending" topic captures relevant prospects | Review first batch |
| Intent leads convert at ≥10% | Track and measure |
| Turso free tier sufficient | Monitor usage |

### Dependencies

| Dependency | Owner | Status |
|------------|-------|--------|
| ZoomInfo API credentials | Andre | ✅ Have |
| ZoomInfo API documentation | ZoomInfo | Available |
| Turso account setup | Andre | TBD |
| SIC whitelist | Andre | TBD |

---

## 10. Risks & Open Questions

### Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| "Vending" topic includes non-prospects | Medium | Medium | Hard filters; manual review |
| API cost overrun | Medium | High | Preview, caps, alerts |
| ZoomInfo API doesn't support filters | Low | High | Validate docs first |
| Stale intent data | Medium | Medium | 7-day TTL, age visible |
| Intent conversion below 10% | Medium | High | Track, adjust ICP |
| Single point of failure (Andre) | Medium | High | Documentation |

### Open Questions

| Question | Owner | Needed By |
|----------|-------|-----------|
| SIC codes defining ICP | Andre | Before first query |
| Additional intent topics to stack | Damione | Before expanding |
| Multi-zip API support (batch vs loop) | Andre | During build |

### Resolved Questions

| Question | Resolution |
|----------|------------|
| ZoomInfo pricing | 1 export = 1 credit (flat) |
| Target volume | 50/week Intent |
| Credit budget | 500/week Intent |
| Failure definition | <10% conversion |
| Storage | Turso |
| Hosting | Streamlit Community Cloud |
| VanillaSoft POST | Phase 2 |

---

## 11. Next Steps

### Immediate Actions

| Action | Owner | Target |
|--------|-------|--------|
| Set up Turso account + database | Andre | Day 1 |
| Review ZoomInfo API documentation | Andre | Day 1 |
| Confirm API filter support | Andre | Day 1-2 |
| Provide SIC whitelist | Andre | Day 1-2 |
| Create/extend project repo | Andre | Day 1 |

### Build Sequence

| Phase | Tasks | Effort |
|-------|-------|--------|
| Week 1 | ZoomInfo API client; Turso schema + connection | 6-8 hrs |
| Week 2 | Intent + Geography query builders; Hard filters | 6-8 hrs |
| Week 3 | Scoring; Cache; Deduplication; CSV export | 6-8 hrs |
| Week 4 | UI screens; Testing; Documentation | 6-8 hrs |

**Total: ~25 hours over 3-4 weeks**

### Validation Checkpoints

| Checkpoint | Criteria |
|------------|----------|
| End Week 1 | Can authenticate and pull from ZoomInfo API |
| End Week 2 | Can run filtered Intent + Geography queries |
| End Week 3 | Full pipeline: query → filter → score → dedupe → CSV |
| End Week 4 | UI complete; first real query run |

---

## Appendix A: Config File Structure (Example)

```yaml
hard_filters:
  employee_count:
    minimum: 50
    strict: true

  industry:
    match_type: "exact"
    sic_codes:
      - "5812"    # Eating Places
      # ... full list TBD

scoring:
  intent_workflow:
    intent_strength: 0.50
    onsite_presence: 0.25
    intent_freshness: 0.25
  
  geography_workflow:
    proximity: 0.50
    onsite_presence: 0.30
    employee_scale: 0.20

budget:
  intent:
    weekly_cap: 500
    alerts: [0.50, 0.80, 0.95]
  geography:
    weekly_cap: null  # unlimited

cache:
  ttl_days: 7

intent_topics:
  - "Vending"
  # - "Breakroom"        # Phase 2
  # - "Employee Amenities"  # Phase 2
```

---

## Appendix B: Intent Freshness Strategy

| Age | Priority | Score Multiplier |
|-----|----------|------------------|
| 0-3 days | 🔥 Hot | 100% |
| 4-7 days | 🟡 Warm | 70% |
| 8-14 days | 🟠 Cooling | 40% |
| 15+ days | ❄️ Stale | Exclude |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-27 | Andre | Initial brief |
