"""
Enrich HLM Locatings data with SIC codes, employee counts, and line of business
from VanillaSoft DB export.

6-pass matching pipeline:
  Pass 1: Exact canonical name + ZIP5
  Pass 2: City/state-stripped name + ZIP5 (exact)
  Pass 3: Substring/anchor match within ZIP5
  Pass 4: Fuzzy match within ZIP5 (token_set_ratio >= 88, city-stripped variants too)
  Pass 5: Fuzzy match within ZIP3 (token_set_ratio >= 92, city-stripped variants too)
  Pass 6: Exact canonical name only (3+ anchors, no ZIP constraint)
  Unmatched: genuinely not in VanillaSoft

Usage:
    python enrich_locatings.py
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

# --- Paths ---
VS_PATH = Path("/Users/boss/Projects/VanillaSoft-wrangling/VTI_fixed.csv")
LOCATINGS_PATH = Path("/Users/boss/Projects/locator-dashboard/HLM_Locatings.csv")
OUTPUT_PATH = Path("/Users/boss/Projects/HADES/data/enriched_locatings.csv")

# Fields to pull from VanillaSoft
VS_ENRICH_FIELDS = ["Primary SIC", "Primary Line of Business", "Number of Employees"]


# =============================================================================
# ZIP CODE CLEANING
# =============================================================================

def clean_zip(raw: str) -> str:
    """Clean a ZIP code: strip non-numeric, pad to 5 digits.

    Handles: backticks, ='061' format, 4-digit ZIPs missing leading zero,
    9-digit ZIPs (take first 5).
    """
    if not raw:
        return ""
    # Strip everything except digits
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return ""
    # Take first 5 digits (handles ZIP+4)
    digits = digits[:5]
    # Pad with leading zeros (handles 4-digit CT/NJ/MA ZIPs)
    return digits.zfill(5)


# =============================================================================
# NAME NORMALIZATION (Pass 0)
# =============================================================================

CORP_SUFFIXES = re.compile(
    r"\b(?:inc|llc|ltd|corp|co|lp|llp|pc|pa|na|plc|company|incorporated|corporation|limited)\b\.?",
    re.IGNORECASE,
)

STOPWORDS = frozenset({"the", "a", "an", "of", "at", "for", "in", "on", "by", "to", "and", "or"})

ABBREVIATIONS = {
    "st": "saint",
    "mt": "mount",
    "ft": "fort",
    "univ": "university",
    "hosp": "hospital",
    "ctr": "center",
    "cntrl": "central",
    "mgmt": "management",
    "svcs": "services",
    "svc": "service",
    "intl": "international",
    "natl": "national",
    "rehab": "rehabilitation",
    "tech": "technology",
    "assoc": "associates",
    "dept": "department",
    "med": "medical",
    "hlth": "health",
    "govt": "government",
    "mfg": "manufacturing",
    "ent": "enterprises",
    "grp": "group",
    "hwy": "highway",
    "apt": "apartment",
    "bldg": "building",
}

# US state abbreviations (for stripping full state names from company names)
STATE_ABBREVS = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
}


def canonicalize(name: str) -> str:
    """Deep normalization for matching.

    Casefolds, strips punctuation, removes parentheticals, corporate suffixes,
    stopwords, expands abbreviations, collapses whitespace.
    """
    if not name:
        return ""

    s = name.casefold()

    # Remove all parentheticals: "(GREEN/DELIVERED)", "(Charlotte, Uptown)", etc.
    # Also handle unclosed parens: "(GREEN/DELIVERED" without closing paren
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\([^)]*$", " ", s)

    # Replace & with and
    s = s.replace("&", " and ")

    # Remove dash-separated location suffixes: "- hanover md", "- cincinnati oh"
    # Must come before punctuation stripping so we can detect the dash pattern
    # Handles multi-word cities: "- corpus christi tx", "- new york ny"
    s = re.sub(r"\s*-\s+[a-z]+(?:\s+[a-z]+)*(?:\s+[a-z]{2})?\s*$", " ", s)

    # Remove all punctuation except hyphens (within words) and spaces
    s = re.sub(r"[^\w\s-]", " ", s)

    # Remove corporate suffixes
    s = CORP_SUFFIXES.sub(" ", s)

    # Tokenize
    tokens = s.split()

    # Expand abbreviations (only full-token matches)
    tokens = [ABBREVIATIONS.get(t, t) for t in tokens]

    # Remove stopwords
    tokens = [t for t in tokens if t not in STOPWORDS]

    # Remove purely numeric tokens (street numbers, etc.)
    tokens = [t for t in tokens if not t.isdigit()]

    return " ".join(tokens).strip()


def get_anchors(canon_name: str) -> set[str]:
    """Extract significant tokens (>=4 chars, not stopwords) for anchor matching."""
    return {t for t in canon_name.split() if len(t) >= 4 and t not in STOPWORDS}


# =============================================================================
# CITY/STATE STRIPPING (Pass 2)
# =============================================================================

def strip_city_state(canon_name: str, city: str, state: str) -> list[str]:
    """Generate name variants with city/state info removed.

    Returns list of unique non-empty variants (excluding the original).
    """
    if not canon_name:
        return []

    city_canon = canonicalize(city)
    state_lower = state.strip().lower() if state else ""
    # Also handle full state names: "Oregon" -> "or"
    state_abbr = STATE_ABBREVS.get(state_lower, state_lower)

    variants = []

    # 1. Remove trailing city: "bmw roswell" -> "bmw"
    if city_canon and canon_name.endswith(city_canon):
        v = canon_name[: -len(city_canon)].strip()
        if v:
            variants.append(v)

    # 2. Remove trailing state abbr or full name
    for st in {state_lower, state_abbr} - {""}:
        tokens = canon_name.split()
        if tokens and tokens[-1] == st:
            v = " ".join(tokens[:-1]).strip()
            if v:
                variants.append(v)
                # Also try removing city after state removal
                if city_canon and v.endswith(city_canon):
                    v2 = v[: -len(city_canon)].strip()
                    if v2:
                        variants.append(v2)

    # 3. Remove city anywhere in name
    if city_canon:
        pattern = re.compile(r"\b" + re.escape(city_canon) + r"\b")
        stripped = pattern.sub(" ", canon_name).strip()
        stripped = " ".join(stripped.split())
        if stripped and stripped != canon_name:
            variants.append(stripped)

    # 4. Remove trailing "city state": "estes express waterloo ia" -> "estes express"
    if city_canon and state_abbr:
        for st in {state_lower, state_abbr} - {""}:
            city_state = f"{city_canon} {st}"
            if canon_name.endswith(city_state):
                v = canon_name[: -len(city_state)].strip()
                if v:
                    variants.append(v)

    # 5. Remove trailing dash-location: "estes express - waterloo ia"
    if city_canon:
        for sep in [f"- {city_canon}", f"-{city_canon}"]:
            if canon_name.endswith(sep):
                v = canon_name[: -len(sep)].strip().rstrip("-").strip()
                if v:
                    variants.append(v)

    # Deduplicate while preserving order, exclude original
    seen = {canon_name}
    unique = []
    for v in variants:
        if v not in seen and len(v) >= 3:
            seen.add(v)
            unique.append(v)

    return unique


# =============================================================================
# LOAD VANILLASOFT LOOKUP
# =============================================================================

def load_vanillasoft(path: Path) -> tuple[dict, dict, dict, dict]:
    """Build lookup structures from VanillaSoft export.

    Returns:
        vs_by_canon_zip: "canon_name|zip5" -> enrichment
        vs_by_zip5: zip5 -> list of (canon_name, anchors, enrichment)
        vs_by_zip3: zip3 -> list of (canon_name, anchors, enrichment)
        vs_by_canon: canon_name -> enrichment (name-only, first wins)
    """
    vs_by_canon_zip = {}
    vs_by_zip5 = defaultdict(list)
    vs_by_zip3 = defaultdict(list)
    vs_by_canon = {}

    print(f"Loading VanillaSoft from {path}...")
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        count = 0
        skipped_no_data = 0
        skipped_no_zip = 0
        for row in reader:
            company = (row.get("Company") or "").strip()
            if not company:
                continue

            sic = (row.get("Primary SIC") or "").strip()
            lob = (row.get("Primary Line of Business") or "").strip()
            emp = (row.get("Number of Employees") or "").strip()

            if not sic and not emp and not lob:
                skipped_no_data += 1
                continue

            zipcode = clean_zip(row.get("Zip Code") or "")
            canon = canonicalize(company)
            if not canon:
                continue

            enrichment = {
                "sic": sic,
                "lob": lob,
                "employees": emp,
                "raw_name": company,
            }
            anchors = get_anchors(canon)

            # Name-only lookup (first wins to avoid ambiguity)
            if canon not in vs_by_canon:
                vs_by_canon[canon] = enrichment

            if not zipcode:
                skipped_no_zip += 1
                continue

            # Exact lookup by canon+zip
            key = f"{canon}|{zipcode}"
            if key not in vs_by_canon_zip:
                vs_by_canon_zip[key] = enrichment

            # Bucket by zip5 for substring/fuzzy
            vs_by_zip5[zipcode].append((canon, anchors, enrichment))

            # Bucket by zip3 for wider fuzzy
            zip3 = zipcode[:3]
            vs_by_zip3[zip3].append((canon, anchors, enrichment))

            count += 1

    print(f"  Loaded {count:,} VS records (skipped {skipped_no_data:,} no data, {skipped_no_zip:,} no ZIP)")
    print(f"  Canon+ZIP keys: {len(vs_by_canon_zip):,}")
    print(f"  ZIP5 buckets: {len(vs_by_zip5):,}")
    print(f"  ZIP3 buckets: {len(vs_by_zip3):,}")
    print(f"  Name-only keys: {len(vs_by_canon):,}")
    return vs_by_canon_zip, dict(vs_by_zip5), dict(vs_by_zip3), vs_by_canon


# =============================================================================
# MATCHING PASSES
# =============================================================================

def try_exact_zip(canon: str, zip5: str, vs_by_canon_zip: dict) -> dict | None:
    """Pass 1: Exact canonical name + ZIP5."""
    key = f"{canon}|{zip5}"
    return vs_by_canon_zip.get(key)


def try_city_strip_zip(
    canon: str, city: str, state: str, zip5: str, vs_by_canon_zip: dict
) -> tuple[dict | None, str]:
    """Pass 2: Strip city/state from name, then exact match + ZIP5."""
    variants = strip_city_state(canon, city, state)
    for variant in variants:
        key = f"{variant}|{zip5}"
        match = vs_by_canon_zip.get(key)
        if match:
            return match, variant
    return None, ""


def try_substring_zip(
    canon: str, anchors: set[str], zip5: str, vs_by_zip5: dict,
    city_variants: list[str] | None = None,
) -> tuple[dict | None, str]:
    """Pass 3: Substring/anchor match within ZIP5 bucket.

    Tries original name + city-stripped variants.
    Requires substring relationship AND 2+ anchor tokens to overlap.
    """
    candidates = vs_by_zip5.get(zip5, [])
    if not candidates:
        return None, ""

    search_names = [canon] + (city_variants or [])

    for search_name in search_names:
        s_anchors = get_anchors(search_name)
        if len(s_anchors) < 2:
            continue
        for vs_canon, vs_anchors, enrichment in candidates:
            if search_name in vs_canon or vs_canon in search_name:
                overlap = s_anchors & vs_anchors
                if len(overlap) >= 2:
                    return enrichment, vs_canon

    return None, ""


def _fuzzy_search(
    search_names: list[str], candidates: list[tuple], threshold: float
) -> tuple[dict | None, str, float]:
    """Shared fuzzy matching logic for ZIP5 and ZIP3 passes."""
    scored = []
    for search_name in search_names:
        s_anchors = get_anchors(search_name)
        min_anchors = 2 if len(search_name.split()) >= 3 else 1
        for vs_canon, vs_anchors, enrichment in candidates:
            overlap = s_anchors & vs_anchors
            if len(overlap) < min_anchors:
                continue
            score = fuzz.token_set_ratio(search_name, vs_canon)
            if score >= threshold:
                scored.append((score, vs_canon, enrichment))

    if not scored:
        return None, "", 0.0

    # Deduplicate by VS canonical name (same company appearing multiple times
    # in a ZIP bucket should not trigger ambiguity)
    scored.sort(key=lambda x: -x[0])
    seen_names = set()
    unique_scored = []
    for score, vs_canon, enrichment in scored:
        if vs_canon not in seen_names:
            seen_names.add(vs_canon)
            unique_scored.append((score, vs_canon, enrichment))

    if len(unique_scored) == 1 or (unique_scored[0][0] - unique_scored[1][0] >= 5):
        return unique_scored[0][2], unique_scored[0][1], unique_scored[0][0]

    # Ambiguous — skip
    return None, "", 0.0


def try_fuzzy_zip5(
    canon: str, zip5: str, vs_by_zip5: dict,
    city_variants: list[str] | None = None,
) -> tuple[dict | None, str, float]:
    """Pass 4: Fuzzy match within ZIP5 bucket (threshold >= 88)."""
    candidates = vs_by_zip5.get(zip5, [])
    if not candidates:
        return None, "", 0.0
    search_names = [canon] + (city_variants or [])
    return _fuzzy_search(search_names, candidates, threshold=88)


def try_fuzzy_zip3(
    canon: str, zip5: str, vs_by_zip3: dict,
    city_variants: list[str] | None = None,
) -> tuple[dict | None, str, float]:
    """Pass 5: Fuzzy match within ZIP3 bucket (stricter: threshold >= 92)."""
    zip3 = zip5[:3]
    candidates = vs_by_zip3.get(zip3, [])
    if not candidates:
        return None, "", 0.0
    search_names = [canon] + (city_variants or [])
    return _fuzzy_search(search_names, candidates, threshold=92)


def try_name_only(
    canon: str, vs_by_canon: dict,
    city_variants: list[str] | None = None,
) -> tuple[dict | None, str]:
    """Pass 6: Exact name match without ZIP (requires 3+ anchor tokens)."""
    search_names = [canon] + (city_variants or [])
    for search_name in search_names:
        if len(get_anchors(search_name)) >= 3:
            match = vs_by_canon.get(search_name)
            if match:
                return match, search_name
    return None, ""


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def match_record(
    company: str,
    city: str,
    state: str,
    zip5: str,
    vs_by_canon_zip: dict,
    vs_by_zip5: dict,
    vs_by_zip3: dict,
    vs_by_canon: dict,
) -> tuple[dict | None, str, float, str]:
    """Run 6-pass matching pipeline.

    Returns: (enrichment, match_method, score, matched_name)
    """
    canon = canonicalize(company)
    if not canon:
        return None, "unmatched", 0.0, ""

    # Pre-compute city-stripped variants (used in multiple passes)
    city_variants = strip_city_state(canon, city, state)

    if zip5:
        # Pass 1: Exact canonical + ZIP5
        match = try_exact_zip(canon, zip5, vs_by_canon_zip)
        if match:
            return match, "exact+zip", 100.0, match["raw_name"]

        # Pass 2: City/state stripping + exact ZIP5
        match, variant = try_city_strip_zip(canon, city, state, zip5, vs_by_canon_zip)
        if match:
            return match, "city_strip+zip", 100.0, match["raw_name"]

        # Pass 3: Substring/anchor within ZIP5
        match, vs_name = try_substring_zip(canon, get_anchors(canon), zip5, vs_by_zip5, city_variants)
        if match:
            return match, "substring+zip", 100.0, match["raw_name"]

        # Pass 4: Fuzzy within ZIP5
        match, vs_name, score = try_fuzzy_zip5(canon, zip5, vs_by_zip5, city_variants)
        if match:
            return match, "fuzzy+zip5", score, match["raw_name"]

        # Pass 5: Fuzzy within ZIP3
        match, vs_name, score = try_fuzzy_zip3(canon, zip5, vs_by_zip3, city_variants)
        if match:
            return match, "fuzzy+zip3", score, match["raw_name"]

    # Pass 6: Name-only exact match (strict: 3+ anchors)
    match, variant = try_name_only(canon, vs_by_canon, city_variants)
    if match:
        return match, "name_only", 100.0, match["raw_name"]

    return None, "unmatched", 0.0, ""


def main():
    # Load lookups
    vs_by_canon_zip, vs_by_zip5, vs_by_zip3, vs_by_canon = load_vanillasoft(VS_PATH)

    # Load Locatings
    print(f"\nLoading Locatings from {LOCATINGS_PATH}...")
    with open(LOCATINGS_PATH) as f:
        locatings = list(csv.DictReader(f))
    print(f"  {len(locatings):,} records")

    # Enrich
    print("\nEnriching...")
    enriched = []
    stats = {"total": 0, "matched": 0, "unmatched": 0}
    method_counts = {}

    for row in locatings:
        company = (row.get("company_name") or "").strip()
        zip5 = clean_zip(row.get("zip_code") or "")
        city = (row.get("city") or "").strip()
        state = (row.get("state") or "").strip()

        match, method, score, matched_name = match_record(
            company, city, state, zip5,
            vs_by_canon_zip, vs_by_zip5, vs_by_zip3, vs_by_canon,
        )

        enriched_row = {**row}
        if match:
            enriched_row["vs_sic"] = match["sic"]
            enriched_row["vs_lob"] = match["lob"]
            enriched_row["vs_employees"] = match["employees"]
            enriched_row["vs_match_method"] = method
            enriched_row["vs_match_score"] = f"{score:.0f}" if score < 100 else ""
            enriched_row["vs_matched_name"] = matched_name
            stats["matched"] += 1
        else:
            enriched_row["vs_sic"] = ""
            enriched_row["vs_lob"] = ""
            enriched_row["vs_employees"] = ""
            enriched_row["vs_match_method"] = "unmatched"
            enriched_row["vs_match_score"] = ""
            enriched_row["vs_matched_name"] = ""
            stats["unmatched"] += 1

        method_counts[method] = method_counts.get(method, 0) + 1
        stats["total"] += 1
        enriched.append(enriched_row)

    # Stats
    rate = stats["matched"] / stats["total"] * 100 if stats["total"] else 0
    print(f"\n  Total: {stats['total']:,}")
    print(f"  Matched: {stats['matched']:,} ({rate:.1f}%)")
    print(f"  Unmatched: {stats['unmatched']:,} ({100 - rate:.1f}%)")
    print(f"\n  Match methods:")
    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"    {method}: {count:,}")

    # Outcome breakdown
    outcomes = {"Green/ Delivered": [], "Red/ Rejected": []}
    for row in enriched:
        stage = row.get("stage", "")
        if stage in outcomes:
            outcomes[stage].append(row)

    print(f"\n  Outcome match rates:")
    total_outcome = 0
    total_outcome_matched = 0
    for stage, rows in outcomes.items():
        matched = sum(1 for r in rows if r["vs_match_method"] != "unmatched")
        total_outcome += len(rows)
        total_outcome_matched += matched
        print(f"    {stage}: {matched}/{len(rows)} ({matched / len(rows) * 100:.1f}%)")
    if total_outcome:
        print(f"    Combined: {total_outcome_matched}/{total_outcome} ({total_outcome_matched / total_outcome * 100:.1f}%)")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(locatings[0].keys()) + [
        "vs_sic", "vs_lob", "vs_employees",
        "vs_match_method", "vs_match_score", "vs_matched_name",
    ]

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    print(f"\n  Output: {OUTPUT_PATH}")
    print(f"  {len(enriched):,} rows written")

    # Show unmatched outcome records for review
    unmatched_outcomes = [
        r for r in enriched
        if r["vs_match_method"] == "unmatched"
        and r.get("stage") in ("Green/ Delivered", "Red/ Rejected")
    ]
    if unmatched_outcomes:
        print(f"\n  Unmatched outcome records ({len(unmatched_outcomes)}):")
        for r in unmatched_outcomes[:30]:
            print(f"    [{r['stage'][:8]}] {r['company_name'][:50]} | {r['city']}, {r['state']} {r['zip_code']}")


if __name__ == "__main__":
    main()
