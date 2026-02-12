"""
Stage 1: Prepare NonHLM Deliveries for SIC enrichment.

- Deduplicates by normalized company name
- Keyword-classifies obvious industries (~25%)
- Exports remaining names for ChatGPT classification

Usage:
    python enrich_nonhlm_prep.py
"""

import csv
import re
from pathlib import Path
from collections import Counter

# --- Paths ---
INPUT_PATH = Path("/Users/boss/Projects/locator-dashboard/NonHLM_Deliveries.csv")
KEYWORD_OUT = Path("data/nonhlm_keyword_classified.csv")
CHATGPT_OUT = Path("data/nonhlm_for_chatgpt.csv")

# --- SIC keyword rules ---
# Order matters: more specific patterns first to avoid false matches
KEYWORD_RULES = [
    # Nursing / skilled care (before generic "care")
    (r'skilled nursing|nursing home|nursing center|nursing care|nursing facility', '8051', 'Skilled Nursing Care Facilities'),
    (r'nursing\b.*\b(?:rehab|personal)', '8059', 'Nursing and Personal Care NEC'),

    # Hospitals (before generic "medical")
    (r'hospital|medical center(?!\s*(?:of|for)\s*(?:beauty|aesthet))|health system', '8062', 'General Medical and Surgical Hospitals'),

    # Hotels / lodging
    (r'hotel|hilton|marriott|hyatt|radisson|sheraton|doubletree|hampton\s*inn|holiday\s*inn|comfort\s*(?:inn|suite)|best\s*western|wyndham|motel|la\s*quinta|courtyard\s*(?:by)?|fairfield\s*inn|residence\s*inn|springhill|embassy\s*suite|homewood\s*suite|candlewood|staybridge|crowne\s*plaza|intercontinental|westin|omni\s*hotel|loews|ritz.carlton|four\s*(?:seasons|points)|aloft|w\s*hotel|indigo\s*hotel|even\s*hotel|avid\s*hotel|tru\s*by\s*hilton', '7011', 'Hotels and Motels'),
    (r'\bresort\b|\blodge\b|\binn\b(?!\s*(?:ovation|dustri|vent|surance|terior|tern|vest|stitut))', '7011', 'Hotels and Motels'),

    # Auto dealers
    (r'dealer|dealership|\bford\b(?!\s*(?:foundat|ham))|\bchev(?:rolet|y)\b|toyota|honda|nissan|bmw|mercedes|kia\b|hyundai|subaru|volkswagen|mazda|lexus|dodge|jeep|chrysler|gmc\b|cadillac|buick|volvo|acura|infiniti|mitsubishi|lincoln\s*(?:motor|deal|auto)|genesis\s*(?:motor|deal|auto)|fiat|alfa\s*romeo|maserati|porsche|audi|land\s*rover|jaguar|bentley|\bram\b\s*(?:truck|deal)|isuzu|freightliner|kenworth|peterbilt|mack\s*truck|navistar|international\s*truck', '5511', 'Motor Vehicle Dealers'),

    # Schools (K-12)
    (r'school|academy|elementary|middle\s*school|high\s*school|preparatory|montessori|\.?\s*k\s*-?\s*(?:8|12)\b', '8211', 'Elementary and Secondary Schools'),

    # Colleges / universities
    (r'college|university|univ\b', '8221', 'Colleges and Universities'),

    # Fitness
    (r'ymca|ywca|fitness|gym\b|planet\s*fitness|anytime\s*fitness|lifetime\s*fitness|crossfit|la\s*fitness|gold.?s\s*gym|equinox|orangetheory|crunch\s*fitness|snap\s*fitness|24\s*hour\s*fitness', '7991', 'Physical Fitness Facilities'),

    # Senior living / residential care (before generic "apartment")
    (r'assisted\s*living|senior\s*living|retirement\s*(?:community|home|living|center|village)|memory\s*care|eldercare|brightspring|brookdale|sunrise\s*senior|atria\s*senior|senior\s*care|continuing\s*care|independent\s*living.*senior|senior\s*residence', '8361', 'Residential Care'),

    # Trucking / freight
    (r'trucking|truck\s*terminal|freight\s*line|ltl\b|express.*freight|\bxpo\b|\bsaia\b|estes\s*express|fedex\s*freight|old\s*dominion|yrc\b|abf\s*freight|r\+l\s*carriers|southeastern\s*freight|con-way|holland\s*freight|averitt|dayton\s*freight|forward\s*air', '4213', 'Trucking, Except Local'),

    # Warehousing / distribution
    (r'warehouse|warehousing|distribution\s*center|fulfillment\s*center', '4225', 'General Warehousing and Storage'),

    # Freight transport services
    (r'freight\s*(?:transport|forward|broker|services)|logistics\s*(?:center|hub|terminal)', '4731', 'Freight Transportation Arrangement'),

    # Equipment rental
    (r'united\s*rentals|sunbelt\s*rentals|equipment\s*rental|hertz\s*(?:equip|rent)|herc\s*rentals|neff\s*(?:corp|rental)|blueline\s*rental', '7359', 'Equipment Rental and Leasing NEC'),

    # Vehicle rental
    (r'(?:enterprise|avis|budget|national|alamo|dollar|thrifty|sixt)\s*(?:rent|car)', '7515', 'Passenger Car Leasing'),

    # Correctional
    (r'correctional|prison|jail|detention|penitentiary|inmate', '9223', 'Correctional Institutions'),

    # Military / national security
    (r'military|(?:army|navy|air\s*force|marine|national\s*guard)\s*(?:base|post|station|depot|reserve)|(?:fort|camp)\s*(?:[a-z]+)\s*(?:army|military)?', '9711', 'National Security'),

    # Social services
    (r'social\s*service|family\s*service|community\s*(?:service|center|action)|goodwill|salvation\s*army|united\s*way|red\s*cross|habitat\s*for\s*humanity', '8322', 'Individual and Family Social Services'),

    # Job training
    (r'job\s*(?:training|corps)|vocational|workforce\s*(?:center|develop)|career\s*center', '8331', 'Job Training and Vocational Rehab'),

    # RV parks / campgrounds
    (r'rv\s*(?:park|resort|center)|campground|camping|koa\b', '7033', 'Recreational Vehicle Parks'),

    # Construction machinery
    (r'caterpillar|cat\s*(?:dealer|rental)|john\s*deere|komatsu|volvo\s*(?:construct|equip)|case\s*(?:construct|equip)|hitachi\s*construct', '3531', 'Construction Machinery'),

    # Aviation services
    (r'aviation|airport\s*(?:service|terminal)|fbo\b|signature\s*(?:flight|aviation)|atlantic\s*aviation|million\s*air', '4581', 'Services to Air Transportation'),
]


def normalize(name: str) -> str:
    """Normalize company name for dedup and keyword matching."""
    s = name.strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\([^)]*$", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def keyword_classify(name: str) -> tuple[str, str] | None:
    """Try to classify by keyword rules. Returns (sic_code, sic_description) or None."""
    norm = normalize(name)
    for pattern, sic, desc in KEYWORD_RULES:
        if re.search(pattern, norm):
            return sic, desc
    return None


def main():
    # Load
    print(f"Loading {INPUT_PATH}...")
    with open(INPUT_PATH) as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows):,} records")

    # Dedup by normalized name (keep first occurrence with its city/state)
    seen = {}
    for r in rows:
        norm_name = normalize(r["location_name"])
        if norm_name and norm_name not in seen:
            seen[norm_name] = {
                "name": r["location_name"].strip(),
                "city": r["city"].strip(),
                "state": r["state"].strip(),
                "norm": norm_name,
            }

    print(f"  {len(seen):,} unique names")

    # Classify
    keyword_results = []
    chatgpt_results = []

    for norm_name, info in seen.items():
        result = keyword_classify(info["name"])
        if result:
            sic, desc = result
            keyword_results.append({
                "name": info["name"],
                "city": info["city"],
                "state": info["state"],
                "sic_code": sic,
                "sic_description": desc,
                "sic_confidence": "high",
                "sic_source": "keyword",
            })
        else:
            chatgpt_results.append({
                "name": info["name"],
                "city": info["city"],
                "state": info["state"],
            })

    print(f"\n  Keyword-classified: {len(keyword_results):,} ({len(keyword_results)/len(seen)*100:.1f}%)")
    print(f"  Need ChatGPT:       {len(chatgpt_results):,} ({len(chatgpt_results)/len(seen)*100:.1f}%)")

    # Show keyword breakdown
    sic_counts = Counter(r["sic_code"] for r in keyword_results)
    print(f"\n  Keyword SIC breakdown:")
    for sic, cnt in sic_counts.most_common():
        desc = next(r["sic_description"] for r in keyword_results if r["sic_code"] == sic)
        print(f"    {sic} {desc:45s} {cnt:,}")

    # Write keyword-classified
    KEYWORD_OUT.parent.mkdir(parents=True, exist_ok=True)
    kw_fields = ["name", "city", "state", "sic_code", "sic_description", "sic_confidence", "sic_source"]
    with open(KEYWORD_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=kw_fields)
        w.writeheader()
        w.writerows(keyword_results)
    print(f"\n  Wrote {KEYWORD_OUT} ({len(keyword_results):,} rows)")

    # Write ChatGPT input
    gpt_fields = ["name", "city", "state"]
    with open(CHATGPT_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=gpt_fields)
        w.writeheader()
        w.writerows(chatgpt_results)
    print(f"  Wrote {CHATGPT_OUT} ({len(chatgpt_results):,} rows)")


if __name__ == "__main__":
    main()
