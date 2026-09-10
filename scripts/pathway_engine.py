"""
HERO FEATURE: Government Benefit Pathway - orchestrator.

Wires together goal_parser, matching_engine, eligibility_checklist,
financial_calculator, document_readiness, application_steps, and
near_miss_engine into the single end-to-end response:

    YOUR GOAL -> BEST SCHEME -> FINANCIAL BENEFIT -> DOCUMENTS
    -> APPLICATION STEPS -> (if not eligible) ALTERNATIVE PATH

This is the one function the Flask route should call.
"""
from matching_engine import find_matches, is_eligible
from goal_parser import parse_goal, merge_goal_into_user
from eligibility_checklist import build_checklist, format_checklist_summary
from financial_calculator import build_financial_breakdown
from document_readiness import check_document_readiness
from application_steps import get_application_steps
from near_miss_engine import analyze_near_misses, find_alternatives


def build_pathway(user, schemes, goal_text=None, user_owned_documents=None, requested_amount=None):
    """
    user: dict with age/gender/category/annual_income/state/occupation etc.
          (same shape matching_engine.sanitize_user expects)
    schemes: the full combined_schemes.json list
    goal_text: optional free-text goal, e.g. "5 lakh chahiye business ke liye"
    user_owned_documents: optional list/set of canonical document keys the
          user already has (see document_readiness.get_canonical_checklist_options)
    requested_amount: optional explicit loan amount override; if omitted,
          falls back to the goal parser's extracted amount

    Returns a single dict shaped for direct frontend rendering. Every
    sub-section is present but may have "available": False / empty list
    when the underlying data doesn't support it - the frontend should
    render a graceful fallback in that case, not hide the section abruptly.
    """
    goal_parsed = parse_goal(goal_text) if goal_text else None
    effective_user = merge_goal_into_user(user, goal_parsed) if goal_parsed else dict(user)

    amount = requested_amount or (goal_parsed.get('target_amount') if goal_parsed else None)

    matches = find_matches(effective_user, schemes)

    response = {
        "goal": {
            "raw_text": goal_text,
            "parsed": goal_parsed,
        },
        "has_eligible_match": bool(matches),
    }

    if matches:
        best = matches[0]
        best_scheme = next(
            (s for s in schemes if s.get('scheme_name') == best['scheme_name']
             and s.get('scheme_id') == best.get('scheme_id')),
            next((s for s in schemes if s.get('scheme_name') == best['scheme_name']), None)
        )

        checklist_rows = build_checklist(effective_user, best_scheme) if best_scheme else []
        financials = build_financial_breakdown(
            best_scheme, user_gender=effective_user.get('gender'), requested_amount=amount
        ) if best_scheme else {"available": False, "reason": "Scheme data unavailable"}
        doc_readiness = check_document_readiness(
            best_scheme, user_owned_documents or []
        ) if best_scheme else {"total_required": 0, "ready_count": 0, "ready": [], "missing": []}
        steps = get_application_steps(best_scheme) if best_scheme else {"steps": [], "source": "none"}

        response["best_match"] = {
            "scheme_name": best['scheme_name'],
            "scheme_id": best_scheme.get('scheme_id') if best_scheme else None,
            "eligibility_checklist": checklist_rows,
            "eligibility_summary": format_checklist_summary(checklist_rows),
            "financial_breakdown": financials,
            "document_readiness": doc_readiness,
            "application_steps": steps,
            "official_urls": best.get('official_urls', []),
            "verification_status": best.get('verification_status'),
        }

        # Also surface up to 2 more decent alternatives for comparison,
        # even when the top match succeeded - user may want options.
        response["other_options"] = [
            {"scheme_name": m['scheme_name'], "match_score": m['match_score']}
            for m in matches[1:4]
        ]
        return response

    # --- NOT ELIGIBLE for anything: pivot to "path to eligibility" ---
    near_misses = analyze_near_misses(effective_user, schemes, max_gap_fields=2, limit=5)
    alternatives = find_alternatives(effective_user, schemes, limit=3)

    response["best_match"] = None
    response["near_misses"] = near_misses
    response["alternative_note"] = (
        "You're not eligible for a top scheme matching your goal right now, "
        "but here's what's blocking you and what you CAN apply for instead."
    )
    response["fallback_alternatives"] = [
        {"scheme_name": a['scheme_name'], "match_score": a['match_score']}
        for a in alternatives
    ]
    return response
