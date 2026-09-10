"""
Step: Normalize Kaggle CSV into our Tier-2 schema shape with complete, untruncated text fields.
Run: python3 normalize_tier2.py
Input:  data/tier2/raw/kaggle_dump.csv
Output: data/tier2/processed/schemes_broad.json
"""
import pandas as pd
import re
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier2', 'raw', 'kaggle_dump.csv')
OUT_PATH = os.path.join(BASE_DIR, '..', 'data', 'tier2', 'processed', 'schemes_broad.json')

df = pd.read_csv(CSV_PATH)

# --- Extraction Helpers ---

def extract_age_range(text):
    if pd.isna(text):
        return None, None
    t = str(text)
    m = re.search(r'(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*years?', t, re.I)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except ValueError:
            pass

    min_m = re.search(r'(?:minimum|at least|above|completed)\s*(?:age\s*of)?\s*(\d{1,2})\s*years?', t, re.I)
    max_m = re.search(r'(?:maximum|not exceed|below|up to|less than)\s*(?:age\s*of)?\s*(\d{1,2})\s*years?', t, re.I)
    min_a = int(min_m.group(1)) if min_m else None
    max_a = int(max_m.group(1)) if max_m else None
    return min_a, max_a

def extract_gender(text):
    if pd.isna(text):
        return "any"
    t = str(text).lower()
    if any(w in t for w in ['woman', 'women', 'female', 'girl', 'widow', 'mahila', 'mother', 'maternal', 'pregnant']):
        return "female"
    if re.search(r'\bmale\b', t) and 'female' not in t and 'women' not in t:
        return "male"
    return "any"

def parse_amount(num_s, unit_s=None):
    if not num_s:
        return None
    cleaned = num_s.replace(',', '').strip()
    if not cleaned:
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if unit_s:
        u = unit_s.lower().strip()
        if 'lakh' in u or 'lac' in u:
            val *= 100000
        elif 'crore' in u or 'cr' in u:
            val *= 10000000
        elif 'thousand' in u or 'k' in u:
            val *= 1000
    return val

def extract_income_range(text):
    """
    Handles both annual and monthly income ceilings/floors, and statutory ceilings (BPL, EWS, NCL, non-taxpayer).
    """
    if pd.isna(text):
        return None, None
    t = str(text)

    # 1. Range pattern: "between Rs 100000 and Rs 300000" or "Rs 1,00,000 to Rs 3,00,000"
    range_match = re.search(
        r'(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?\s*(?:to|and|-)\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?',
        t, re.I
    )
    if range_match:
        n1 = parse_amount(range_match.group(1), range_match.group(2))
        n2 = parse_amount(range_match.group(3), range_match.group(4))
        if n1 is not None and n2 is not None:
            return int(min(n1, n2)), int(max(n1, n2))

    # 2. Annual ceiling pattern
    annual_match = re.search(
        r'(?:annual|family|total|gross|household|parental|combined)?\s*(?:family|household)?\s*income\s*(?:from\s*all\s*sources)?\s*(?:should|must|shall|is|can)?\s*(?:not\s*exceed|not\s*be\s*more\s*than|below|up\s*to|less\s*than|is\s*up\s*to|within|limit\s*(?:is|of)?|ceiling\s*(?:is|of)?|maximum\s*(?:of)?|under|not\s*more\s*than|cannot\s*be\s*more\s*than)\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|thousand|k)?',
        t, re.I
    )
    if annual_match:
        val = parse_amount(annual_match.group(1), annual_match.group(2))
        if val is not None and 1000 <= val <= 50000000:
            return None, int(val)

    # 3. Monthly ceiling pattern
    monthly_match = re.search(
        r'(?:monthly|per\s*month)\s*(?:family|household|applicant\'?s?)?\s*income\s*(?:should|must|shall|is|can)?\s*(?:not\s*exceed|not\s*be\s*more\s*than|below|up\s*to|less\s*than|under|maximum|within|cannot\s*be\s*more\s*than)?\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?',
        t, re.I
    )
    if monthly_match:
        val = parse_amount(monthly_match.group(1), monthly_match.group(2))
        if val is not None and 100 <= val <= 200000:
            return None, int(val * 12)

    # 4. Statutory default ceilings
    if re.search(r'\b(?:below\s*poverty\s*line|bpl\s*family|bpl\s*card|bpl\s*category|antyodaya|annapurna|destitute\s*family|yellow\s*ration\s*card)\b', t, re.I):
        return None, 120000
    if re.search(r'\b(?:non-taxpayer|non-tax\s*payer|not\s*an\s*income\s*taxpayer|not\s*an\s*income\s*tax\s*payee|not\s*income\s*tax\s*assessee|should\s*not\s*be\s*an\s*income\s*tax\s*payer|not\s*paying\s*income\s*tax)\b', t, re.I):
        return None, 300000
    if re.search(r'\b(?:non-creamy\s*layer|non\s*creamy\s*layer|\bncl\b)\b', t, re.I):
        return None, 800000
    if re.search(r'\b(?:economically\s*weaker\s*section|ews\s*category|ews\s*certificate)\b', t, re.I):
        return None, 800000

    return None, None

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "Puducherry", "Jammu and Kashmir",
    "Ladakh", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep", "Andaman and Nicobar Islands"
]

def extract_state(text):
    if pd.isna(text):
        return "Not Specified"
    t = str(text)
    for state in INDIAN_STATES:
        if re.search(rf'\b{re.escape(state)}\b', t, re.I):
            return state
    return "Not Specified"

def extract_category(text):
    if pd.isna(text):
        return ["any"]
    t = str(text)
    found = []

    checks = {
        "SC": [r'\bSC\b', r'scheduled caste', r'dalit', r'adi dravidar', r'safai karamchari'],
        "ST": [r'\bST\b', r'scheduled tribe', r'adivasi', r'tribal'],
        "OBC": [r'\bOBC\b', r'backward class', r'other backward'],
        "EWS": [r'\bEWS\b', r'economically weaker', r'economically backward'],
    }
    for cat, patterns in checks.items():
        if any(re.search(p, t, re.I) for p in patterns):
            found.append(cat)

    return found if found else ["any"]

def parse_documents(doc_text):
    """Parses raw unstructured document requirements into a clean list of document items."""
    if pd.isna(doc_text):
        return []
    text = str(doc_text).strip()
    if not text:
        return []
    raw_lines = re.split(r'[\r\n•\*;]+|\d+\.\s*', text)
    docs = []
    for l in raw_lines:
        cleaned = l.strip(' -–—\t\r\n﻿')
        if len(cleaned) >= 3 and len(cleaned) <= 300:
            docs.append(cleaned)
    return docs if docs else [text]

def parse_tags(tag_text):
    """Parses comma or semicolon separated tags into a clean list."""
    if pd.isna(tag_text):
        return []
    text = str(tag_text).strip()
    if not text:
        return []
    return [t.strip() for t in re.split(r'[,;]', text) if t.strip()]

# --- Apply Extractions ---

df['min_age'], df['max_age'] = zip(*df['eligibility'].apply(extract_age_range))
df['gender'] = df['eligibility'].apply(extract_gender)
df['income_floor_annual'], df['income_ceiling_annual'] = zip(*df['eligibility'].apply(extract_income_range))

combined_text_for_category = (
    df['scheme_name'].fillna('') + " " +
    df['details'].fillna('') + " " +
    df['eligibility'].fillna('') + " " +
    df['benefits'].fillna('')
)
df['category'] = combined_text_for_category.apply(extract_category)

combined_text_for_state = (
    df['scheme_name'].fillna('') + " " +
    df['details'].fillna('') + " " +
    df['eligibility'].fillna('')
)
df['detected_state'] = combined_text_for_state.apply(extract_state)

print(f"Total rows in Kaggle dump: {len(df)}")

# --- Build Output with Complete, Untruncated Text ---
output = []
for _, row in df.iterrows():
    det_state = row['detected_state']
    if det_state != "Not Specified":
        state_val = det_state
    elif str(row.get('level', '')).strip().lower() == 'central':
        state_val = "All India"
    else:
        state_val = "Not Specified"

    slug = str(row['slug']).strip() if pd.notna(row['slug']) else ""
    official_link = f"https://www.myscheme.gov.in/schemes/{slug}" if slug else ""

    docs_list = parse_documents(row.get('documents'))
    tags_list = parse_tags(row.get('tags'))

    full_details = str(row['details']).strip() if pd.notna(row['details']) else ""
    full_benefits = str(row['benefits']).strip() if pd.notna(row['benefits']) else ""
    full_eligibility = str(row['eligibility']).strip() if pd.notna(row['eligibility']) else ""
    full_application = str(row['application']).strip() if pd.notna(row['application']) else ""
    scheme_cat = str(row['schemeCategory']).strip() if pd.notna(row['schemeCategory']) else "Not Specified"

    output.append({
        "scheme_id": f"TIER2-{slug}" if slug else f"TIER2-{_}",
        "scheme_name": str(row['scheme_name']).strip(),
        "level": str(row.get('level', 'Not Specified')).strip(),
        "state": state_val,
        "department": "Not Specified",
        "scheme_category": scheme_cat,
        "short_description": full_details,
        "eligibility": {
            "gender": row['gender'],
            "min_age": row['min_age'],
            "max_age": row['max_age'],
            "category": row['category'],
            "income_floor_annual": row['income_floor_annual'],
            "income_ceiling_annual": row['income_ceiling_annual'],
            "occupation": "not_specified",
            "business_type": "not_specified",
            "disability_status": "not_specified",
            "other_conditions": full_eligibility
        },
        "benefits_summary": full_benefits,
        "application_process_summary": full_application,
        "documents_required": docs_list,
        "tags": tags_list,
        "official_url": official_link,
        "last_verified_date": None,
        "verification_status": "unverified",
        "ai_inferred": True,
        "tier": 2
    })

def clean_nan(obj):
    """Recursively convert pandas NaN / float NaN to None so JSON stays valid."""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj

output = clean_nan(output)

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Saved {len(output)} normalized Tier-2 schemes with complete text to {OUT_PATH}")
