"""
FEATURE 6: Application steps pathway.

application_process_summary in the dataset is free-text, not structured
steps. This module gets numbered steps two ways:

  1. APPLICATION_STEPS_OVERRIDES: hand-curated clean steps for important
     schemes (same pattern as loan_terms_overrides.py) - add entries here
     over time as you verify more schemes, exactly like you did for loan terms.
  2. A fallback splitter for every other scheme, that breaks the raw text
     into readable steps using common separators (numbered lists, "then",
     line breaks) - not as clean as a curated entry, but always produces
     SOMETHING instead of a wall of text.

Generic 5-step fallback (Prepare documents -> Apply -> Appraisal -> Sanction
-> Disbursement) is used only as an absolute last resort when the scheme has
literally no application_process_summary text at all, and is clearly marked
as generic so it isn't mistaken for scheme-specific guidance.
"""
import re

# Fill this in over time for schemes you've manually verified, same workflow
# as loan_terms_overrides.py. Key = scheme_id, value = ordered step strings.
APPLICATION_STEPS_OVERRIDES = {
    # "TIER1-3": [
    #     "Approach your nearest Regional Rural Bank or Cooperative Bank",
    #     "Submit a Detailed Project Report along with KYC documents",
    #     "Bank appraises the project and verifies eligibility",
    #     "Loan sanctioned and first tranche disbursed",
    #     "Remaining tranches released as per project milestones",
    # ],
}

GENERIC_FALLBACK_STEPS = [
    "Prepare all required documents",
    "Apply through the authorised agency or official portal",
    "Application undergoes project/eligibility appraisal",
    "Loan or benefit is sanctioned",
    "Amount is disbursed to the beneficiary",
]


def _split_free_text_into_steps(text):
    """
    Best-effort split of unstructured application_process_summary text into
    step-like chunks. Tries, in order: explicit numbered list markers,
    semicolon/newline separated clauses, then sentence-level split as a
    last resort. Always trims to reasonable step-length chunks.
    """
    text = text.strip()
    if not text:
        return []

    # 1. Explicit numbering like "1. ... 2. ... 3. ..."
    numbered = re.split(r'\d+\s*[\.\)]\s*', text)
    numbered = [s.strip(' -–—') for s in numbered if s.strip()]
    if len(numbered) >= 2:
        return [s for s in numbered if len(s) > 3]

    # 2. Line breaks / bullets / semicolons
    parts = re.split(r'[\r\n•\*;]+', text)
    parts = [p.strip(' -–—') for p in parts if p.strip()]
    if len(parts) >= 2:
        return [p for p in parts if len(p) > 3]

    # 3. Sentence-level split (period followed by space + capital letter)
    sentences = re.split(r'(?<=[.!])\s+(?=[A-Z])', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) >= 2:
        return sentences

    # Nothing splittable - return as a single step rather than nothing
    return [text]


def get_application_steps(scheme):
    """
    Returns:
      {
        "steps": ["step 1 text", "step 2 text", ...],
        "source": "curated" | "extracted" | "generic_fallback"
      }
    """
    scheme_id = scheme.get('scheme_id')
    if scheme_id in APPLICATION_STEPS_OVERRIDES:
        return {"steps": APPLICATION_STEPS_OVERRIDES[scheme_id], "source": "curated"}

    raw_text = scheme.get('application_process_summary') or ''
    if raw_text.strip():
        steps = _split_free_text_into_steps(raw_text)
        if steps:
            return {"steps": steps, "source": "extracted"}

    return {"steps": list(GENERIC_FALLBACK_STEPS), "source": "generic_fallback"}
