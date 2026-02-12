"""
Stage 3: Merge keyword + ChatGPT SIC classifications back onto NonHLM Deliveries.

Expects:
  - data/nonhlm_keyword_classified.csv  (from enrich_nonhlm_prep.py)
  - data/nonhlm_chatgpt_classified.csv  (downloaded from ChatGPT — renamed from classified_pass1 or pass2)

Outputs:
  - data/enriched_nonhlm_deliveries.csv (all 9,609 records with SIC enrichment)

Usage:
    python enrich_nonhlm_merge.py
"""

import csv
import re
from pathlib import Path
from collections import Counter

# --- Paths ---
ORIGINAL_PATH = Path("/Users/boss/Projects/locator-dashboard/NonHLM_Deliveries.csv")
KEYWORD_PATH = Path("data/nonhlm_keyword_classified.csv")
CHATGPT_PATH = Path("data/nonhlm_chatgpt_classified.csv")
OUTPUT_PATH = Path("data/enriched_nonhlm_deliveries.csv")

# ICP target SICs from config/icp.yaml
TARGET_SICS = {
    "3531", "3599", "3999", "4225", "4231", "5511", "7011", "7021", "7033",
    "7359", "7991", "8051", "8059", "8062", "8211", "8221", "8322", "8331",
    "8361", "9223", "9229", "9711",
}


def normalize(name: str) -> str:
    """Same normalization as prep script for join key."""
    s = name.strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\([^)]*$", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def load_classifications(path: Path) -> dict:
    """Load classification CSV into lookup by normalized name."""
    lookup = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            norm_name = normalize(row["name"])
            lookup[norm_name] = {
                "sic_code": (row.get("sic_code") or "").strip(),
                "sic_description": (row.get("sic_description") or "").strip(),
                "sic_confidence": (row.get("sic_confidence") or row.get("confidence") or "").strip(),
                "sic_source": (row.get("sic_source") or "").strip(),
            }
    return lookup


def main():
    # Load original data
    print(f"Loading original data from {ORIGINAL_PATH}...")
    with open(ORIGINAL_PATH) as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows):,} records")

    # Load keyword classifications
    print(f"\nLoading keyword classifications from {KEYWORD_PATH}...")
    keyword_lookup = load_classifications(KEYWORD_PATH)
    print(f"  {len(keyword_lookup):,} entries")

    # Load ChatGPT classifications
    chatgpt_lookup = {}
    if CHATGPT_PATH.exists():
        print(f"Loading ChatGPT classifications from {CHATGPT_PATH}...")
        chatgpt_lookup = load_classifications(CHATGPT_PATH)
        # Set source if not already set
        for v in chatgpt_lookup.values():
            if not v["sic_source"]:
                v["sic_source"] = "llm"
        print(f"  {len(chatgpt_lookup):,} entries")
    else:
        print(f"\n  WARNING: {CHATGPT_PATH} not found.")
        print(f"  Download the ChatGPT output CSV and save it as {CHATGPT_PATH}")
        print(f"  Proceeding with keyword classifications only.\n")

    # Merge
    print("\nMerging...")
    enriched = []
    stats = {"total": 0, "matched": 0, "unmatched": 0}
    source_counts = Counter()

    for row in rows:
        norm_name = normalize(row["location_name"])
        stats["total"] += 1

        # ChatGPT takes priority (may have corrected keyword classification)
        classification = chatgpt_lookup.get(norm_name) or keyword_lookup.get(norm_name)

        enriched_row = {**row}
        if classification and classification["sic_code"]:
            enriched_row["sic_code"] = classification["sic_code"]
            enriched_row["sic_description"] = classification["sic_description"]
            enriched_row["sic_confidence"] = classification["sic_confidence"]
            enriched_row["sic_source"] = classification["sic_source"]
            stats["matched"] += 1
            source_counts[classification["sic_source"]] += 1
        else:
            enriched_row["sic_code"] = ""
            enriched_row["sic_description"] = ""
            enriched_row["sic_confidence"] = ""
            enriched_row["sic_source"] = ""
            stats["unmatched"] += 1

        enriched.append(enriched_row)

    # Stats
    rate = stats["matched"] / stats["total"] * 100 if stats["total"] else 0
    print(f"\n  Total:     {stats['total']:,}")
    print(f"  Enriched:  {stats['matched']:,} ({rate:.1f}%)")
    print(f"  Missing:   {stats['unmatched']:,} ({100 - rate:.1f}%)")
    print(f"\n  By source:")
    for src, cnt in source_counts.most_common():
        print(f"    {src:15s} {cnt:,}")

    # SIC distribution for delivered records
    delivered = [r for r in enriched if r["category"].startswith("6. Delivered") or r["category"].startswith("6.6")]
    del_sics = Counter(r["sic_code"] for r in delivered if r["sic_code"])
    print(f"\n  === SIC Distribution (Delivered Only: {len(delivered):,} records) ===")
    for sic, cnt in del_sics.most_common(30):
        in_icp = "" if sic in TARGET_SICS else " ** NEW **"
        desc = next((r["sic_description"] for r in delivered if r["sic_code"] == sic and r["sic_description"]), "")
        print(f"    {sic} {desc:45s} {cnt:5,}{in_icp}")

    # ICP coverage
    in_target = sum(cnt for sic, cnt in del_sics.items() if sic in TARGET_SICS)
    total_classified = sum(del_sics.values())
    if total_classified:
        print(f"\n  ICP coverage: {in_target:,}/{total_classified:,} delivered records ({in_target/total_classified*100:.1f}%) match current 22 target SICs")
        new_sics = {sic for sic in del_sics if sic not in TARGET_SICS and del_sics[sic] >= 10}
        if new_sics:
            print(f"\n  Candidate SICs to ADD to ICP (10+ deliveries, not in current 22):")
            for sic in sorted(new_sics, key=lambda s: -del_sics[s]):
                desc = next((r["sic_description"] for r in delivered if r["sic_code"] == sic and r["sic_description"]), "")
                print(f"    {sic} {desc:45s} {del_sics[sic]:,} deliveries")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) + ["sic_code", "sic_description", "sic_confidence", "sic_source"]

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    print(f"\n  Output: {OUTPUT_PATH}")
    print(f"  {len(enriched):,} rows written")


if __name__ == "__main__":
    main()
