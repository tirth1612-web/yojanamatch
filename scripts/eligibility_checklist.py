"""
FEATURE 2: Structured eligibility checklist.

For a scheme the user IS eligible for, shows per-field ✅ so the user (and
the UI) can see WHY it matched - "matched because: category, income, age" -
instead of a black-box pass/fail. Reuses near_miss_engine's field labels so
the vocabulary is identical whether a field passed or failed.
"""
from matching_engine import sanitize_user, get_resolved_constraints
from near_miss_engine import FIELD_LABELS


def build_checklist(user, scheme):
    """
    Returns an ordered list of checklist rows for every constraint the
    scheme actually has (skips fields the scheme places no restriction on -
    an unrestricted field isn't a "requirement satisfied", it's just absent).

      { "field": "category", "label": "Category", "status": "pass"|"fail",
        "detail": "OBC matches scheme's OBC/EWS restriction" }
    """
    u = sanitize_user(user)
    c = get_resolved_constraints(scheme)
    rows = []

    if c.get('categories'):
        cats = c['categories']
        ok = (u['category'] in cats) or ('ANY' in cats) or (u['category'] == 'EWS' and 'GENERAL' in cats)
        rows.append({
            "field": "category", "label": FIELD_LABELS["category"],
            "status": "pass" if ok else "fail",
            "detail": f"Requires {', '.join(cats)} — you are {u['category'] or 'not specified'}"
        })

    if c.get('gender_restricted'):
        ok = (u['gender'] == c['gender_restricted'])
        rows.append({
            "field": "gender", "label": FIELD_LABELS["gender"],
            "status": "pass" if ok else "fail",
            "detail": f"Requires {c['gender_restricted']} — you are {u['gender'] or 'not specified'}"
        })

    if c.get('min_age') is not None or c.get('max_age') is not None:
        lo, hi = c.get('min_age'), c.get('max_age')
        ok = True
        if u['age'] is not None:
            if lo is not None and u['age'] < lo:
                ok = False
            if hi is not None and u['age'] > hi:
                ok = False
        range_txt = f"{lo or '0'}–{hi or '∞'} years"
        rows.append({
            "field": "age", "label": "Age requirement",
            "status": "pass" if ok else "fail",
            "detail": f"Requires {range_txt} — you are {u['age'] if u['age'] is not None else 'not specified'}"
        })

    if c.get('income_ceiling') is not None or c.get('income_floor') is not None:
        lo, hi = c.get('income_floor'), c.get('income_ceiling')
        ok = True
        if u['annual_income'] is not None:
            if lo is not None and u['annual_income'] < lo:
                ok = False
            if hi is not None and u['annual_income'] > hi:
                ok = False
        range_txt = f"Rs.{lo:,.0f}" if lo else "no floor"
        range_txt += f" to Rs.{hi:,.0f}" if hi else " (no ceiling)"
        rows.append({
            "field": "income", "label": "Income eligibility",
            "status": "pass" if ok else "fail",
            "detail": f"Requires {range_txt} — your income is "
                      f"Rs.{u['annual_income']:,.0f}" if u['annual_income'] is not None else
                      f"Requires {range_txt} — income not specified"
        })

    if c.get('disability_required'):
        ok = bool(u['disability'])
        rows.append({
            "field": "disability", "label": FIELD_LABELS["disability"],
            "status": "pass" if ok else "fail",
            "detail": "Requires disability status" + (" — matched" if ok else " — not indicated")
        })

    # Informational only — NOT a pass/fail eligibility gate. These are weak
    # qualification-type words found in the scheme text (graduate/PhD/
    # college/university/matriculation) that describe an entry requirement
    # the scheme may want, separate from who the scheme is broadly "for".
    # Shown so the user isn't surprised later, but never counted in
    # format_checklist_summary()'s pass/fail total.
    hints = c.get('qualification_hints') or []
    if hints:
        hint_labels = {
            "graduate": "a graduate degree",
            "postgraduate": "a postgraduate degree",
            "phd": "a PhD/doctorate",
            "matriculation": "10th/12th pass",
            "college_or_university": "enrollment in a college/university",
        }
        readable = ", ".join(hint_labels.get(h, h) for h in hints)
        rows.append({
            "field": "qualification_hint", "label": "Additional requirement mentioned",
            "status": "info",
            "detail": f"Scheme text also mentions {readable} — verify against the official source"
        })

    return rows


def format_checklist_summary(rows):
    """
    One-line summary like: '4/4 requirements matched' for quick display.
    Only counts real pass/fail eligibility rows - 'info' rows (see
    qualification hints above) are detail, not a gate, so they're excluded
    from both the numerator and denominator here.
    """
    scored_rows = [r for r in rows if r['status'] in ('pass', 'fail')]
    if not scored_rows:
        return "Open to all applicants — no specific eligibility requirements"
    passed = sum(1 for r in scored_rows if r['status'] == 'pass')
    return f"{passed}/{len(scored_rows)} requirements matched"
