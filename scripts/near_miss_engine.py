"""
FEATURE 1: "Path to Eligibility" engine.

MyScheme-style tools stop at PASS/FAIL. This module goes one step further:
for a scheme the user narrowly fails, it tells them EXACTLY which single
requirement is blocking them and by how much, then finds real alternative
schemes they ALREADY qualify for.

Builds entirely on matching_engine.get_resolved_constraints() and
sanitize_user() - no new data fields required, no re-scraping needed.

Public API:
    analyze_near_misses(user, schemes, max_gap_fields=1) -> list[dict]
    find_alternatives(user, schemes, limit=3) -> list[dict]
"""
from matching_engine import (
    sanitize_user, get_resolved_constraints, is_eligible, find_matches
)

# Human-readable field labels, used to build the "what's blocking you" message
FIELD_LABELS = {
    "income_ceiling": "Income ceiling",
    "income_floor": "Income floor",
    "min_age": "Minimum age",
    "max_age": "Maximum age",
    "category": "Category",
    "gender": "Gender",
    "disability": "Disability status",
    "area": "Rural/Urban restriction",
    "state": "State-specific restriction",
}


def _field_level_check(user, scheme):
    """
    Re-implements is_eligible()'s checks but returns ONE failure entry per
    FIELD (not per free-text sentence like is_eligible does), each carrying
    the actual user value vs. the required value/threshold. This is what
    lets us say "you're over by Rs.60,000" instead of just a text reason.
    """
    u = sanitize_user(user)
    c = get_resolved_constraints(scheme)
    gaps = []

    # Income ceiling
    if c.get('income_ceiling') is not None and u['annual_income'] is not None:
        if u['annual_income'] > c['income_ceiling']:
            gaps.append({
                "field": "income_ceiling",
                "label": FIELD_LABELS["income_ceiling"],
                "required": c['income_ceiling'],
                "user_value": u['annual_income'],
                "gap_amount": round(u['annual_income'] - c['income_ceiling'], 2),
                "message": (f"Income limit is Rs.{c['income_ceiling']:,.0f}, "
                            f"your income is Rs.{u['annual_income']:,.0f} "
                            f"(over by Rs.{u['annual_income'] - c['income_ceiling']:,.0f})")
            })

    # Income floor
    if c.get('income_floor') is not None and u['annual_income'] is not None:
        if u['annual_income'] < c['income_floor']:
            gaps.append({
                "field": "income_floor",
                "label": FIELD_LABELS["income_floor"],
                "required": c['income_floor'],
                "user_value": u['annual_income'],
                "gap_amount": round(c['income_floor'] - u['annual_income'], 2),
                "message": (f"Income must be at least Rs.{c['income_floor']:,.0f}, "
                            f"yours is Rs.{u['annual_income']:,.0f} "
                            f"(short by Rs.{c['income_floor'] - u['annual_income']:,.0f})")
            })

    # Min age
    if c.get('min_age') is not None and u['age'] is not None:
        if u['age'] < c['min_age']:
            gaps.append({
                "field": "min_age",
                "label": FIELD_LABELS["min_age"],
                "required": c['min_age'],
                "user_value": u['age'],
                "gap_amount": round(c['min_age'] - u['age'], 1),
                "message": (f"Minimum age is {c['min_age']:.0f}, you are {u['age']:.0f} "
                            f"({c['min_age'] - u['age']:.0f} year(s) too young)")
            })

    # Max age
    if c.get('max_age') is not None and u['age'] is not None:
        if u['age'] > c['max_age']:
            gaps.append({
                "field": "max_age",
                "label": FIELD_LABELS["max_age"],
                "required": c['max_age'],
                "user_value": u['age'],
                "gap_amount": round(u['age'] - c['max_age'], 1),
                "message": (f"Maximum age is {c['max_age']:.0f}, you are {u['age']:.0f} "
                            f"({u['age'] - c['max_age']:.0f} year(s) over)")
            })

    # Category
    cats = c.get('categories', [])
    if cats:
        user_cat = u['category']
        ok = (user_cat in cats) or ('ANY' in cats) or (user_cat == 'EWS' and 'GENERAL' in cats)
        if not ok:
            gaps.append({
                "field": "category",
                "label": FIELD_LABELS["category"],
                "required": cats,
                "user_value": user_cat or "Not specified",
                "gap_amount": None,
                "message": f"Scheme is restricted to {', '.join(cats)}, you selected {user_cat or 'none'}"
            })

    # Gender
    req_gender = c.get('gender_restricted')
    if req_gender and u['gender'] and req_gender != u['gender']:
        gaps.append({
            "field": "gender",
            "label": FIELD_LABELS["gender"],
            "required": req_gender,
            "user_value": u['gender'],
            "gap_amount": None,
            "message": f"Scheme is open only to {req_gender} applicants"
        })

    # Disability
    if c.get('disability_required') and not u['disability']:
        gaps.append({
            "field": "disability",
            "label": FIELD_LABELS["disability"],
            "required": True,
            "user_value": False,
            "gap_amount": None,
            "message": "Scheme requires a disability status you haven't indicated"
        })

    # Area
    req_area = c.get('area_restricted')
    if req_area and u['area'] not in ('any', '') and req_area != u['area']:
        gaps.append({
            "field": "area",
            "label": FIELD_LABELS["area"],
            "required": req_area,
            "user_value": u['area'],
            "gap_amount": None,
            "message": f"Scheme is restricted to {req_area} areas"
        })

    # State
    scheme_level = str(scheme.get('level') or 'Central').strip().lower()
    scheme_state = str(scheme.get('state') or 'All India').strip().lower()
    user_state = u['state'].lower()
    if scheme_level == 'state':
        if user_state == 'all india' or scheme_state != user_state:
            gaps.append({
                "field": "state",
                "label": FIELD_LABELS["state"],
                "required": scheme.get('state'),
                "user_value": u['state'],
                "gap_amount": None,
                "message": f"This is a {scheme.get('state')}-specific scheme, not for {u['state']}"
            })

    return gaps


def _relaxed_eligibility_check(user, scheme, ignore_field):
    """Same as is_eligible(), but pretends the given field has no constraint."""
    if ignore_field is None:
        return is_eligible(user, scheme)
    # Cheap trick: temporarily patch the user's value to whatever would
    # satisfy that one field, then re-check with the real is_eligible().
    patched_user = dict(user)
    c = get_resolved_constraints(scheme)
    if ignore_field == "income_ceiling" and c.get('income_ceiling') is not None:
        patched_user['annual_income'] = c['income_ceiling']
    elif ignore_field == "income_floor" and c.get('income_floor') is not None:
        patched_user['annual_income'] = c['income_floor']
    elif ignore_field == "min_age" and c.get('min_age') is not None:
        patched_user['age'] = c['min_age']
    elif ignore_field == "max_age" and c.get('max_age') is not None:
        patched_user['age'] = c['max_age']
    elif ignore_field == "category" and c.get('categories'):
        patched_user['category'] = c['categories'][0]
    elif ignore_field == "gender" and c.get('gender_restricted'):
        patched_user['gender'] = c['gender_restricted']
    elif ignore_field == "disability":
        patched_user['disability'] = True
    elif ignore_field == "area" and c.get('area_restricted'):
        patched_user['area'] = c['area_restricted']
    elif ignore_field == "state":
        patched_user['state'] = scheme.get('state', patched_user.get('state'))
    return is_eligible(patched_user, scheme)


def analyze_near_misses(user, schemes, max_gap_fields=2, limit=5):
    """
    Finds schemes the user is CLOSE to qualifying for (fails on 1-2 fields,
    not fully out of reach), and for single-field misses, computes what
    would need to change and whether relaxing just that field alone would
    make them eligible.

    Returns a list of:
      {
        "scheme_name", "scheme_id",
        "blocking_requirements": [...gap dicts...],
        "is_single_blocker": bool,
        "fixable_alone": bool   # true if fixing ONLY the listed gap(s) clears every other check too
      }
    sorted by fewest blocking requirements first (closest misses on top).
    """
    near_misses = []
    for scheme in schemes:
        if not isinstance(scheme, dict):
            continue
        eligible, _ = is_eligible(user, scheme)
        if eligible:
            continue  # not a miss at all

        gaps = _field_level_check(user, scheme)
        if not gaps or len(gaps) > max_gap_fields:
            continue  # either not a real field-level gap, or too far off to be "near"

        fixable_alone = True
        if len(gaps) == 1:
            would_pass, _ = _relaxed_eligibility_check(user, scheme, gaps[0]['field'])
            fixable_alone = would_pass

        near_misses.append({
            "scheme_id": scheme.get('scheme_id'),
            "scheme_name": scheme.get('scheme_name'),
            "blocking_requirements": gaps,
            "is_single_blocker": len(gaps) == 1,
            "fixable_alone": fixable_alone,
        })

    near_misses.sort(key=lambda x: len(x['blocking_requirements']))
    return near_misses[:limit]


def find_alternatives(user, schemes, limit=3):
    """
    Runs the normal matcher and returns the top N schemes the user is
    ALREADY fully eligible for right now - used as the "here's what you
    CAN apply for instead" fallback when their first-choice scheme fails.
    """
    results = find_matches(user, schemes)
    return results[:limit]
