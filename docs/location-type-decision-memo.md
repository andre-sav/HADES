# Location Type Filter: Decision Memo

**To:** Damione
**From:** Lead Pipeline Team
**Date:** February 3, 2026
**Re:** Optimizing Contact Search for Vending Services Territory Coverage

---

## Executive Summary

We need your input on which location filter strategy to use when searching for potential vending service clients in an operator's territory. This decision affects how many leads we find and the quality of those leads.

**The Question:** When searching for contacts within a 15-mile radius, should we require that both the contact AND their company headquarters be in the territory, or just the contact?

---

## Background

ZoomInfo's Contact Search API offers different "Location Type" filters that determine which contacts are returned:

| Location Type | What It Means |
|---------------|---------------|
| **Person AND HQ** | Contact's work location AND company headquarters must BOTH be in the search radius |
| **Person** | Only the contact's work location must be in the radius (HQ can be anywhere) |
| **Combined** | Run both searches and merge results |

---

## Test Results: Northbrook, IL (ZIP 60062, 15-mile radius)

We ran identical searches with both filters. Same ZIP codes, same industries, same quality filters.

| Metric | Person AND HQ | Person Only | Difference |
|--------|---------------|-------------|------------|
| **Companies Found** | 46 | 56 | +10 (+22%) |
| **Contacts Found** | 79 | 80 | +1 |

---

## What "Person" Finds That "Person AND HQ" Misses

These companies have employees working at physical sites in the territory, but their corporate headquarters is elsewhere:

| Company | Contact | Title | Why They Appeared |
|---------|---------|-------|-------------------|
| **LOGISTEED America** | Christopher Baillie | Branch Manager | Japanese logistics company with Chicago branch |
| **Farrow** | Lorrie Roddy | Branch Manager (Chicago) | Canadian company with Chicago branch |
| **Caterpillar** | Filip Marek | Division CFO | HQ in Peoria, IL - office in territory |
| **Caremark (CVS)** | Dawn Matras | Director, Specialty Customer Care | HQ in Rhode Island |
| **The Hoxton** | Amos Kelsey | General Manager | UK hotel chain with Chicago property |
| **Crowne Plaza** | Cher Jacobsen | General Manager | IHG hotel with local property |
| **Pampered Chef** | Bikram Sohi | COO | Berkshire Hathaway subsidiary |
| **WillScot** | A.J. McGrath | VP and General Manager | HQ in Phoenix, AZ |
| **Canadian Alliance Terminals** | William McKinnon | President | Canadian company with Chicago operations |
| **Barrett Distribution** | Arthur Barrett | President | HQ in Massachusetts |

**Key Observation:** Many of these are **branch managers** or **local general managers** - people who likely CAN authorize vending for their specific facility.

---

## What "Person AND HQ" Finds That "Person" Misses

These companies appeared in the Person AND HQ search but not in the Person-only search (due to result ranking/pagination):

| Company | Contact | Title |
|---------|---------|-------|
| Loyola Academy | Lynn Egan | Director, Communications |
| Wespath Benefits | Christopher Wampler | Director, Project Management |
| Harper College | Riaz Yusuff | Chief Information Officer |
| Northwest Community Healthcare | Randi Zitron | Director, HR |
| Prospect Heights School District 23 | Christopher Alms | Director, Technology |
| Radio Flyer | Amy Bastuga | Chief People Officer |
| ITW | Randall Scheuneman | VP & Chief Accounting Officer |

**Key Observation:** These are **local institutions** (schools, colleges, healthcare) where the contact likely has direct authority.

---

## The Trade-Off

### Option A: Person AND HQ (Current Manual Process)

**Pros:**
- Higher confidence the contact has local decision authority
- Avoids "that's a corporate decision" responses
- Filters to truly local businesses
- Matches our existing manual workflow

**Cons:**
- Misses branch offices of national chains
- Lower volume (46 vs 56 companies in test)
- May miss legitimate opportunities at regional facilities

**Best For:** Prioritizing quality over quantity; focusing on owner-operated or locally-headquartered businesses

---

### Option B: Person Only

**Pros:**
- 22% more companies found
- Captures branch offices and regional facilities
- Finds contacts who physically work at sites in the territory
- Branch managers often CAN authorize vending for their location

**Cons:**
- Some contacts may need to escalate to corporate
- May include facilities with national vending contracts
- Slightly more filtering needed during outreach

**Best For:** Maximizing coverage; willing to handle some "call corporate" responses

---

### Option C: Combined (Run Both, Merge Results)

**Pros:**
- Maximum coverage - gets local companies AND branch offices
- No companies missed due to ranking/pagination
- Estimated 60-70 companies (vs 46 or 56 alone)
- No additional cost (ZoomInfo only charges for enrichment, not searches)

**Cons:**
- More contacts to review and qualify
- National chains often have inaccessible corporate decision makers
- Branch managers may lack authority despite local presence
- Implementation complexity

**Best For:** Comprehensive territory coverage when operators are willing to navigate corporate procurement processes

---

## Concrete Scenario: Making a Sale

**Scenario 1: Local Business (Person AND HQ)**
> You call **Wilmette Park District**. Jeffery Groves, General Manager of Recreation Facilities, answers. He says "Yes, I can make that decision. Let's set up a meeting."
>
> **Result:** Direct path to sale.

**Scenario 2: Branch Office (Person Only)**
> You call **LOGISTEED America** (Chicago branch). Christopher Baillie, Branch Manager, answers. He says "I manage this facility. Vending is my call for this location."
>
> **Result:** Direct path to sale for that facility.

**Scenario 3: Branch Office with Corporate Control**
> You call **Caremark (CVS)**. Dawn Matras, Director, answers. She says "Vending is handled through our corporate facilities team in Rhode Island."
>
> **Result:** Dead end or long sales cycle.

---

## Our Recommendation

We recommend starting with **Option A (Person AND HQ)** as the default, with the ability to switch to **Option B (Person)** when:
- An operator's territory has few results with Person AND HQ
- The operator is willing to pursue national chain locations
- The target is 75+ companies and Person AND HQ yields <50

This matches the manual process that's been working, while giving flexibility for territories that need more volume.

---

## Questions for Your Decision

1. **Volume vs. Quality:** Is finding 22% more companies worth potentially more "call corporate" responses?

2. **National Chains:** Are branch locations of national chains (hotels, logistics, healthcare systems) viable targets, or do they typically have corporate vending contracts?

3. **Operator Preference:** Should operators be able to choose their preferred filter, or should we standardize?

4. **Combined Approach:** Is the additional review time worth it to get maximum coverage, knowing many national chain contacts may be dead ends?

---

## Next Steps

Once you provide direction, we will:
1. Set the appropriate default in the system
2. Document the guidance for operators
3. Optionally implement the combined approach if desired

Please let us know which approach you'd like us to proceed with.

---

*Prepared by the Lead Pipeline Development Team*
