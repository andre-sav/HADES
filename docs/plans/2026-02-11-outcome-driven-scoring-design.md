# Outcome-Driven Lead Scoring

**Date:** 2026-02-11
**Status:** Design approved, not yet implemented

## Problem

HADES scores leads using hardcoded weights and tier scores configured in `icp.yaml`. On-site likelihood, employee scale, proximity, and signal strength scores are based on assumptions — not actual conversion data. There is no feedback loop from sales outcomes back into scoring.

## Success Metric

A **delivery record** created in Zoho CRM, meaning the location approved vending and has had (or will soon have) a delivery. This is the strongest signal — it represents real revenue, not just a meeting booked.

## Available Data

- **3,000+ VanillaSoft-sourced leads** in Zoho CRM with a source field identifying them
- **319 delivery records** attributed to those leads (~10% conversion rate)
- **22 SIC codes**, employee ranges, and geographic data available on each lead
- Zoho CRM auth already partially built (`zoho_auth.py`, `zoho_sync.py`)

## Design

### 1. Batch ID Tracking Chain

Every HADES export gets a batch ID that flows through the entire pipeline:

```
HADES export → CSV "Import Notes" column → VanillaSoft → Zoho CRM custom field
```

**Batch ID format:** `HADES-{YYYYMMDD}-{seq}` (e.g., `HADES-20260211-001`)

Generated at CSV export time in `export.py`. Written to the "Import Notes" column (column 31) in every row. The team ensures this field propagates from VanillaSoft into a Zoho custom field (one-time CRM configuration).

### 2. Outcome Tables

Two new tables in Turso:

**`historical_outcomes`** (one-time import of pre-HADES data):

```sql
CREATE TABLE historical_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    sic_code TEXT,
    employee_count INTEGER,
    zip_code TEXT,
    state TEXT,
    outcome TEXT NOT NULL,          -- 'delivery' or 'no_delivery'
    deal_created_at TEXT,
    delivery_at TEXT,
    imported_at TEXT NOT NULL
);
```

**`lead_outcomes`** (ongoing HADES-originated tracking):

```sql
CREATE TABLE lead_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,          -- HADES export batch
    company_name TEXT NOT NULL,
    company_id TEXT,                 -- ZoomInfo company ID
    sic_code TEXT,
    employee_count INTEGER,
    distance_miles REAL,
    zip_code TEXT,
    state TEXT,
    hades_score INTEGER,             -- Score at time of export
    workflow_type TEXT,               -- 'intent' or 'geography'
    exported_at TEXT NOT NULL,
    outcome TEXT,                     -- NULL → 'contacted' → 'appointment' → 'delivery' → 'churned'
    outcome_at TEXT,
    source_features TEXT,             -- JSON blob of all scoring inputs
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

The `source_features` JSON preserves everything scored on (signal strength, freshness, accuracy, phone type) so weights can be recalibrated without re-querying ZoomInfo.

### 3. Historical Bootstrap

One-time script using existing Zoho auth infrastructure:

1. Query Zoho CRM for all VanillaSoft-sourced leads (identified by source field)
2. For each lead, capture: company name, industry/SIC, employee count, location, deal stage, delivery status
3. Write to `historical_outcomes` table
4. Run initial calibration analysis

### 4. Calibration Engine

No ML. Conversion rates sliced by each scoring dimension:

1. Pull all leads with features and outcomes from Turso
2. Calculate conversion rate per value in each dimension:
   - Per SIC code (22 buckets)
   - Per employee range (3-4 tiers)
   - Per state/region
   - Per proximity band (geography workflow)
   - Per signal strength (intent workflow)
3. Normalize to 0-100 scale (highest converting value gets 100, rest scaled proportionally)
4. Compare to current hardcoded scores in `icp.yaml`
5. Output a calibration report with confidence indicators based on sample size

**Confidence thresholds:**
- High: 100+ leads in bucket
- Medium: 30-99 leads
- Low: < 30 leads (flag for manual review)

**Output example:**

```
Dimension          Current Score → Suggested Score    Confidence
SIC 8062 Hospital       100      →  100               High (280 leads)
SIC 7033 RV Parks        100      →   15               Medium (120 leads)
SIC 3999 Mfg NEC          40      →   72               Low (18 leads)
Employees 101-500          70      →   85               High (1400 leads)
```

### 5. Score Calibration Page

New Streamlit page: **Score Calibration** (page 7).

**Tab 1: Current Weights**
- Live `icp.yaml` values in readable format
- Last calibration date and data volume
- Overall conversion rate baseline

**Tab 2: Calibration Report**
- Side-by-side table: current vs suggested scores per dimension
- Color-coded delta (green = close, red = way off)
- Confidence indicator per row
- Checkbox selection + "Apply selected" button to update `icp.yaml`

**Tab 3: Outcomes Feed**
- Recent outcomes flowing in, by batch
- Conversion funnel: exported → contacted → appointment → delivery
- Time-lag chart: average days from export to delivery
- Batch-level conversion rate highlights (anomaly detection)

**Key rule:** Weights never auto-update. The system suggests, the user approves.

### 6. Ongoing Zoho Outcome Sync

Piggybacks on existing Zoho sync infrastructure (Operators page):

- Same auth flow (`zoho_auth.py`)
- Queries Zoho for deals where source field contains a HADES batch ID
- Matches to `lead_outcomes` rows by batch ID + company name
- Updates `outcome` column as deals progress
- New outcomes trigger a "recalibration available" indicator on the dashboard
- Unmatched leads (batch ID missing in Zoho) logged for pipeline debugging

### 7. Future: Predictive Model (Approach B)

Graduate to logistic regression when HADES-originated outcomes reach ~500+ (estimated 4-6 months).

**What changes:**
- Logistic regression on all features together (discovers interactions weight system cannot)
- Output is still 0-100 score — UI unchanged
- Scikit-learn, ~50 lines of training code, monthly retrain
- Model stored as pickled file, scoring function swaps in

**What stays the same:**
- All tables, sync pipelines, and dashboard components carry forward
- Calibration dashboard adds "Model" tab showing model vs weights performance
- User approves before switching scoring methods
- Fallback to calibrated weights if model underperforms

## Implementation Sequence

1. **Batch ID generation** — Modify `export.py` to generate and embed batch IDs
2. **Outcome tables** — Add `historical_outcomes` and `lead_outcomes` to `turso_db.py`
3. **Lead outcome tracking** — Write to `lead_outcomes` at export time with `source_features`
4. **Historical import script** — Zoho query for VanillaSoft-sourced leads
5. **Calibration engine** — SQL aggregations + normalization logic
6. **Score Calibration page** — New Streamlit page with 3 tabs
7. **Zoho outcome sync** — Extend existing sync to pull deal outcomes
8. **Weight application** — "Apply selected" writes back to `icp.yaml`

## Files to Create/Modify

```
NEW:  calibration.py                    -- Calibration engine (conversion rates, normalization)
NEW:  pages/7_Score_Calibration.py      -- Calibration dashboard
NEW:  scripts/import_historical.py      -- One-time Zoho historical import
MOD:  export.py                         -- Batch ID generation
MOD:  turso_db.py                       -- outcome tables, CRUD methods
MOD:  zoho_sync.py                      -- Outcome sync from Zoho deals
MOD:  config/icp.yaml                   -- Updated by calibration (user-approved)
```

## Dependencies

- Zoho CRM custom field for HADES batch ID (team configuration)
- VanillaSoft → Zoho field mapping includes "Import Notes" (team configuration)
- Existing `zoho_auth.py` and `zoho_sync.py` working (partially built)

## Timeline

- **Week 1:** Historical import, first calibration report
- **Week 2+:** HADES goes live with calibrated weights
- **Month 2+:** First HADES-originated outcomes flow back
- **Month 3+:** Compare HADES conversion rates to historical baseline
- **Month 4-6:** Enough data for predictive model evaluation
