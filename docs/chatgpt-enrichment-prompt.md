# Enrichment Match Rate Optimization — Consult Prompt

I'm enriching 3,136 lead records (from a Zoho CRM export called "Locatings") by matching them against a 283K-record VanillaSoft call center database export. The goal is to join SIC code, line of business, and employee count onto each lead so I can validate a lead scoring model for a vending machine sales pipeline.

## Current State

My enrichment script does cascading exact matching:
1. Exact company name + ZIP code (matched 2,398)
2. Exact company name only (matched 185)
3. Strip location suffixes like "- Houston" or "TX - Austin" + ZIP (matched 63)
4. Strip corporate suffixes like "Inc", "LLC" + ZIP (matched 2)
5. Strip corporate suffixes name-only (matched 2)

**Result: 2,659/3,136 matched (84.8%). I need 95%+ (close 321 of the remaining 477 unmatched).**

## The Source Data

**Locatings (what I'm enriching):**
- Fields: `company_name`, `street_address`, `city`, `state`, `zip_code`, `stage`
- Company names often include the city/location as a suffix: "BMW of Roswell", "Everglades University Tampa", "FlexCar Marietta GA"
- Some have Zoho stage text appended: "Soerens Ford (GREEN/DELIVERED)"
- Some have typos: "Raddison Hotel Pheonix Airport", "Raul P Elizondo Elementart"

**VanillaSoft (what I'm matching against):**
- 283K records with fields: `Company`, `Zip Code`, `Primary SIC`, `Primary Line of Business`, `Number of Employees`
- Company names are cleaner/canonical: "BMW", "Everglades University", "FlexCar"
- 98% have SIC codes and employee counts

## Unmatched Record Analysis (477 records)

| Failure Pattern | Count | Examples |
|---|---|---|
| City name embedded in company name | ~151 | "BMW of Roswell" (city=Roswell), "Embassy Suites Houston West- Katy" |
| State abbreviation in name | ~52 | "FlexCar Marietta GA", "Best Western Monroe WA." |
| Stage text in parentheses | 10 | "Jubilee Chrysler Dodge Jeep Ram (GREEN/DELIVERED)" |
| Other parentheticals | ~20 | "Hilton Garden Inn (Charlotte, Uptown)", "Peachtree Hills Place (The Terraces)" |
| Name doesn't exist in VS at all | ~244 | "Heart of the Valley YMCA", "Voltage Fitness", "Pasco Juvenile Justice Dept" |

## Sample Unmatched Records

```
"North Houston Mitsubish" | Houston, TX 77060
"United Rentals Trench and HVAC - Kansas City" | Kansas City, MO 64153
"Hilton Garden Inn (Charlotte, Uptown)" | Charlotte, NC 28202
"FlexCar Marietta GA" | Marietta, GA 30067
"Lakeshore Retirement/ The Meadows - Nashville TN" | Nashville, TN 37214
"Allegiance Trucks Liverpool 7th North" | Liverpool, NY 13088
"Encompass Health Rehabilitation Institute of Tucson" | Tucson, AZ 85712
"Morningside House of St. Charles" | Waldorf, MD 20602
"Harbor House Rehabilitation & Nursing Center" | Hingham, MA 02043
"Heart of the Valley YMCA" | Huntsville, AL 35803
"Remington College (GREEN/DELIVERED)" | Mobile, AL 36611
"SAIA LTL Freight SJC" | San Jose, CA 95112
"Ferguson Ent" | Nampa, ID 83687
"BMS Cat Symrna GA" | Smyrna, GA 30082
"Raddison Hotel Pheonix Airport" | Phoenix, AZ 85008
```

## My Current Planned Approach

1. **Strip city name from company** — Use the `city` field to remove it from `company_name` before matching. "BMW of Roswell" with city=Roswell → try "BMW of" and "BMW". Expected: ~150 recoveries.

2. **Strip all parentheticals** — Remove anything in `()` including stage text. Expected: ~30 recoveries.

3. **Token-based fuzzy matching** — Tokenize both names, match when 2+ significant non-stopword tokens overlap and ZIP matches. Expected: ~100-150 recoveries but risk of false positives.

## What I Want From You

1. **What matching strategies am I missing?** Think about: substring matching, n-gram similarity, phonetic matching (Soundex/Metaphone for typos like "Raddison"→"Radisson"), address-based matching (street address exists on both sides), or any other approach.

2. **For the ~244 records where the company name simply doesn't exist in VanillaSoft** — these are leads that VanillaSoft never called. What's the best fallback enrichment strategy? Options I'm considering: LLM classification from company name, Google Places API, or just accepting the gap.

3. **What's the right fuzzy matching threshold?** I'm worried about false positives — matching "Ford" in one ZIP to the wrong "Ford" location. How would you handle disambiguation when multiple VS records could match?

4. **Is there a smarter order of operations?** Maybe some passes should run before others to avoid conflicts.

Give me a concrete Python-level strategy with the matching passes in priority order.
