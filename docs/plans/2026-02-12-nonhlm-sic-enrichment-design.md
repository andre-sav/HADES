# NonHLM Deliveries SIC Enrichment Design

## Objective

Classify 9,609 NonHLM delivery records by 4-digit SIC code to discover which industries actually accept and keep vending machines. This ground truth data validates and expands the 22-SIC ICP in `config/icp.yaml`.

## Pipeline

### Stage 1 — Local Prep (`enrich_nonhlm_prep.py`)
- Deduplicate 9,609 records → ~7,768 unique company names
- Keyword-classify ~25% (hotels, schools, dealerships, etc.) → `data/nonhlm_keyword_classified.csv`
- Export remaining ~5,800 for LLM classification → `data/nonhlm_for_chatgpt.csv`

### Stage 2 — ChatGPT Project (two-pass)
- **Pass 1:** Classify all rows by name + city + state alone. Assign confidence: high/medium/low. Output: `classified_pass1.csv`
- **Pass 2:** Web search medium + low confidence records to verify/correct SIC codes. Output: `classified_pass2.csv`

### Stage 3 — Local Merge (`enrich_nonhlm_merge.py`)
- Combine keyword-classified + ChatGPT-classified results
- Join back to all 9,609 original records
- Output: `data/enriched_nonhlm_deliveries.csv`
- Print SIC distribution, delivery rates by industry, ICP gap analysis

## Output Schema

| Column | Description |
|---|---|
| (all original columns) | From NonHLM_Deliveries.csv |
| `sic_code` | 4-digit SIC code |
| `sic_description` | Human-readable industry name |
| `sic_confidence` | high, medium, low, or verified |
| `sic_source` | keyword, llm, or web_search |

## Files

- `enrich_nonhlm_prep.py` — Stage 1 prep script
- `enrich_nonhlm_merge.py` — Stage 3 merge script
- `docs/chatgpt-nonhlm-sic-instructions.md` — ChatGPT project instruction (ready to paste)
