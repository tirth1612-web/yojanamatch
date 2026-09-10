"""
FEATURE 3: Goal parser.

Turns a free-text goal ("Mujhe 5 lakh chahiye business start karne ke liye")
into a structured hint dict the pathway engine can use to pick which
scheme(s) to feature first and roughly what loan amount to size the
financial calculator around.

Deliberately simple (regex + keyword maps), NOT full NLP - this is a
routing hint layered on top of the real eligibility filters the user
already gives (age/gender/income/category), not a replacement for them.
"""
import re

AMOUNT_UNIT_MULTIPLIER = {
    "lakh": 100000, "lac": 100000, "lakhs": 100000,
    "crore": 10000000, "crores": 10000000, "cr": 10000000,
    "thousand": 1000, "k": 1000,
}

# Purpose keyword -> (occupation hint for matching_engine, loan_category hint
# for the channel-finance locator, human label for display)
PURPOSE_MAP = [
    (r'\b(business|udyog|dukan|shop|vyapar|entrepreneur|startup|self.?employ)\b',
     {"occupation": "entrepreneur", "loan_category": "term_loan", "label": "Start/expand a business"}),
    (r'\b(education|padhai|study|college|school|degree|course|fees?)\b',
     {"occupation": "student", "loan_category": "education_loan", "label": "Education"}),
    (r'\b(farm|kisan|krishi|agriculture|crop|khet|dairy|livestock)\b',
     {"occupation": "farmer", "loan_category": "micro_finance", "label": "Farming/agriculture"}),
    (r'\b(house|ghar|home|makan|housing)\b',
     {"occupation": "", "loan_category": None, "label": "Housing"}),
    (r'\b(handicraft|artisan|weav|handloom|craft)\b',
     {"occupation": "artisan", "loan_category": "micro_finance", "label": "Artisan/handicraft work"}),
    (r'\b(job|naukri|employment|rozgar|unemployed|skill)\b',
     {"occupation": "unemployed", "loan_category": None, "label": "Employment/skill training"}),
]


def _extract_amount(text):
    """Finds the first monetary amount mentioned, in INR. Returns None if none found."""
    m = re.search(
        r'(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|lakhs|crore|crores|cr|thousand|k)?',
        text, re.I
    )
    if not m:
        return None
    try:
        val = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in AMOUNT_UNIT_MULTIPLIER:
        val *= AMOUNT_UNIT_MULTIPLIER[unit]
    # guard against matching a stray small number that isn't really an amount
    # (e.g. "5 documents") - require at least a plausible loan-size figure
    if val < 500:
        return None
    return int(val)


def _extract_purpose(text):
    for pattern, info in PURPOSE_MAP:
        if re.search(pattern, text, re.I):
            return info
    return {"occupation": "", "loan_category": None, "label": "General financial assistance"}


def parse_goal(goal_text):
    """
    Parses a free-text goal string.

    Returns:
      {
        "raw_text": "...",
        "target_amount": 500000 | None,
        "occupation_hint": "entrepreneur" | "" ,
        "loan_category_hint": "term_loan" | None,
        "purpose_label": "Start/expand a business"
      }

    This dict is meant to be merged INTO the user's own profile dict
    (age/gender/income/category/state, which the user must still provide
    separately) - it never overrides explicit fields the user has already set.
    """
    if not goal_text or not isinstance(goal_text, str):
        return {
            "raw_text": goal_text or "",
            "target_amount": None,
            "occupation_hint": "",
            "loan_category_hint": None,
            "purpose_label": "General financial assistance",
        }

    amount = _extract_amount(goal_text)
    purpose = _extract_purpose(goal_text)

    return {
        "raw_text": goal_text,
        "target_amount": amount,
        "occupation_hint": purpose["occupation"],
        "loan_category_hint": purpose["loan_category"],
        "purpose_label": purpose["label"],
    }


def merge_goal_into_user(user, goal_parsed):
    """
    NOTE (changed): this used to fall back to goal_parsed['occupation_hint']
    (guessed from free text with a simple regex/keyword map, see PURPOSE_MAP
    above) whenever the user hadn't picked an occupation filter themselves.
    In practice that guess was often wrong, and occupation feeds directly
    into find_matches()'s occupation-based sort key in matching_engine.py -
    so a slightly-off sentence could silently push the wrong schemes to the
    top with no visible explanation to the user.

    Per feedback: the explicit, structured filters the user actually fills
    in on the main form (gender/category/income/occupation/etc) are the
    reliable signal and should be the ONLY thing driving eligibility and
    ranking. Free-text goal_text is kept around purely for display (the
    "Goal: ..." banner/purpose_label) and for target_amount extraction
    (there's no dedicated amount field otherwise) - it no longer feeds any
    eligibility or matching decision. This is now a no-op passthrough, kept
    as a named function so pathway_engine.py / app.py don't need to change,
    and so the "why" is documented in one place.
    """
    return dict(user)
