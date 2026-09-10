"""
FEATURE 4: Document readiness checklist.

Compares the documents the user says they ALREADY have against a scheme's
documents_required list. Needs one explicit input from the user (which
documents they own) since the system can't know this on its own - the
matching/UI layer should collect this via a simple multi-select checkbox
form (common doc names repeat heavily across schemes, so a fixed checklist
works better than free text).

Fuzzy-ish matching handles the fact that documents_required text is scraped/
free-form ("Aadhaar Card" vs "Aadhar card copy" vs "Aadhaar") rather than a
fixed enum.
"""
import re

# Canonical document types -> regex patterns that catch common phrasings
# across the dataset. Add more as new document phrasings show up in the data.
DOCUMENT_CANON = {
    "aadhaar": r'\baadhaa?r\b',
    "income_certificate": r'\bincome\s*certificate\b',
    "caste_certificate": r'\b(?:caste|category)\s*certificate\b',
    "bank_passbook": r'\bbank\s*(?:passbook|account\s*(?:details|statement))\b',
    "pan_card": r'\bpan\s*card\b',
    "domicile_certificate": r'\bdomicile\s*certificate\b',
    "disability_certificate": r'\b(?:disability|udid)\s*certificate\b',
    "project_report": r'\b(?:detailed\s*)?project\s*report\b',
    "photograph": r'\bphotograph|passport.?size\s*photo\b',
    "ration_card": r'\bration\s*card\b',
    "bpl_certificate": r'\bbpl\s*(?:certificate|card)\b',
    "birth_certificate": r'\bbirth\s*certificate\b',
    "education_certificate": r'\b(?:education|mark\s*sheet|degree)\s*certificate\b',
    "residence_proof": r'\b(?:residence|address)\s*proof\b',
    "bank_guarantee": r'\bbank\s*guarantee\b',
}

CANON_LABELS = {
    "aadhaar": "Aadhaar Card",
    "income_certificate": "Income Certificate",
    "caste_certificate": "Caste/Category Certificate",
    "bank_passbook": "Bank Passbook/Account Details",
    "pan_card": "PAN Card",
    "domicile_certificate": "Domicile Certificate",
    "disability_certificate": "Disability/UDID Certificate",
    "project_report": "Detailed Project Report",
    "photograph": "Passport-size Photograph",
    "ration_card": "Ration Card",
    "bpl_certificate": "BPL Certificate/Card",
    "birth_certificate": "Birth Certificate",
    "education_certificate": "Education/Mark Sheet Certificate",
    "residence_proof": "Residence/Address Proof",
    "bank_guarantee": "Bank Guarantee",
}


def canonicalize_document(doc_text):
    """Maps a raw documents_required string to a canonical key, or None if unrecognized."""
    if not doc_text:
        return None
    for canon_key, pattern in DOCUMENT_CANON.items():
        if re.search(pattern, doc_text, re.I):
            return canon_key
    return None


def get_canonical_checklist_options():
    """
    For the frontend: the fixed list of checkboxes to show the user ONCE
    ("which of these do you already have?"), rather than asking per-scheme.
    """
    return [{"key": k, "label": v} for k, v in CANON_LABELS.items()]


def check_document_readiness(scheme, user_owned_doc_keys):
    """
    scheme: a scheme dict with 'documents_required' (list of raw strings)
    user_owned_doc_keys: set/list of canonical keys the user checked off,
        e.g. {"aadhaar", "bank_passbook"}

    Returns:
      {
        "total_required": int,
        "ready_count": int,
        "ready": [{"key","label"}...],
        "missing": [{"key","label"}...],
        "unrecognized_requirements": [raw strings that couldn't be canonicalized]
      }
    """
    owned = set(user_owned_doc_keys or [])
    raw_docs = scheme.get('documents_required') or []
    if not isinstance(raw_docs, list):
        raw_docs = [raw_docs]

    ready, missing, unrecognized = [], [], []
    seen_keys = set()

    for raw in raw_docs:
        key = canonicalize_document(raw)
        if key is None:
            unrecognized.append(raw)
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entry = {"key": key, "label": CANON_LABELS[key]}
        if key in owned:
            ready.append(entry)
        else:
            missing.append(entry)

    total = len(ready) + len(missing)
    return {
        "total_required": total,
        "ready_count": len(ready),
        "ready": ready,
        "missing": missing,
        "unrecognized_requirements": unrecognized,
    }
