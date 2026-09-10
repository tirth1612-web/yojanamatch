"""
Convert your Tier-1 CSV (the 69-scheme table you built) into schemes_verified.json,
in the exact schema the matching engine expects.

Run: python3 convert_tier1_csv.py
Input:  data/tier1/tier1_raw.csv   (export your Google Sheet as CSV with this name)
Output: data/tier1/schemes_verified.json  (overwrites the old 3-example version)
"""
import pandas as pd
import json
import re
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier1', 'tier1_raw.csv')
OUT_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier1', 'schemes_verified.json')

df = pd.read_csv(CSV_PATH)
df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

def clean(val):
    if pd.isna(val):
        return None
    val = str(val).strip()
    if val.lower() in ['not specified', 'nan', '', 'none', 'n/a']:
        return None
    return val

def clean_number(val):
    val = clean(val)
    if val is None:
        return None
    val = val.replace(',', '').replace('₹', '').strip()
    try:
        return int(float(val))
    except ValueError:
        return None

def extract_income_floor_ceiling(income_ceiling_col, other_conditions_col, notes_col, benefits_col):
    """
    Your sheet's income_ceiling_annual column gives the ceiling directly.
    But floor+ceiling RANGES (e.g. "Rs.1,00,000 to Rs.3,00,000") often show up
    in other_conditions OR notes OR benefits_summary text instead - so we search all three.
    """
    ceiling = clean_number(income_ceiling_col)
    floor = None

    combined_text = " ".join(filter(None, [
        clean(other_conditions_col) or "",
        clean(notes_col) or "",
        clean(benefits_col) or ""
    ]))

    range_match = re.search(
        r'(?:rs\.?|₹)\s*([\d,]+)\s*(?:to|-)\s*(?:rs\.?|₹)?\s*([\d,]+)', combined_text, re.I
    )
    if range_match:
        n1 = int(range_match.group(1).replace(',', ''))
        n2 = int(range_match.group(2).replace(',', ''))
        floor, ceiling = min(n1, n2), max(n1, n2)

    return floor, ceiling

def split_list(val):
    val = clean(val)
    if val is None:
        return None
    # split on semicolon, comma, OR forward-slash (e.g. "ST/SC/OBC" -> ["ST","SC","OBC"])
    parts = re.split(r'[;,/]', val)
    return [p.strip() for p in parts if p.strip()]

output = []
skipped = 0
for _, row in df.iterrows():
    scheme_name = clean(row.get('scheme_name'))
    if scheme_name is None:
        skipped += 1
        continue  # skip blank/empty rows

    income_floor, income_ceiling = extract_income_floor_ceiling(
        row.get('income_ceiling_annual'), row.get('other_conditions'),
        row.get('notes'), row.get('benefits_summary')
    )

    category_raw = clean(row.get('category'))
    category_list = split_list(category_raw) if category_raw else ["any"]

    # Fix: some schemes are labeled "General" in the sheet (since EWS legally
    # falls under the General/Open category) but are actually EWS-specific
    # schemes. If the scheme text mentions EWS/Economically Weaker anywhere,
    # add "EWS" as a category tag too, so it's findable under EWS search.
    ews_check_text = " ".join(filter(None, [
        clean(row.get('short_description')) or "",
        clean(row.get('other_conditions')) or "",
        clean(row.get('notes')) or "",
        clean(row.get('benefits_summary')) or ""
    ])).lower()
    if ('ews' in ews_check_text or 'economically weaker' in ews_check_text) and 'EWS' not in category_list:
        category_list.append('EWS')

    scheme = {
        "scheme_id": clean(row.get('scheme_id')) or f"TIER1-{_}",
        "scheme_name": scheme_name,
        "level": clean(row.get('level')) or "Not Specified",
        "state": clean(row.get('state')) or "All India",
        "department": clean(row.get('department')),
        "short_description": clean(row.get('short_description')),
        "eligibility": {
            "gender": (clean(row.get('gender')) or "any").lower(),
            "min_age": clean_number(row.get('min_age')),
            "max_age": clean_number(row.get('max_age')),
            "category": category_list,
            "income_floor_annual": income_floor,
            "income_ceiling_annual": income_ceiling,
            "occupation": clean(row.get('occupation')) or "any",
            "business_type": clean(row.get('business_type')) or "any",
            "disability_status": clean(row.get('disability_status')) or "not_specified",
            "other_conditions": clean(row.get('other_conditions')) or ""
        },
        "benefits_summary": clean(row.get('benefits_summary')),
        "application_process_summary": clean(row.get('application_process_summary')),
        "documents_required": split_list(row.get('documents_required')) or [],
        "official_url": clean(row.get('source_links')),
        "last_verified_date": clean(row.get('last_verified_date')),
        "verification_status": (clean(row.get('verification_status')) or "needs_review").lower().replace(' ', '_'),
        "tier": 1,
        "notes": clean(row.get('notes'))
    }
    output.append(scheme)

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Converted {len(output)} Tier-1 schemes -> schemes_verified.json")
if skipped:
    print(f"Skipped {skipped} blank row(s) with no scheme_name")

# quick sanity check: show how many got income floor/ceiling detected
with_floor = sum(1 for s in output if s['eligibility']['income_floor_annual'] is not None)
with_ceiling = sum(1 for s in output if s['eligibility']['income_ceiling_annual'] is not None)
print(f"Schemes with income floor detected: {with_floor}")
print(f"Schemes with income ceiling detected: {with_ceiling}")
