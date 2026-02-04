# Technical Architecture Document
# ZoomInfo Intent & Geography Lead Pipeline

## Document Information
| Field | Value |
|-------|-------|
| Project Name | ZoomInfo Lead Pipeline |
| Version | 1.0 |
| Status | Draft |
| Created | 2026-01-27 |
| Author | Andre (Data Engineering & Automation Specialist) |

---

## 1. Overview

### 1.1 Purpose
This document defines the technical architecture for the ZoomInfo Lead Pipeline—a Streamlit application that automates lead extraction from ZoomInfo, applies ICP filtering and scoring, and exports VanillaSoft-ready CSV files.

### 1.2 Architecture Goals
| Goal | Approach |
|------|----------|
| Simplicity | Python + Streamlit; minimal dependencies |
| Persistence | Turso (libsql) for all stateful data |
| Cost efficiency | Cache results; filter at API level |
| Maintainability | Config-driven; clear separation of concerns |
| Extensibility | Modular design for Phase 2 features |

### 1.3 System Context

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SYSTEMS                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐      │
│   │  ZoomInfo   │         │    Turso    │         │ VanillaSoft │      │
│   │    API      │         │  Database   │         │   (Manual)  │      │
│   └──────┬──────┘         └──────┬──────┘         └──────▲──────┘      │
│          │                       │                       │              │
└──────────┼───────────────────────┼───────────────────────┼──────────────┘
           │                       │                       │
           ▼                       ▼                       │
┌─────────────────────────────────────────────────────────────────────────┐
│                     ZOOMINFO LEAD PIPELINE                              │
│                    (Streamlit Application)                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      PRESENTATION LAYER                         │   │
│   │   Streamlit UI: Workflows, Dashboards, Config                   │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                      │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                       SERVICE LAYER                             │   │
│   │   Query Builders, Scoring Engine, Cost Tracker, Export          │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                      │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    INTEGRATION LAYER                            │   │
│   │   ZoomInfo Client, Turso Client, VSDP Utils                     │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              USERS                                      │
├─────────────────────────────────────────────────────────────────────────┤
│   Andre (Admin)    Damione (Viewer)    Executives (Summary Only)        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

### 2.1 Core Technologies
| Component | Technology | Version | Rationale |
|-----------|------------|---------|-----------|
| Language | Python | 3.10+ | Team expertise; ecosystem |
| UI Framework | Streamlit | Latest | Rapid development; existing VSDP pattern |
| Database | Turso (libsql) | Latest | Persistent storage on Streamlit Cloud |
| Config | YAML | - | Human-readable; version-controlled |
| Hosting | Streamlit Community Cloud | - | Free; simple deployment |

### 2.2 Key Dependencies
```
# requirements.txt
streamlit>=1.28.0
libsql-experimental>=0.0.30
pandas>=2.0.0
requests>=2.31.0
pyyaml>=6.0
python-dotenv>=1.0.0
```

### 2.3 Development Tools
| Tool | Purpose |
|------|---------|
| Git | Version control |
| VS Code / Claude Code | Development IDE |
| BMAD Method | Development workflow |

---

## 3. Component Architecture

### 3.1 Directory Structure
```
HADES/
├── app.py                      # Main Streamlit entry point
├── requirements.txt            # Python dependencies
├── zoominfo_client.py          # ZoomInfo API client (auth, intent, company search)
├── turso_db.py                 # Turso database connection and queries
├── scoring.py                  # Lead scoring engine
├── dedup.py                    # Deduplication logic
├── cache.py                    # Cache management
├── export.py                   # CSV export
├── cost_tracker.py             # Credit tracking and budget alerts
├── utils.py                    # Phone cleaning, column mapping (from VSDP)
├── .streamlit/
│   ├── config.toml             # Streamlit config
│   └── secrets.toml            # Credentials (not in git)
├── config/
│   └── icp.yaml                # ICP filters, scoring weights, budgets
├── pages/
│   ├── 1_🎯_Intent_Workflow.py
│   ├── 2_📍_Geography_Workflow.py
│   ├── 3_👤_Operators.py
│   ├── 4_📊_Usage_Dashboard.py
│   └── 5_📈_Executive_Summary.py
├── docs/
│   ├── PROJECT_BRIEF.md
│   ├── prd.md
│   └── architecture.md
└── tests/
    ├── test_zoominfo.py
    ├── test_scoring.py
    └── test_dedup.py
```

### 3.2 Component Descriptions

#### 3.2.1 Presentation Layer (`pages/`)
| Component | Responsibility |
|-----------|----------------|
| Intent Workflow | Query builder UI for intent-based searches |
| Geography Workflow | Query builder UI for location-based searches |
| Operators | CRUD UI for operator management |
| Usage Dashboard | Credit usage, query history, operational metrics |
| Executive Summary | High-level KPIs for leadership |

#### 3.2.2 Core Modules (flat structure)
| File | Responsibility |
|------|----------------|
| `zoominfo_client.py` | OAuth auth, Intent API, Company Search API, rate limiting |
| `turso_db.py` | Database connection, query execution, models |
| `scoring.py` | Apply scoring weights to qualified leads |
| `dedup.py` | Phone normalization, fuzzy matching, cross-workflow dedup |
| `cache.py` | Cache lookup, storage, expiration (7-day TTL) |
| `export.py` | Generate VanillaSoft-formatted CSV |
| `cost_tracker.py` | Log credit usage, check budget caps, alerts |
| `utils.py` | Phone cleaning, column mapping (copied from VSDP) |

---

## 4. Data Architecture

### 4.1 Database Schema (Turso)

#### 4.1.1 Entity Relationship Diagram
```
┌─────────────────┐       ┌─────────────────┐
│    operators    │       │ location_templates│
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ operator_name   │       │ name            │
│ vending_business│       │ zip_codes (JSON)│
│ phone           │       │ radius_miles    │
│ email           │       │ created_at      │
│ zip             │       └─────────────────┘
│ website         │
│ team            │       ┌─────────────────┐
│ created_at      │       │  credit_usage   │
│ updated_at      │       ├─────────────────┤
└─────────────────┘       │ id (PK)         │
                          │ workflow_type   │
┌─────────────────┐       │ query_params    │
│ zoominfo_cache  │       │ credits_used    │
├─────────────────┤       │ leads_returned  │
│ id (PK)         │       │ created_at      │
│ company_name    │       └─────────────────┘
│ workflow_type   │
│ query_params    │       ┌─────────────────┐
│ lead_data (JSON)│       │  query_history  │
│ score           │       ├─────────────────┤
│ created_at      │       │ id (PK)         │
│ expires_at      │       │ workflow_type   │
└─────────────────┘       │ query_params    │
                          │ leads_returned  │
                          │ leads_exported  │
                          │ created_at      │
                          └─────────────────┘
```

#### 4.1.2 Table Definitions

```sql
-- Operator profiles (migrated from VSDP Google Sheets)
CREATE TABLE operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_name TEXT UNIQUE NOT NULL,
    vending_business_name TEXT,
    operator_phone TEXT,
    operator_email TEXT,
    operator_zip TEXT,
    operator_website TEXT,
    team TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Cached ZoomInfo results
CREATE TABLE zoominfo_cache (
    id TEXT PRIMARY KEY,  -- Hash of query params
    company_name TEXT,
    workflow_type TEXT NOT NULL,  -- 'intent' or 'geography'
    query_params TEXT NOT NULL,   -- JSON
    lead_data TEXT NOT NULL,      -- JSON array of leads
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_cache_expires ON zoominfo_cache(expires_at);
CREATE INDEX idx_cache_workflow ON zoominfo_cache(workflow_type);

-- Credit usage log
CREATE TABLE credit_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_type TEXT NOT NULL,
    query_params TEXT,  -- JSON
    credits_used INTEGER NOT NULL,
    leads_returned INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_usage_created ON credit_usage(created_at);
CREATE INDEX idx_usage_workflow ON credit_usage(workflow_type);

-- Saved location templates
CREATE TABLE location_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    zip_codes TEXT NOT NULL,  -- JSON array
    radius_miles INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Query history (audit trail)
CREATE TABLE query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_type TEXT NOT NULL,
    query_params TEXT,  -- JSON
    leads_returned INTEGER,
    leads_exported INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_history_created ON query_history(created_at);
```

### 4.2 Data Flow

#### 4.2.1 Intent Workflow Data Flow
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   User       │     │  Config      │     │   Cache      │
│   Input      │     │  (icp.yaml)  │     │   Check      │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                   QUERY BUILDER                         │
│  • Topic: "Vending"                                     │
│  • Filters: employee≥50, SIC whitelist                  │
│  • Estimate: ~X credits                                 │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Cache Hit?   │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        [YES: Return]            [NO: Query API]
              │                         │
              │                         ▼
              │                  ┌──────────────┐
              │                  │  ZoomInfo    │
              │                  │  Intent API  │
              │                  └──────┬───────┘
              │                         │
              │                         ▼
              │                  ┌──────────────┐
              │                  │ Store Cache  │
              │                  │ Log Credits  │
              │                  └──────┬───────┘
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   SCORING ENGINE                        │
│  • Intent strength (50%)                                │
│  • On-site likelihood (25%)                             │
│  • Freshness (25%)                                      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   DEDUPLICATION                         │
│  • Phone normalization                                  │
│  • Cross-workflow check                                 │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   PREVIEW TABLE                         │
│  • Show scored leads                                    │
│  • Allow selection                                      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   CSV EXPORT                            │
│  • VanillaSoft format                                   │
│  • Operator metadata                                    │
│  • Lead source tags                                     │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Configuration Schema

#### 4.3.1 ICP Configuration (`config/icp.yaml`)
```yaml
# Hard Filters (applied at API level)
hard_filters:
  employee_count:
    minimum: 50
    strict: true  # Fail query if API doesn't support

  sic_codes:
    match_type: exact
    codes:
      - "5812"    # Eating Places
      - "5813"    # Drinking Places
      - "7011"    # Hotels and Motels
      - "8011"    # Offices of Physicians
      - "8021"    # Offices of Dentists
      # ... additional codes

# Scoring Weights
scoring:
  intent:
    signal_strength: 0.50
    onsite_likelihood: 0.25
    freshness: 0.25
  
  geography:
    proximity: 0.50
    onsite_likelihood: 0.30
    employee_scale: 0.20

# Intent Freshness Tiers
freshness:
  hot:
    max_days: 3
    multiplier: 1.0
  warm:
    max_days: 7
    multiplier: 0.7
  cooling:
    max_days: 14
    multiplier: 0.4
  stale:
    max_days: 999
    multiplier: 0.0  # Exclude

# Budget Controls
budget:
  intent:
    weekly_cap: 500
    alerts:
      - 0.50
      - 0.80
      - 0.95
  geography:
    weekly_cap: null  # Unlimited
    alerts: []

# Cache Settings
cache:
  ttl_days: 7
  enabled: true

# Intent Topics
intent_topics:
  primary:
    - "Vending"
  expansion:  # Phase 2
    - "Breakroom"
    - "Employee Amenities"
    - "Office Snacks"

# On-site Likelihood by SIC (for scoring)
onsite_scoring:
  high:  # 100% score
    - "5812"  # Restaurants
    - "7011"  # Hotels
    - "8011"  # Medical offices
  medium:  # 70% score
    - "6411"  # Insurance
    - "6021"  # Banks
  low:  # 40% score
    - "7371"  # Computer services (may be remote)
```

---

## 5. Integration Architecture

### 5.1 ZoomInfo API Integration

#### 5.1.1 Authentication Flow
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   App Start  │────▶│  Check Token │────▶│ Token Valid? │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                    ┌─────────────┴─────────────┐
                                    ▼                           ▼
                              [YES: Use]                  [NO: Refresh]
                                    │                           │
                                    │                           ▼
                                    │                    ┌──────────────┐
                                    │                    │  OAuth Token │
                                    │                    │   Request    │
                                    │                    └──────┬───────┘
                                    │                           │
                                    │                           ▼
                                    │                    ┌──────────────┐
                                    │                    │  Store Token │
                                    │                    └──────┬───────┘
                                    │                           │
                                    └────────────┬──────────────┘
                                                 │
                                                 ▼
                                          ┌──────────────┐
                                          │  Make API    │
                                          │   Request    │
                                          └──────────────┘
```

#### 5.1.2 ZoomInfo API Client (`src/zoominfo/client.py`)
```python
class ZoomInfoClient:
    """
    ZoomInfo API client with authentication, rate limiting, and error handling.
    """
    
    BASE_URL = "https://api.zoominfo.com"
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = None
    
    def authenticate(self) -> bool:
        """Obtain or refresh OAuth access token."""
        ...
    
    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make authenticated API request with retry logic."""
        ...
    
    def search_intent(self, params: IntentQueryParams) -> list[Lead]:
        """Query Intent API."""
        ...
    
    def search_companies(self, params: GeoQueryParams) -> list[Lead]:
        """Query Company Search API."""
        ...
```

#### 5.1.3 Intent API Query Structure
```python
# Request
{
    "intentTopics": ["Vending"],
    "companyEmployeeCount": {"min": 50},
    "sicCodes": ["5812", "5813", ...],
    "intentStrength": ["High", "Medium"],
    "pageSize": 100,
    "page": 1
}

# Response (expected)
{
    "data": [
        {
            "companyId": "123456",
            "companyName": "Acme Corp",
            "intentTopic": "Vending",
            "intentStrength": "High",
            "intentDate": "2026-01-25",
            "employees": 150,
            "sicCode": "5812",
            "address": "123 Main St",
            "city": "Dallas",
            "state": "TX",
            "zip": "75201",
            "phone": "555-123-4567",
            "website": "acme.com",
            "contacts": [...]
        },
        ...
    ],
    "pagination": {
        "totalResults": 250,
        "pageSize": 100,
        "currentPage": 1,
        "totalPages": 3
    }
}
```

#### 5.1.4 Company Search API Query Structure
```python
# Request
{
    "locationSearchType": "radius",
    "postalCodes": ["75201", "75202"],
    "radiusMiles": 25,
    "companyEmployeeCount": {"min": 50},
    "sicCodes": ["5812", "5813", ...],
    "pageSize": 100,
    "page": 1
}

# Response (expected)
{
    "data": [
        {
            "companyId": "789012",
            "companyName": "Beta Inc",
            "employees": 200,
            "sicCode": "7011",
            "address": "456 Oak Ave",
            "city": "Dallas",
            "state": "TX",
            "zip": "75202",
            "phone": "555-987-6543",
            "website": "beta.com",
            "distance": 5.2,  # Miles from search center
            "contacts": [...]
        },
        ...
    ],
    "pagination": {...}
}
```

### 5.2 Turso Database Integration

#### 5.2.1 Connection Management (`src/database/turso.py`)
```python
import libsql_experimental as libsql
import streamlit as st

class TursoDatabase:
    """
    Turso database connection manager.
    """
    
    def __init__(self):
        self.url = st.secrets["TURSO_DATABASE_URL"]
        self.auth_token = st.secrets["TURSO_AUTH_TOKEN"]
        self._conn = None
    
    @property
    def connection(self):
        if self._conn is None:
            self._conn = libsql.connect(
                self.url,
                auth_token=self.auth_token
            )
        return self._conn
    
    def execute(self, query: str, params: tuple = ()) -> list:
        """Execute query and return results."""
        cursor = self.connection.execute(query, params)
        return cursor.fetchall()
    
    def execute_many(self, query: str, params_list: list) -> None:
        """Execute batch insert/update."""
        ...


@st.cache_resource
def get_database() -> TursoDatabase:
    """Get cached database instance."""
    return TursoDatabase()
```

---

## 6. Security Architecture

### 6.1 Secrets Management
| Secret | Storage | Access |
|--------|---------|--------|
| ZoomInfo Client ID | Streamlit secrets | App only |
| ZoomInfo Client Secret | Streamlit secrets | App only |
| Turso Database URL | Streamlit secrets | App only |
| Turso Auth Token | Streamlit secrets | App only |

### 6.2 Secrets Configuration
```toml
# .streamlit/secrets.toml (NOT in version control)

ZOOMINFO_CLIENT_ID = "your-client-id"
ZOOMINFO_CLIENT_SECRET = "your-client-secret"

TURSO_DATABASE_URL = "libsql://your-db-name.turso.io"
TURSO_AUTH_TOKEN = "your-auth-token"
```

### 6.3 Security Controls
| Control | Implementation |
|---------|----------------|
| No PII in logs | Sanitize before logging |
| HTTPS only | Enforced by Streamlit Cloud |
| No hardcoded secrets | All via Streamlit secrets |
| Git exclusions | `.streamlit/secrets.toml` in `.gitignore` |

---

## 7. Error Handling

### 7.1 Error Categories
| Category | Examples | Handling |
|----------|----------|----------|
| Auth errors | Invalid credentials, expired token | Re-authenticate; show user message |
| API errors | Rate limit, server error | Retry with backoff; show user message |
| Data errors | Invalid response format | Log error; show user message |
| Budget errors | Cap exceeded | Block query; show budget status |
| Database errors | Connection failed | Retry; show user message |

### 7.2 Error Response Pattern
```python
class PipelineError(Exception):
    """Base exception for pipeline errors."""
    
    def __init__(self, message: str, user_message: str, recoverable: bool = True):
        self.message = message
        self.user_message = user_message
        self.recoverable = recoverable
        super().__init__(message)


class ZoomInfoAuthError(PipelineError):
    """ZoomInfo authentication failed."""
    pass


class BudgetExceededError(PipelineError):
    """Credit budget would be exceeded."""
    pass
```

---

## 8. Performance Considerations

### 8.1 Caching Strategy
| Data | Cache Location | TTL | Invalidation |
|------|----------------|-----|--------------|
| ZoomInfo results | Turso | 7 days | Manual refresh; TTL expiry |
| Config | Memory | Session | App restart |
| Database connection | Memory | Session | App restart |

### 8.2 Optimization Techniques
| Technique | Implementation |
|-----------|----------------|
| Lazy loading | Load data only when needed |
| Pagination | Limit preview to 100 rows; load more on demand |
| Connection pooling | Reuse Turso connection |
| Batch operations | Bulk insert cached leads |

### 8.3 Performance Targets
| Operation | Target |
|-----------|--------|
| Query builder load | <1 second |
| API query (uncached) | <30 seconds |
| Cache lookup | <500ms |
| CSV export (500 leads) | <5 seconds |
| Dashboard load | <3 seconds |

---

## 9. Deployment Architecture

### 9.1 Deployment Environment
```
┌─────────────────────────────────────────────────────────────────────────┐
│                     STREAMLIT COMMUNITY CLOUD                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    GitHub Repository                            │   │
│   │   • Source code                                                 │   │
│   │   • Config files (icp.yaml)                                     │   │
│   │   • requirements.txt                                            │   │
│   └──────────────────────────┬──────────────────────────────────────┘   │
│                              │ Auto-deploy on push                      │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Streamlit App Instance                       │   │
│   │   • Ephemeral filesystem                                        │   │
│   │   • Secrets injected at runtime                                 │   │
│   │   • Public URL: https://your-app.streamlit.app                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
           │                                      │
           ▼                                      ▼
┌─────────────────────┐              ┌─────────────────────┐
│     Turso Cloud     │              │    ZoomInfo API     │
│   (Persistent DB)   │              │   (External SaaS)   │
└─────────────────────┘              └─────────────────────┘
```

### 9.2 Deployment Checklist
- [ ] GitHub repository created
- [ ] Streamlit Cloud connected to repo
- [ ] Secrets configured in Streamlit Cloud dashboard
- [ ] Turso database created and schema applied
- [ ] ICP config (`config/icp.yaml`) populated
- [ ] Initial operators created in database

---

## 10. Testing Strategy

### 10.1 Test Categories
| Category | Scope | Tools |
|----------|-------|-------|
| Unit tests | Individual functions | pytest |
| Integration tests | API + Database | pytest + mocks |
| Manual testing | End-to-end workflows | Streamlit UI |

### 10.2 Test Coverage Targets
| Component | Target |
|-----------|--------|
| Scoring engine | 90% |
| Deduplication | 90% |
| Phone cleaning | 90% |
| Query builders | 80% |
| API client | 70% (mock external calls) |

### 10.3 Test Data
- Mock ZoomInfo API responses (saved JSON fixtures)
- Test database with sample operators
- Sample leads for deduplication testing

---

## 11. VSDP Code Reuse

### 11.1 Functions to Copy
| Function | Source File | Target File |
|----------|-------------|-------------|
| `remove_phone_extension()` | `vanillasoft_automation.py` | `utils.py` |
| `clean_phone_dataframe()` | `vanillasoft_automation.py` | `utils.py` |
| `remove_duplicate_phones()` | `vanillasoft_automation.py` | `utils.py` |
| `map_zoominfo_to_template()` | `vanillasoft_automation.py` | `utils.py` |
| `fill_operator_fields()` | `vanillasoft_automation.py` | `utils.py` |
| `ZOOMINFO_TEMPLATE_COLUMNS` | `vanillasoft_pipeline.py` | `utils.py` |

### 11.2 Code to NOT Reuse
| Code | Reason |
|------|--------|
| Google Sheets integration | Replaced by Turso |
| Zoho CRM matching | Not in MVP scope |
| CLI automation script | UI-driven approach |

---

## 12. Future Considerations

### 12.1 Phase 2 Architecture Changes
| Feature | Architecture Impact |
|---------|---------------------|
| VanillaSoft POST | Add `src/vanillasoft/client.py` |
| Disposition sync | Add `src/vanillasoft/sync.py`; new DB tables |
| Scheduled sweeps | Add task scheduler (APScheduler or external) |
| Self-service | Add user authentication layer |

### 12.2 Scale Considerations
| Trigger | Action |
|---------|--------|
| Turso free tier exceeded | Upgrade plan or migrate to PostgreSQL |
| >5 concurrent users | Consider dedicated hosting |
| >100k cached leads | Implement cache eviction policy |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-27 | Andre | Initial architecture |
