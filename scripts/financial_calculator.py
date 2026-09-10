"""
FEATURE 5: Financial Impact Calculator.

Turns matching_engine.extract_financial_terms() (interest rate + tenure,
already parsed from scheme text) plus curated loan_terms_overrides.py
(max loan amount, moratorium, gender rebates) into an actual EMI number and
a chart-ready principal/interest breakdown - what the user will actually
pay, not just "8% p.a." as dead text.

Honest about data gaps: if a scheme has no numeric rate/tenure available
anywhere (most Tier-2 schemes), calculate_emi() returns None rather than
guessing - the UI should show "loan terms not available, check official
source" for those instead of a fabricated number.
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from matching_engine import extract_financial_terms

try:
    from loan_terms_overrides import LOAN_TERMS_BY_SCHEME_ID
except ImportError:
    LOAN_TERMS_BY_SCHEME_ID = {}


def _get_terms(scheme):
    """
    Curated overrides (loan_terms_overrides.py) win when present - they were
    hand-verified against source text. Falls back to the regex-extracted
    terms from matching_engine for schemes with no manual entry yet.
    """
    scheme_id = scheme.get('scheme_id')
    if scheme_id in LOAN_TERMS_BY_SCHEME_ID:
        override = dict(LOAN_TERMS_BY_SCHEME_ID[scheme_id])
        return {
            "base_interest_rate_percent": override.get("base_interest_rate_percent"),
            "max_loan_amount": override.get("max_loan_amount"),
            "repayment_years": override.get("repayment_years"),
            "moratorium_months": override.get("moratorium_months"),
            "gender_rebate": override.get("gender_rebate"),
            "gender_locked": override.get("gender_locked"),
            "rate_note": override.get("rate_note"),
            "source": "curated",
        }

    extracted = extract_financial_terms(scheme)
    if not extracted:
        return None
    return {
        "base_interest_rate_percent": extracted.get("interest_rate_default"),
        "max_loan_amount": None,
        "repayment_years": extracted.get("tenure_years"),
        "moratorium_months": None,
        "gender_rebate": (
            {"gender": "female",
             "rebate_percent": round(extracted["interest_rate_default"] - extracted["interest_rate_female"], 2)}
            if extracted.get("interest_rate_female") is not None and extracted.get("interest_rate_default") is not None
            else None
        ),
        "gender_locked": None,
        "rate_note": None,
        "source": "extracted",
    }


def calculate_emi(principal, annual_rate_percent, years):
    """
    Standard reducing-balance EMI formula.
    Returns None if any input is missing/invalid, or if rate is 0 (handled
    separately as a simple division, since the formula divides by zero).
    """
    if not principal or not years or years <= 0:
        return None
    if annual_rate_percent is None:
        return None

    months = years * 12
    if annual_rate_percent == 0:
        return round(principal / months, 2)

    monthly_rate = (annual_rate_percent / 100.0) / 12.0
    emi = principal * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)
    return round(emi, 2)


def build_financial_breakdown(scheme, user_gender=None, requested_amount=None):
    """
    Main entry point. Given a scheme and optionally the user's gender and
    a requested loan amount (from the goal parser or a manual input), builds
    everything needed to render both a text summary and a Chart.js pie/bar:

      {
        "available": bool,
        "principal": 500000,
        "applicable_rate_percent": 8.0,
        "rate_note": "...",
        "tenure_years": 7,
        "monthly_emi": 7823.45,
        "total_repayment": 657000.0,
        "total_interest": 157000.0,
        "chart_data": {
            "labels": ["Principal", "Total Interest"],
            "values": [500000, 157000]
        },
        "gender_rebate_applied": bool,
        "max_loan_amount": 4500000
      }

    Returns {"available": False, "reason": "..."} when no numeric terms exist
    for this scheme (e.g. most Tier-2 / AI-inferred schemes) - the caller
    should render a graceful fallback message, not an empty chart.
    """
    terms = _get_terms(scheme)
    if terms is None or terms.get('base_interest_rate_percent') is None:
        return {"available": False, "reason": "No numeric interest rate found for this scheme yet."}

    rate = terms['base_interest_rate_percent']
    gender_rebate_applied = False
    if user_gender and terms.get('gender_rebate'):
        rebate = terms['gender_rebate']
        if str(user_gender).strip().lower() == rebate.get('gender'):
            rate = round(rate - rebate.get('rebate_percent', 0), 2)
            gender_rebate_applied = True

    principal = requested_amount or terms.get('max_loan_amount')
    if not principal:
        return {"available": False, "reason": "No loan amount specified and scheme has no default ceiling."}
    if terms.get('max_loan_amount') and principal > terms['max_loan_amount']:
        principal = terms['max_loan_amount']  # cap to what the scheme actually offers

    years = terms.get('repayment_years')
    if not years:
        return {"available": False, "reason": "No repayment tenure found for this scheme yet."}

    emi = calculate_emi(principal, rate, years)
    if emi is None:
        return {"available": False, "reason": "Could not compute EMI from available terms."}

    total_repayment = round(emi * years * 12, 2)
    total_interest = round(total_repayment - principal, 2)

    return {
        "available": True,
        "principal": principal,
        "applicable_rate_percent": rate,
        "rate_note": terms.get('rate_note'),
        "tenure_years": years,
        "moratorium_months": terms.get('moratorium_months'),
        "monthly_emi": emi,
        "total_repayment": total_repayment,
        "total_interest": total_interest,
        "chart_data": {
            "labels": ["Principal", "Total Interest"],
            "values": [principal, max(total_interest, 0)]
        },
        "gender_rebate_applied": gender_rebate_applied,
        "max_loan_amount": terms.get('max_loan_amount'),
        "source": terms.get('source'),
    }
