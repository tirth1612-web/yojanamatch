"""
Step: Merge Tier 1 (verified) + Tier 2 (broad) into one combined dataset.
- Tier 1 is the base (trusted structure/numbers).
- If a Tier 1 field is missing/"Not Specified" AND a matching Tier 2 scheme
  has a real value for that field, we backfill it into Tier 1's record.
- Tier 2 duplicates of Tier 1 schemes are then dropped (Tier 1 already has the merged data).

Run: python3 merge_dedup.py
Input:  data/tier1/schemes_verified.json
        data/tier2/processed/schemes_broad.json
Output: data/combined_schemes.json
"""
import json
import os
from rapidfuzz import fuzz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
T1_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier1', 'schemes_verified.json')
T2_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier2', 'processed', 'schemes_broad.json')
OUT_PATH = os.path.join(BASE_DIR, '..', 'data', 'combined_schemes.json')

BLANK_VALUES = {None, "", "not specified", "not_specified", "none", "n/a", "na", "needs_review"}

def is_blank(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in BLANK_VALUES:
        return True
    if isinstance(value, list) and (len(value) == 0 or value == ["any"] or value == ["Not Specified"]):
        return True
    return False

def normalize_name(name):
    if name is None:
        return ""
    name = name.lower().strip()
    # BUG FIX: "for women" / "- for women" used to be stripped here, same as
    # generic filler words like "yojana"/"scheme". That's wrong - the gender
    # qualifier changes WHO is eligible, it isn't decorative. Confirmed real
    # collision risk in this exact dataset: "New Swarnima Scheme - For Women"
    # (Central, women-only, OBC, income ceiling 3L) normalized to nearly the
    # same string as "Swarnima" (a completely different, Maharashtra-only,
    # gender-any scheme with a 98k/1.2L ceiling) - a false match here would
    # either corrupt the Central scheme's verified data with the wrong
    # state's numbers, or silently drop the real Maharashtra scheme as a
    # "duplicate". Only strip truly generic naming suffixes now.
    for suffix in ["yojana", "yojna", "scheme", "programme"]:
        name = name.replace(suffix, "")
    return " ".join(name.split())

def schemes_compatible(t1_scheme, t2_scheme):
    """
    Extra guard before trusting a fuzzy name match: reject it if the two
    schemes clearly can't be the same real-world scheme, even if their
    names look similar. Prevents backfilling/dropping across two different
    schemes that just happen to share a generic name.
    """
    # Explicit, differing, non-"any" gender restrictions -> not the same scheme
    g1 = str((t1_scheme.get('eligibility') or {}).get('gender') or '').strip().lower()
    g2 = str((t2_scheme.get('eligibility') or {}).get('gender') or '').strip().lower()
    if g1 and g2 and g1 not in ('any', 'not specified', 'not_specified') \
            and g2 not in ('any', 'not specified', 'not_specified') and g1 != g2:
        return False

    # Both pinned to specific, different states -> not the same scheme
    s1 = str(t1_scheme.get('state') or '').strip().lower()
    s2 = str(t2_scheme.get('state') or '').strip().lower()
    if s1 and s2 and s1 not in ('all india', 'not specified') \
            and s2 not in ('all india', 'not specified') and s1 != s2:
        return False

    return True

def find_best_tier2_match(t1_scheme, tier2_list, threshold=87):
    best_score = 0
    best_match = None
    for t2 in tier2_list:
        if not schemes_compatible(t1_scheme, t2):
            continue
        score = fuzz.token_sort_ratio(
            normalize_name(t1_scheme['scheme_name']),
            normalize_name(t2['scheme_name'])
        )
        if score > best_score:
            best_score = score
            best_match = t2
    if best_score >= threshold:
        return best_match
    return None

def backfill_fields(t1_scheme, t2_scheme):
    """Fill blank Tier1 top-level and eligibility fields using Tier2 values."""
    filled_fields = []

    for field in ['department', 'official_url', 'benefits_summary', 'short_description',
                  'application_process_summary', 'scheme_category']:
        if is_blank(t1_scheme.get(field)) and not is_blank(t2_scheme.get(field)):
            t1_scheme[field] = t2_scheme[field]
            filled_fields.append(field)

    if is_blank(t1_scheme.get('documents_required')) and not is_blank(t2_scheme.get('documents_required')):
        t1_scheme['documents_required'] = t2_scheme['documents_required']
        filled_fields.append('documents_required')

    if is_blank(t1_scheme.get('tags')) and not is_blank(t2_scheme.get('tags')):
        t1_scheme['tags'] = t2_scheme.get('tags', [])
        filled_fields.append('tags')

    t1_elig = t1_scheme.get('eligibility', {})
    t2_elig = t2_scheme.get('eligibility', {})
    for field in ['gender', 'min_age', 'max_age', 'category', 'income_floor_annual',
                  'income_ceiling_annual', 'occupation', 'business_type', 'disability_status', 'other_conditions']:
        if is_blank(t1_elig.get(field)) and not is_blank(t2_elig.get(field)):
            t1_elig[field] = t2_elig[field]
            filled_fields.append(f"eligibility.{field}")
    t1_scheme['eligibility'] = t1_elig

    if filled_fields:
        t1_scheme['backfilled_from_tier2'] = filled_fields

    return t1_scheme

with open(T1_PATH, encoding='utf-8') as f:
    tier1 = json.load(f)

with open(T2_PATH, encoding='utf-8') as f:
    tier2 = json.load(f)

print(f"Tier 1 (verified): {len(tier1)} schemes")
print(f"Tier 2 (broad, unverified): {len(tier2)} schemes")

matched_tier2_names = set()
backfilled_count = 0

for t1_scheme in tier1:
    match = find_best_tier2_match(t1_scheme, tier2)
    if match:
        matched_tier2_names.add(match['scheme_name'])
        t1_scheme = backfill_fields(t1_scheme, match)
        if t1_scheme.get('backfilled_from_tier2'):
            backfilled_count += 1

print(f"Backfilled missing fields in {backfilled_count} Tier 1 schemes from Tier 2 matches")

kept_tier2 = [s for s in tier2 if s['scheme_name'] not in matched_tier2_names]
print(f"Dropped {len(tier2) - len(kept_tier2)} Tier 2 duplicates (already merged into Tier 1)")
print(f"Remaining Tier 2 (unique): {len(kept_tier2)}")

combined = tier1 + kept_tier2

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(combined, f, indent=2, ensure_ascii=False)

print(f"\nFinal combined dataset: {len(combined)} schemes -> {OUT_PATH}")
