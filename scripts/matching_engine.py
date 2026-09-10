"""
The core matching engine: given a user's profile, find eligible schemes
and rank them using a multi-tiered sorting logic:
  - Tier 1: Highly Specific Matches (explicit demographic match for category, gender,
            disability, occupation, vulnerability, or minority; intersectional matches at top)
  - Tier 2: Broader/Parent Categories (e.g., General schemes for EWS applicants)
  - Tier 3: Universal/Open Schemes (schemes with no demographic restrictions)

Within each tier/sub-group, schemes are ranked internally by match_score descending.
Includes deep sentence-level constraint extraction and verification across structured fields,
'other_conditions', and 'notes' nodes.
"""
import re
import json

BLANK_VALUES = {None, "", "not specified", "not_specified", "none", "n/a", "na", "any"}
EMPTY_ELIGIBILITY_MESSAGE = "You are not eligible for any schemes at the moment."

# Statutory benchmark ceilings for government welfare programs
STATUTORY_CEILINGS = {
    "BPL": 120000.0,         # Below Poverty Line / Antyodaya / Yellow Ration Card
    "NON_TAXPAYER": 300000.0, # Non-income-tax-paying criteria
    "OBC_NCL": 800000.0,     # OBC Non-Creamy Layer standard ceiling
    "EWS": 800000.0          # Economically Weaker Section standard ceiling
}

# Canonicalizes the scheme's own STRUCTURED eligibility.occupation field
# (e.g. "Student", "Farmer", "Self Employed") to the same occupation keys
# used by the text regex (occ_map below), so a curated field can be
# trusted directly instead of only relying on free-text matching.
OCCUPATION_FIELD_CANON = {
    "student": r'\bstudents?\b',
    "farmer": r'\bfarmers?|agricultur(?:e|ist)\b',
    "entrepreneur": r'\bentrepreneurs?|self[- ]?employed|business(?:man|woman)?\b',
    "artisan": r'\bartisans?|weavers?|craftsm[ae]n\b',
    "sanitation_worker": r'\bsafai karamcharis?|sanitation workers?\b',
    "driver": r'\bdrivers?\b',
    "unemployed": r'\bunemployed|job seekers?\b',
}

# Weak / generic words that describe an ENTRY QUALIFICATION a scheme
# wants from applicants (e.g. "graduates from recognized universities")
# rather than the scheme actually being FOR students. Tracked separately
# as informational-only "hints" - never used for occupation targeting or
# ranking, only surfaced as extra detail (see bug-fix note further down).
QUALIFICATION_HINT_PATTERNS = {
    "graduate": r'\bgraduates?\b|\bgraduation\b|\bdegree\s+holders?\b',
    "postgraduate": r'\bpost[- ]?graduates?\b|\bpost[- ]?graduation\b',
    "phd": r'\bph\.?\s*d\.?\b|\bdoctorate\b',
    "matriculation": r'\bmatriculation\b|\b(?:10th|12th)\s*(?:pass|standard)\b',
    "college_or_university": r'\bcolleges?\b|\buniversit(?:y|ies)\b',
}


def is_unrestricted(value):
    """True if the scheme places no real restriction on this field."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in BLANK_VALUES
    if isinstance(value, (list, tuple, set)):
        if len(value) == 0:
            return True
        return all(is_unrestricted(v) for v in value)
    return False


def clean_amount(val_str, unit_str=''):
    """Safely convert currency string to float with unit multiplier."""
    if not val_str:
        return None
    val_str = str(val_str).replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    try:
        val = float(val_str)
        if unit_str:
            unit_lower = unit_str.lower()
            if 'lakh' in unit_lower or 'lac' in unit_lower:
                val = val * 100000.0
            elif 'crore' in unit_lower or 'cr' in unit_lower:
                val = val * 10000000.0
            elif 'thousand' in unit_lower or 'k' in unit_lower:
                val = val * 1000.0
        return val
    except (ValueError, TypeError):
        return None


def extract_constraints_from_text(scheme):
    """
    Deeply parses unstructured text across 'other_conditions', 'notes', and 'short_description'
    to extract unmapped constraints:
      - Age limits (range, min, max)
      - Income limits (annual ceiling, annual floor, monthly ceiling converted to annual)
      - Statutory income caps (BPL, Non-Taxpayer, EWS, OBC-NCL)
      - Disability requirements
      - Gender restrictions
      - Occupation / livelihood targeting
      - Vulnerability & marital status targeting (widows, divorced, single mothers, orphans, transgender)
      - Minority community targeting
      - Domicile / Area targeting (rural vs urban)
    """
    if not isinstance(scheme, dict):
        return {}

    elig = scheme.get('eligibility', {}) if isinstance(scheme.get('eligibility'), dict) else {}
    other_cond = elig.get('other_conditions') or ''
    notes = scheme.get('notes') or ''
    desc = scheme.get('short_description') or ''
    # BUG FIX: scheme_name was never included in the text scanned for
    # constraints. Many schemes state their gender/target-group restriction
    # only in the title itself (e.g. "Post Doctoral Fellowship To Women
    # Candidates") without repeating "women"/"female" anywhere in
    # other_conditions/notes/short_description - so those schemes were
    # silently treated as gender-unrestricted and shown to everyone.
    name = scheme.get('scheme_name') or ''
    combined = f"{name} {other_cond} {notes} {desc}"

    if not combined.strip():
        return {}

    extracted = {}

    # 1. Age Range: e.g. '18 to 50 years', 'between 18 and 45 years', '18-35 years'
    m_range = re.search(r'\b(?:aged?\s*(?:between)?\s*)?(\d{1,2})\s*(?:-|to|and)\s*(\d{1,2})\s*years?\b', combined, re.I)
    if m_range:
        extracted['min_age'] = float(m_range.group(1))
        extracted['max_age'] = float(m_range.group(2))

    # Min Age: e.g. 'above 21 years', 'at least 18 years', 'minimum age of 18', 'age should be 18 years and above'
    if 'min_age' not in extracted:
        m_min = re.search(r'\b(?:above|at least|minimum\s*age\s*(?:of|is)?|more than|completed)\s*(\d{1,2})\s*years?\b', combined, re.I)
        if m_min:
            extracted['min_age'] = float(m_min.group(1))

    # Max Age: e.g. 'below 35 years', 'up to 50 years', 'maximum age of 52', 'not exceed 45 years', 'less than 18 years'
    if 'max_age' not in extracted:
        m_max = re.search(r'\b(?:below|up to|maximum\s*age\s*(?:of|is)?|not\s*exceed(?:ing)?|less than|attain\s*the\s*age\s*of)\s*(\d{1,2})\s*years?\b', combined, re.I)
        if m_max:
            extracted['max_age'] = float(m_max.group(1))

    # 2. Income Ranges & Ceilings
    # 2a. Range: "between Rs 100000 and Rs 300000" or "Rs 50,000 to Rs 1.5 Lakh"
    m_inc_range = re.search(
        r'(?:family|annual|household|monthly)?\s*income\s*(?:from\s*all\s*sources)?\s*(?:is|should\s*be|must\s*be|between)?\s*(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?\s*(?:to|and|-)\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?',
        combined, re.I
    )
    if m_inc_range:
        v1 = clean_amount(m_inc_range.group(1), m_inc_range.group(2))
        v2 = clean_amount(m_inc_range.group(3), m_inc_range.group(4))
        if v1 and v2:
            extracted['income_floor_annual'] = min(v1, v2)
            extracted['income_ceiling_annual'] = max(v1, v2)

    # 2b. Monthly Ceiling: "monthly household income should not exceed Rs. 10,000" -> annual ceiling = 120,000
    if 'income_ceiling_annual' not in extracted:
        m_monthly = re.search(
            r'(?:monthly|per\s*month)\s*(?:family|household|applicant\'?s?|student\'?s?|parents?\'?)?\s*income\s*(?:from\s*all\s*sources)?\s*(?:should|must|shall|is|can)?\s*(?:not\s*exceed|not\s*be\s*more\s*than|below|up\s*to|less\s*than|under|maximum|within|cannot\s*be\s*more\s*than)?\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?',
            combined, re.I
        )
        if m_monthly:
            v = clean_amount(m_monthly.group(1), m_monthly.group(2))
            if v and 100 <= v <= 200000:
                extracted['income_ceiling_annual'] = v * 12.0

    # 2c. Annual Ceiling: "annual family income not exceed Rs. 3,00,000", "income up to ₹2.5 Lakh"
    if 'income_ceiling_annual' not in extracted:
        m_annual = re.search(
            r'(?:annual|family|gross|household|parental|combined|total)?\s*(?:family|household|applicant\'?s?|student\'?s?|candidate\'?s?|parents?\'?)?\s*income\s*(?:from\s*all\s*sources)?\s*(?:should|must|shall|is|can)?\s*(?:not\s*exceed|not\s*be\s*more\s*than|below|up\s*to|less\s*than|is\s*up\s*to|within|limit\s*(?:is|of)?|ceiling\s*(?:is|of)?|maximum\s*(?:of)?|under|not\s*more\s*than|cannot\s*be\s*more\s*than)\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|thousand|k)?',
            combined, re.I
        )
        if m_annual:
            v = clean_amount(m_annual.group(1), m_annual.group(2))
            if v and 1000 <= v <= 50000000:
                extracted['income_ceiling_annual'] = v

    # 2d. Statutory Ceilings (BPL, Non-Taxpayer, EWS, OBC-NCL)
    if 'income_ceiling_annual' not in extracted:
        if re.search(r'\b(?:below\s*poverty\s*line|bpl\s*family|bpl\s*card|bpl\s*category|antyodaya|annapurna|destitute\s*family|yellow\s*ration\s*card|economically\s*poor\s*family)\b', combined, re.I):
            extracted['income_ceiling_annual'] = STATUTORY_CEILINGS["BPL"]
        elif re.search(r'\b(?:non-taxpayer|non-tax\s*payer|not\s*an\s*income\s*taxpayer|not\s*an\s*income\s*tax\s*payee|not\s*income\s*tax\s*assessee|should\s*not\s*be\s*an\s*income\s*tax\s*payer|not\s*paying\s*income\s*tax)\b', combined, re.I):
            extracted['income_ceiling_annual'] = STATUTORY_CEILINGS["NON_TAXPAYER"]
        elif re.search(r'\b(?:non-creamy\s*layer|non\s*creamy\s*layer|\bncl\b)\b', combined, re.I):
            extracted['income_ceiling_annual'] = STATUTORY_CEILINGS["OBC_NCL"]
        elif re.search(r'\b(?:economically\s*weaker\s*section|ews\s*category|ews\s*certificate)\b', combined, re.I):
            extracted['income_ceiling_annual'] = STATUTORY_CEILINGS["EWS"]

    # 2e. Income Floor: "income must be at least Rs. 50,000"
    if 'income_floor_annual' not in extracted:
        m_inc_floor = re.search(
            r'(?:family\s*)?(?:annual\s*)?income\s*(?:must|should)?\s*(?:be\s*)?(?:at\s*least|minimum|more than)\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|thousand)?',
            combined, re.I
        )
        if m_inc_floor:
            floor_val = clean_amount(m_inc_floor.group(1), m_inc_floor.group(2) or '')
            if floor_val and floor_val >= 1000:
                extracted['income_floor_annual'] = floor_val

    # 3. Disability requirement from text
    if re.search(r'(?:disability\s*(?:of\s*)?(?:at\s*least)?\s*\d+%|minimum\s*\d+%\s*disability|person[s]?\s*with\s*disabilit(?:y|ies)|differently\s*abled|physically\s*handicapped|udid\s*(?:card|number)|hearing\s*impaired|locomotor\s*disabled|\bblind\b|\bdeaf\b|\bpwd\b)', combined, re.I):
        if not re.search(r'disability is NOT a general eligibility', combined, re.I):
            extracted['disability_required'] = True

    # 4. Gender restriction from text
    # BUG FIX v1: the old pattern only caught very narrow phrasing like "for
    # women only" / "female candidates only", so common real-world phrasing
    # like "Post Doctoral Fellowship To Women Candidates" or "for women"
    # (without the word "only") matched nothing and the scheme was treated
    # as open to everyone, including men. Broadened the pattern to catch
    # generic women/female/girl-child targeting, while explicitly excluding
    # unisex phrasing ("both men and women", "all genders") so genuinely
    # open schemes that merely mention women as one eligible group aren't
    # wrongly restricted.
    # BUG FIX v2: the broadened generic patterns ("for women", "to women")
    # then caused a NEW false positive - schemes that are open to everyone
    # but give women an extra financial perk (e.g. "beneficiaries are
    # charged 4% p.a.; Women receive an interest rebate of 0.5%") matched
    # "for women"/"to women"-style wording purely by coincidence of a rebate
    # clause, and got wrongly locked to female-only. Fixed by checking
    # clause-by-clause: the strong, unambiguous indicators (widow, mahila,
    # "women candidates", etc.) still apply anywhere; but the generic "for
    # women" / "to women" phrasing only counts as a real restriction if that
    # SAME clause isn't describing a rebate/concession/discount/subsidy (an
    # extra benefit implies the base scheme is open to everyone, not
    # exclusive to women).
    is_unisex_phrasing = re.search(
        r'\b(?:both\s+men\s+and\s+women|men\s+and\s+women|male\s+and\s+female|all\s+genders?|irrespective\s+of\s+gender|any\s+gender)\b',
        combined, re.I
    )
    # If the text ALSO explicitly addresses men anywhere (e.g. a rate table
    # listing "...4% p.a. for Women, 5% p.a. for Men" without a neat
    # parenthetical or the word "rebate"), that alone proves the scheme
    # isn't female-exclusive - men are being given their own terms, not
    # excluded. This catches differential-rate phrasings that don't match
    # the dual-rate-parenthesis or rebate/concession/discount checks below.
    mentions_men_too = bool(re.search(r'\bfor\s+men\b', combined, re.I))

    strong_female_signal = re.search(
        r'\b(?:women\s+entrepreneurs|women\s+candidates|female\s+candidates(?:\s+only)?|widows?|single\s+mothers?|girls?(?:\s+only)?|mahila|for\s+girls?|scheme\s+for\s+women)\b',
        combined, re.I
    )
    is_female_targeted = bool(strong_female_signal)
    if not is_female_targeted and not mentions_men_too:
        for clause in re.split(r'[,.;]', combined):
            if not re.search(r'\b(?:for\s+women(?:\s+only)?|only\s+for\s+women|to\s+women|for\s+female)\b', clause, re.I):
                continue
            has_benefit_word = re.search(r'rebate|concession|discount|subsidy', clause, re.I)
            # A "X% (Y% for Women)" differential-rate statement is also just
            # a benefit, not an eligibility restriction, even though it has
            # no "rebate"/"concession" word - catch that pattern explicitly.
            has_dual_rate_pattern = re.search(r'\d+(?:\.\d+)?\s*%\s*\(\s*\d+(?:\.\d+)?\s*%\s*for\s*wom[ae]n\s*\)', clause, re.I)
            if not has_benefit_word and not has_dual_rate_pattern:
                is_female_targeted = True
                break
    if is_female_targeted and not is_unisex_phrasing:
        extracted['gender_restricted'] = 'female'

    # 5. Autonomous Feature: Occupation / Livelihood Targeting
    # BUG FIX: "student" used to also match weak/generic words like
    # "college", "university", "graduate", "phd" - those describe an ENTRY
    # QUALIFICATION a scheme wants from applicants (e.g. Agri-Clinics wants
    # "graduates from ... universities recognized by ICAR/UGC" as one
    # criterion for what is actually a farmer/entrepreneur scheme), not
    # that the scheme targets students as a group. That false match let
    # Agri-Clinics tie with the real Educational Loan Scheme on a
    # student's goal and get sorted above it.
    # Only strong, unambiguous "this scheme is FOR students" words count
    # for occupation targeting now. The weak qualification words are still
    # captured, but separately, as informational-only hints (see below) -
    # they never drive matching or ranking, only extra detail text.
    occ_map = {
        "student": r'\b(?:students?|studying|scholarships?|fellowships?)\b',
        "farmer": r'\b(?:farmers?|agriculture|kisan|krishi|crops?|cultivators?|horticulture|dairy|livestock|fisheries|fisherm[ae]n)\b',
        "entrepreneur": r'\b(?:entrepreneurs?|startups?|msme|small business|enterprise|self[- ]employed|micro enterprise|shopkeepers?|vendors?)\b',
        "artisan": r'\b(?:artisans?|weavers?|craftsm[ae]n|handicrafts?|handloom|potters?|carpenters?|leather workers?|blacksmiths?)\b',
        "sanitation_worker": r'\b(?:safai karamcharis?|sanitation workers?|manual scavengers?|waste pickers?)\b',
        "driver": r'\b(?:drivers?|auto rickshaws?|taxi drivers?|commercial vehicle drivers?)\b'
    }
    for occ_name, occ_pat in occ_map.items():
        if re.search(occ_pat, combined, re.I):
            extracted[f"target_occupation_{occ_name}"] = True

    # FEATURE: the scheme's own curated/structured eligibility.occupation
    # field (e.g. ELS is hand-tagged "Student") is trusted directly when
    # present, as a UNION with the regex result above - it can only ADD a
    # missed occupation tag, never remove one the regex found, so it can't
    # introduce a new false positive on its own.
    raw_occ_field = elig.get('occupation')
    if not is_unrestricted(raw_occ_field):
        occ_field_text = str(raw_occ_field).strip().lower()
        for canon_key, field_pat in OCCUPATION_FIELD_CANON.items():
            if re.search(field_pat, occ_field_text, re.I):
                extracted[f"target_occupation_{canon_key}"] = True

    # FEATURE: weak qualification-type words (graduate/PhD/college/
    # university/matriculation) are recorded separately as informational
    # "hints" only - e.g. so the UI can show "also expects a graduate
    # degree" - but they never count toward occupation targeting or
    # ranking (that's the exact bug fixed above).
    for hint_name, hint_pat in QUALIFICATION_HINT_PATTERNS.items():
        if re.search(hint_pat, combined, re.I):
            extracted[f"qualification_hint_{hint_name}"] = True

    # BUG FIX: "unemployed" used to be just another entry in occ_map with a
    # bare '\bunemployed\b' alternative, so ANY scheme that mentioned the
    # word "unemployed" even once in passing (e.g. a PhD fellowship's text
    # "...to those candidates who are unemployed holding Ph.D. degrees...")
    # got tagged as targeting job-seekers, and then outranked genuine
    # job-seeker schemes for a user who selected "Unemployed / Job Seeker".
    # Fix: (a) require stronger, more specific phrasing than the bare word
    # "unemployed", and (b) only apply the unemployed tag when no other,
    # more specific occupation (student/farmer/entrepreneur/etc.) already
    # matched - a PhD fellowship is a student scheme first, not a
    # job-seeker scheme, even if "unemployed" appears once in its text.
    specific_occ_matched = any(
        extracted.get(f"target_occupation_{occ_name}") for occ_name in occ_map
    )
    unemployed_pattern = (
        r'\b(?:unemployed\s+youth|unemployed\s+persons?|unemployed\s+individuals?|'
        r'unemployed\s+graduates?|job\s+seekers?|registered\s+job\s+seekers?|'
        r'skill\s+development|vocational\s+training|employment\s+generation)\b'
    )
    if not specific_occ_matched and re.search(unemployed_pattern, combined, re.I):
        extracted["target_occupation_unemployed"] = True

    # 6. Autonomous Feature: Vulnerability & Marital Status Targeting
    if re.search(r'\b(?:widow|widowed|destitute widow)\b', combined, re.I):
        extracted['target_vulnerability_widow'] = True
    if re.search(r'\b(?:divorced|deserted|separated woman|abandoned woman)\b', combined, re.I):
        extracted['target_vulnerability_divorced_deserted'] = True
    if re.search(r'\b(?:single mother|unwed mother)\b', combined, re.I):
        extracted['target_vulnerability_single_mother'] = True
    if re.search(r'\b(?:orphan|destitute child|parentless child)\b', combined, re.I):
        extracted['target_vulnerability_orphan'] = True
    if re.search(r'\b(?:transgender|third gender|\btg\b)\b', combined, re.I):
        extracted['target_vulnerability_transgender'] = True

    # 7. Autonomous Feature: Minority Targeting
    if re.search(r'\b(?:minority community|minority communities|muslim|christian|sikh|buddhist|jain|parsi|zoroastrian)\b', combined, re.I):
        extracted['target_minority'] = True

    # 8. Autonomous Feature: Area Domicile Targeting (Rural / Urban)
    if re.search(r'\b(?:rural area|rural areas|gramin|gram panchayat|village level)\b', combined, re.I) and not re.search(r'both rural and urban', combined, re.I):
        extracted['area_restricted'] = 'rural'
    elif re.search(r'\b(?:urban area|urban areas|municipal corporation|city level)\b', combined, re.I) and not re.search(r'both rural and urban', combined, re.I):
        extracted['area_restricted'] = 'urban'

    return extracted


def get_resolved_constraints(scheme):
    """
    Returns effective constraints for a scheme by merging structured eligibility
    fields with deep constraints extracted from 'other_conditions' and 'notes'.
    """
    if not isinstance(scheme, dict):
        return {}

    elig = scheme.get('eligibility', {}) if isinstance(scheme.get('eligibility'), dict) else {}
    extracted = extract_constraints_from_text(scheme)

    # Min Age
    min_age = None
    raw_min_age = elig.get('min_age')
    if not is_unrestricted(raw_min_age):
        try:
            min_age = float(raw_min_age)
        except (ValueError, TypeError):
            pass
    if min_age is None and 'min_age' in extracted:
        min_age = extracted['min_age']

    # Max Age
    max_age = None
    raw_max_age = elig.get('max_age')
    if not is_unrestricted(raw_max_age):
        try:
            max_age = float(raw_max_age)
        except (ValueError, TypeError):
            pass
    if max_age is None and 'max_age' in extracted:
        max_age = extracted['max_age']

    # Income Floor
    income_floor = None
    raw_floor = elig.get('income_floor_annual')
    if not is_unrestricted(raw_floor):
        try:
            income_floor = float(raw_floor)
        except (ValueError, TypeError):
            pass
    if income_floor is None and 'income_floor_annual' in extracted:
        income_floor = extracted['income_floor_annual']

    # Income Ceiling
    income_ceiling = None
    raw_ceiling = elig.get('income_ceiling_annual')
    if not is_unrestricted(raw_ceiling):
        try:
            income_ceiling = float(raw_ceiling)
        except (ValueError, TypeError):
            pass
    if income_ceiling is None and 'income_ceiling_annual' in extracted:
        income_ceiling = extracted['income_ceiling_annual']

    # Disability Status
    disability_required = False
    raw_disability = elig.get('disability_status')
    if isinstance(raw_disability, str) and raw_disability.strip().lower() == 'yes':
        disability_required = True
    elif extracted.get('disability_required'):
        disability_required = True

    # Gender
    gender_restricted = None
    raw_gender = elig.get('gender')
    if not is_unrestricted(raw_gender):
        gender_restricted = str(raw_gender).strip().lower()
    elif extracted.get('gender_restricted'):
        gender_restricted = extracted['gender_restricted']

    # Category
    categories = []
    raw_categories = elig.get('category')
    if not is_unrestricted(raw_categories):
        cats = raw_categories if isinstance(raw_categories, (list, tuple, set)) else [raw_categories]
        categories = [str(c).strip().upper() for c in cats if not is_unrestricted(c)]

    return {
        "min_age": min_age,
        "max_age": max_age,
        "income_floor": income_floor,
        "income_ceiling": income_ceiling,
        "disability_required": disability_required,
        "gender_restricted": gender_restricted,
        "categories": categories,
        "area_restricted": extracted.get('area_restricted'),
        "target_minority": extracted.get('target_minority', False),
        "target_vulnerabilities": {
            "widow": extracted.get('target_vulnerability_widow', False),
            "divorced_deserted": extracted.get('target_vulnerability_divorced_deserted', False),
            "single_mother": extracted.get('target_vulnerability_single_mother', False),
            "orphan": extracted.get('target_vulnerability_orphan', False),
            "transgender": extracted.get('target_vulnerability_transgender', False)
        },
        "target_occupations": {
            k.replace('target_occupation_', ''): True
            for k in extracted if k.startswith('target_occupation_')
        },
        # Informational only (see extract_constraints_from_text) - never
        # used for matching/scoring/ranking, just extra detail for the UI.
        "qualification_hints": sorted(
            k.replace('qualification_hint_', '') for k in extracted
            if k.startswith('qualification_hint_')
        )
    }


def sanitize_user(user):
    """
    Sanitize and extract user profile fields safely with defaults and type conversions.
    Supports exact numeric income, structured sub-ranges, and autonomous demographic traits.
    """
    if not isinstance(user, dict):
        user = {}

    # Gender
    gender_raw = user.get('gender')
    gender = str(gender_raw).strip().lower() if gender_raw is not None else ""

    # Age
    age_raw = user.get('age')
    age = None
    if age_raw is not None and str(age_raw).strip() != "":
        try:
            age = float(age_raw)
        except (ValueError, TypeError):
            age = None

    # Category
    cat_raw = user.get('category')
    category = str(cat_raw).strip().upper() if cat_raw is not None else ""

    # Annual Income (handles numeric, string numbers, or interval strings)
    # Checks both 'annual_income' and 'income_sub_range'
    income_raw = user.get('annual_income')
    if income_raw is None or str(income_raw).strip() == "":
        income_raw = user.get('income_sub_range')

    annual_income = None
    if income_raw is not None and str(income_raw).strip() != "":
        try:
            annual_income = float(income_raw)
        except (ValueError, TypeError):
            # Check for range string e.g. "125000-150000"
            m_range = re.search(r'([\d.]+)\s*-\s*([\d.]+)', str(income_raw))
            if m_range:
                try:
                    # Use upper limit of interval for conservative eligibility verification
                    annual_income = float(m_range.group(2))
                except (ValueError, TypeError):
                    annual_income = None

    # Disability
    disability_raw = user.get('disability', False)
    if isinstance(disability_raw, bool):
        disability = disability_raw
    elif isinstance(disability_raw, str):
        disability = disability_raw.strip().lower() in ('true', '1', 'yes', 'y')
    elif isinstance(disability_raw, (int, float)):
        disability = bool(disability_raw)
    else:
        disability = False

    # State
    state_raw = user.get('state')
    state = str(state_raw).strip() if state_raw is not None and str(state_raw).strip() != "" else "All India"

    # Occupation (Autonomous feature 1)
    occ_raw = user.get('occupation')
    occupation = str(occ_raw).strip().lower() if occ_raw is not None else ""

    # Marital & Vulnerability Status (Autonomous feature 2)
    vuln_raw = user.get('marital_status') or user.get('vulnerability') or ""
    vulnerability = str(vuln_raw).strip().lower() if vuln_raw else ""
    is_widow = bool(user.get('is_widow') or 'widow' in vulnerability)
    is_single_mother = bool(user.get('is_single_mother') or 'single mother' in vulnerability)
    is_divorced_deserted = bool(user.get('is_divorced') or 'divorced' in vulnerability or 'deserted' in vulnerability)
    is_orphan = bool(user.get('is_orphan') or 'orphan' in vulnerability)
    is_transgender = bool(gender == 'transgender' or user.get('is_transgender'))

    # Minority & Domicile (Autonomous feature 3)
    is_minority = bool(user.get('is_minority') or user.get('minority'))
    area_raw = user.get('area') or user.get('domicile') or ""
    area = str(area_raw).strip().lower() if area_raw else "any"

    return {
        "gender": gender,
        "age": age,
        "category": category,
        "annual_income": annual_income,
        "income_sub_range": annual_income,
        "disability": disability,
        "state": state,
        "occupation": occupation,
        "is_widow": is_widow,
        "is_single_mother": is_single_mother,
        "is_divorced_deserted": is_divorced_deserted,
        "is_orphan": is_orphan,
        "is_transgender": is_transgender,
        "is_minority": is_minority,
        "area": area
    }


def is_eligible(user, scheme):
    """
    Returns (eligible: bool, reasons_failed: list[str])
    Verifies user eligibility against all resolved scheme constraints.
    """
    if not isinstance(scheme, dict):
        return False, ["Invalid scheme data"]

    u = sanitize_user(user)
    constraints = get_resolved_constraints(scheme)
    failed = []

    # --- Gender check ---
    req_gender = constraints.get('gender_restricted')
    if req_gender:
        if u['gender'] and req_gender != u['gender']:
            failed.append(f"Gender restricted to {req_gender}")
        elif not u['gender']:
            failed.append(f"Gender restricted to {req_gender}")

    # --- Age check ---
    min_age = constraints.get('min_age')
    max_age = constraints.get('max_age')
    if min_age is not None:
        if u['age'] is not None and u['age'] < min_age:
            failed.append(f"Minimum age is {min_age}")

    if max_age is not None:
        if u['age'] is not None and u['age'] > max_age:
            failed.append(f"Maximum age is {max_age}")

    # --- Category check (with sub-category to parent category support) ---
    cats_upper = constraints.get('categories', [])
    if cats_upper:
        user_cat = u['category']
        is_cat_match = False

        if user_cat in cats_upper:
            is_cat_match = True
        elif user_cat == 'EWS' and 'GENERAL' in cats_upper:
            is_cat_match = True
        elif 'ANY' in cats_upper:
            is_cat_match = True

        if not is_cat_match:
            failed.append(f"Category restricted to {cats_upper}")

    # --- Income check (floor AND ceiling) ---
    income_floor = constraints.get('income_floor')
    income_ceiling = constraints.get('income_ceiling')

    if income_floor is not None:
        if u['annual_income'] is not None and u['annual_income'] < income_floor:
            failed.append(f"Income must be at least Rs.{income_floor}")

    if income_ceiling is not None:
        if u['annual_income'] is not None and u['annual_income'] > income_ceiling:
            failed.append(f"Income must not exceed Rs.{income_ceiling}")

    # --- Disability check ---
    if constraints.get('disability_required'):
        if not u['disability']:
            failed.append("Scheme requires disability status")

    # --- Area check (Rural / Urban) ---
    req_area = constraints.get('area_restricted')
    if req_area and u['area'] not in ('any', ''):
        if req_area != u['area']:
            failed.append(f"Scheme is restricted to {req_area} areas")

    # --- State check ---
    user_state = u['state']
    scheme_level = str(scheme.get('level') or 'Central').strip()
    scheme_state = str(scheme.get('state') or 'All India').strip()

    if user_state.lower() == "all india":
        if scheme_level.lower() == "state":
            failed.append("This is a state-specific scheme, not applicable for 'All India'")
    else:
        if scheme_level.lower() == "state" and scheme_state.lower() != user_state.lower():
            failed.append(f"State-specific scheme, not confirmed for {user_state}")

    return (len(failed) == 0, failed)


def match_score(user, scheme):
    """
    Calculates match score: each validated constraint adds +1.
    Includes autonomous demographic & occupation boosts.
    """
    if not isinstance(scheme, dict):
        return 0

    u = sanitize_user(user)
    constraints = get_resolved_constraints(scheme)
    score = 0
    if constraints.get('gender_restricted'):
        score += 1
    if constraints.get('min_age') is not None:
        score += 1
    if constraints.get('max_age') is not None:
        score += 1
    if constraints.get('categories'):
        score += 1
    if constraints.get('income_floor') is not None:
        score += 1
    if constraints.get('income_ceiling') is not None:
        score += 1
    if constraints.get('disability_required'):
        score += 1

    # Occupation match boost
    user_occ = u.get('occupation')
    if user_occ and constraints.get('target_occupations', {}).get(user_occ):
        score += 1

    # Vulnerability match boost
    vulns = constraints.get('target_vulnerabilities', {})
    if (u.get('is_widow') and vulns.get('widow')) or \
       (u.get('is_divorced_deserted') and vulns.get('divorced_deserted')) or \
       (u.get('is_single_mother') and vulns.get('single_mother')) or \
       (u.get('is_orphan') and vulns.get('orphan')) or \
       (u.get('is_transgender') and vulns.get('transgender')):
        score += 1

    # Minority match boost
    if u.get('is_minority') and constraints.get('target_minority'):
        score += 1

    return score


def classify_demographic_tier(user, scheme):
    """
    Classifies an eligible scheme into one of three demographic tiers:
      - Tier 1 (Highly Specific Matches): Explicitly matches user's specific category,
        gender, disability status, occupation, vulnerability trait, or minority status.
        Intersectional matches (multiple traits) are tracked and ranked at the top.
      - Tier 2 (Broader/Parent Categories): Broader category match (e.g. General category scheme
        for an EWS user) without specific gender/disability/vulnerability targeting.
      - Tier 3 (Universal/Open Schemes): Schemes where anyone can apply without demographic restrictions.

    Returns:
      (tier: int, specific_trait_count: int, matched_traits: list[str])
    """
    u = sanitize_user(user)
    constraints = get_resolved_constraints(scheme)

    cats_upper = constraints.get('categories', [])
    req_gender = constraints.get('gender_restricted')
    req_disability = constraints.get('disability_required', False)

    # Specific category match
    cat_specific_match = bool(u['category'] and u['category'] in cats_upper)

    # Broader category match (EWS -> General)
    cat_broader_match = bool(u['category'] == 'EWS' and not cat_specific_match and 'GENERAL' in cats_upper)

    # Gender match
    gender_specific_match = bool(req_gender and u['gender'] and req_gender == u['gender'])

    # Disability match
    disability_specific_match = bool(req_disability and u['disability'])

    # Autonomous Feature 1: Occupation specific match
    user_occ = u.get('occupation')
    occ_specific_match = bool(user_occ and constraints.get('target_occupations', {}).get(user_occ))

    # Autonomous Feature 2: Vulnerability specific match
    vulns = constraints.get('target_vulnerabilities', {})
    vuln_specific_matches = []
    if u.get('is_widow') and vulns.get('widow'):
        vuln_specific_matches.append('vulnerability:widow')
    if u.get('is_divorced_deserted') and vulns.get('divorced_deserted'):
        vuln_specific_matches.append('vulnerability:divorced_deserted')
    if u.get('is_single_mother') and vulns.get('single_mother'):
        vuln_specific_matches.append('vulnerability:single_mother')
    if u.get('is_orphan') and vulns.get('orphan'):
        vuln_specific_matches.append('vulnerability:orphan')
    if u.get('is_transgender') and vulns.get('transgender'):
        vuln_specific_matches.append('vulnerability:transgender')

    # Autonomous Feature 3: Minority specific match
    minority_specific_match = bool(u.get('is_minority') and constraints.get('target_minority'))

    matched_traits = []
    if cat_specific_match:
        matched_traits.append(f"category:{u['category']}")
    if gender_specific_match:
        matched_traits.append(f"gender:{u['gender']}")
    if disability_specific_match:
        matched_traits.append("disability")
    if occ_specific_match:
        matched_traits.append(f"occupation:{user_occ}")
    matched_traits.extend(vuln_specific_matches)
    if minority_specific_match:
        matched_traits.append("minority")

    specific_count = len(matched_traits)

    if specific_count > 0:
        return 1, specific_count, matched_traits
    elif cat_broader_match:
        return 2, 0, ["parent_category:GENERAL"]
    else:
        return 3, 0, []


def split_urls(url_field):
    """Split concatenated URLs into a clean list."""
    if not url_field:
        return []
    return [u.strip() for u in str(url_field).split(' / ') if u.strip()]


def extract_financial_terms(scheme):
    """
    FEATURE: Financial Calculator support. Pulls interest rate (including
    gender-based rebates) and repayment tenure out of unstructured text
    (benefits_summary / eligibility.other_conditions / notes /
    short_description), since these are almost never in a structured field.

    Returns None if nothing usable was found (per the requirement: schemes
    with no rate/tenure info should NOT show a calculator at all).

    Returns a dict like:
      {
        "interest_rate_default": 8.0,      # % p.a., the rate that applies by default
        "interest_rate_female": 3.5,       # % p.a., only present if a distinct
                                            #   women's rate/rebate was found
        "interest_rate_range": (6.5, 8.0), # only present if text gave a "X% to Y%" range
        "tenure_years": 7                  # repayment period in years, if found
      }
    """
    elig = scheme.get('eligibility', {}) if isinstance(scheme.get('eligibility'), dict) else {}
    text = " ".join(filter(None, [
        scheme.get('benefits_summary') or '',
        elig.get('other_conditions') or '',
        scheme.get('notes') or '',
        scheme.get('short_description') or ''
    ]))
    if not text.strip():
        return None

    # 0. Direct dual-rate parenthetical pattern - the cleanest and most
    # explicit format found in the data, e.g. "chargeable at 11% (10% for
    # Women)". Checked FIRST because when present it's unambiguous, unlike
    # the multi-actor funding-chain text these schemes often ALSO contain
    # (NSFDC-to-NBFC rate, NBFC-to-beneficiary rate, subvention rate, etc.
    # all in the same paragraph).
    base_rate = None
    female_rate = None
    dual_m = re.search(r'(\d+(?:\.\d+)?)\s*%\s*\(\s*(\d+(?:\.\d+)?)\s*%\s*for\s*wom[ae]n\s*\)', text, re.I)
    if dual_m:
        base_rate = float(dual_m.group(1))
        female_rate = float(dual_m.group(2))

    # 1. Base/default interest rate (only if step 0 didn't already resolve it).
    # ACCURACY FIX (v2): pure positional "nearest % to any "beneficiar"
    # mention across the WHOLE text" still got confused when an unrelated
    # actor's rate physically sits closer in characters than the beneficiary's
    # own rate in a different clause (e.g. "Interest charged to the
    # Channelizing Agency is 1% p.a., while beneficiaries are charged 4%
    # p.a." - the "1%" is textually closer to the word "beneficiaries" than
    # the correct "4%" is). Fix: split into clauses on [,.;] first, then only
    # look for percentages WITHIN a clause that also contains "beneficiar" -
    # this keeps other actors' rates in their own clause out of consideration
    # entirely, rather than relying on raw character distance across clauses.
    # ACCURACY FIX (v3): a clause can contain "beneficiar" + a "%" that has
    # NOTHING to do with interest at all (e.g. "At least 50% of funding to
    # the beneficiaries having annual family income..." - that 50% is a
    # funding/subsidy split, not an interest rate). Now requires the clause
    # to also mention interest/rate/charge - AND excludes "subvention"
    # clauses, which describe a separate post-repayment incentive scheme,
    # not the base loan rate the calculator should use.
    if base_rate is None:
        clauses = re.split(r'[,.;]', text)
        beneficiary_clause_rates = []
        for clause in clauses:
            if 'subvention' in clause.lower():
                continue
            if not re.search(r'interest|\brate\b|charg', clause, re.I):
                continue
            if re.search(r'beneficiar\w*', clause, re.I):
                nums_in_clause = [(m.start(), float(m.group(1))) for m in re.finditer(r'(\d+(?:\.\d+)?)\s*%', clause)]
                if nums_in_clause:
                    kpos = re.search(r'beneficiar\w*', clause, re.I).start()
                    nums_in_clause.sort(key=lambda np: abs(np[0] - kpos))
                    beneficiary_clause_rates.append(nums_in_clause[0][1])
        if beneficiary_clause_rates:
            # if several distinct beneficiary-clauses give different rates
            # (rare), take the last one mentioned - text describing a
            # funding chain typically ends with the final rate actually paid.
            base_rate = beneficiary_clause_rates[-1]

    # Fallback for text with no "beneficiar" word at all but a clear
    # "interest rate is/of X%" statement.
    if base_rate is None:
        for pat in [
            r'interest\s+rate\s*s?\s+(?:is|of|chargeable\s+at)?\s*(\d+(?:\.\d+)?)\s*%',
            r'(\d+(?:\.\d+)?)\s*%\s*(?:p\.?a\.?|per\s*annum)\b',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                base_rate = float(m.group(1))
                break

    # 2. Range pattern e.g. "6.5% to 8% per annum" (used when no single
    # "beneficiary interest rate" line exists - use the upper bound as the
    # conservative default, since the lower bound is usually a best-case).
    rate_range = None
    range_m = re.search(r'(\d+(?:\.\d+)?)\s*%\s*to\s*(\d+(?:\.\d+)?)\s*%', text, re.I)
    if range_m:
        rate_range = (float(range_m.group(1)), float(range_m.group(2)))
        if base_rate is None:
            base_rate = rate_range[1]

    # 3. Gender-based rebate/concession for women (e.g. "Women receive an
    # interest rebate of 0.5%"). Subtracted from the base rate to get the
    # female-specific rate. Skipped if step 0 already gave us an explicit
    # female rate directly.
    if base_rate is not None and female_rate is None:
        rebate_m = re.search(
            r'(?:women|female)[^.]{0,50}?(?:rebate|concession|discount)\s+of\s+(\d+(?:\.\d+)?)\s*%',
            text, re.I
        )
        if rebate_m:
            female_rate = round(base_rate - float(rebate_m.group(1)), 2)

    # 4. Repayment tenure in years.
    tenure_years = None
    tenure_m = re.search(
        r'(?:repayment\s+period|maximum\s+period|tenure)[^.\d]{0,40}?(\d+)\s*years?',
        text, re.I
    )
    if tenure_m:
        tenure_years = int(tenure_m.group(1))
    else:
        fallback_m = re.search(r'up\s+to\s+(\d+)\s*years?', text, re.I)
        if fallback_m:
            tenure_years = int(fallback_m.group(1))

    if base_rate is None and tenure_years is None:
        return None

    result = {}
    if base_rate is not None:
        result["interest_rate_default"] = base_rate
    if female_rate is not None:
        result["interest_rate_female"] = female_rate
    if rate_range is not None:
        result["interest_rate_range"] = list(rate_range)
    if tenure_years is not None:
        result["tenure_years"] = tenure_years
    return result


def find_matches(user, schemes):
    """
    Finds all eligible schemes for the user and sorts them using the multi-tiered logic:
      1. Tier 1 (Highly Specific Matches): Intersectional (highest specific trait count) first,
         then single-trait matches, sorted internally by match_score descending.
      2. Tier 2 (Broader/Parent Categories): Sorted internally by match_score descending.
      3. Tier 3 (Universal/Open Schemes): Sorted internally by match_score descending.

    Deduplicates results to ensure each scheme appears only once.
    """
    if not schemes or not isinstance(schemes, list):
        return []

    u = sanitize_user(user)
    results = []
    seen_schemes = set()

    for scheme in schemes:
        if not isinstance(scheme, dict):
            continue

        # Prevent duplicates
        scheme_id = scheme.get('scheme_id')
        scheme_name = scheme.get('scheme_name') or 'Unnamed Scheme'
        dedup_key = f"id:{scheme_id}" if scheme_id is not None else f"name:{scheme_name.strip().lower()}"
        if dedup_key in seen_schemes:
            continue

        eligible, _ = is_eligible(u, scheme)
        if eligible:
            seen_schemes.add(dedup_key)
            score = match_score(u, scheme)
            tier, spec_count, matched_traits = classify_demographic_tier(u, scheme)

            # BUG FIX: previously disability schemes were only ranked by
            # specific_trait_count *within* Tier 1, so e.g. a 2-trait
            # "category+gender" match (no disability) could rank ABOVE a
            # 1-trait "disability-only" match. The user wants disability
            # schemes strictly first, no matter what else matches, when
            # they've indicated they're disabled - this flag makes that
            # an absolute top-level sort key instead of just one of several
            # traits competing inside the trait-count tiebreaker.
            is_disability_match = u['disability'] and ('disability' in matched_traits)

            # FEATURE: when the user explicitly selects an occupation
            # (e.g. "Unemployed / Job Seeker"), schemes that specifically
            # target that occupation should be guaranteed to rank above
            # schemes that don't - not just get +1 to a shared
            # specific_trait_count that a gender/category match could also
            # win on. Mirrors the disability-priority fix: an absolute
            # top-level sort key, but ONLY when the user actually picked an
            # occupation. If no occupation is selected, this key is the
            # same (0) for every scheme, so it has zero effect and the
            # previous tier/trait-count/match_score ordering is unchanged.
            has_occupation_filter = bool(u.get('occupation'))
            is_occupation_match = any(t.startswith('occupation:') for t in matched_traits)
            occupation_sort_key = 0 if (not has_occupation_filter or is_occupation_match) else 1

            # FEATURE: Financial Calculator. gender_restricted tells the
            # frontend whether to show a gender TOGGLE (open to everyone) or
            # a FIXED label (scheme is gender-locked, e.g. "For Women" -
            # there's no legitimate "what if I were male" scenario for a
            # scheme a male can't actually apply to).
            constraints = get_resolved_constraints(scheme)
            gender_restricted = constraints.get('gender_restricted')
            financial_calculator = extract_financial_terms(scheme)
            qualification_hints = constraints.get('qualification_hints', [])

            results.append({
                "scheme_name": scheme_name,
                "match_score": score,
                "tier": scheme.get('tier'),
                "demographic_tier": tier,
                "specific_trait_count": spec_count,
                "matched_demographics": matched_traits,
                "is_disability_match": is_disability_match,
                "occupation_sort_key": occupation_sort_key,
                "gender_restricted": gender_restricted,
                "financial_calculator": financial_calculator,
                "qualification_hints": qualification_hints,
                "department": scheme.get('department', ''),
                "scheme_category": scheme.get('scheme_category', 'Not Specified'),
                "short_description": scheme.get('short_description', ''),
                "benefits_summary": scheme.get('benefits_summary', ''),
                "application_process_summary": scheme.get('application_process_summary', ''),
                "documents_required": scheme.get('documents_required', []) if isinstance(scheme.get('documents_required'), list) else [],
                "tags": scheme.get('tags', []) if isinstance(scheme.get('tags'), list) else [],
                "official_urls": split_urls(scheme.get('official_url', '')),
                "verification_status": scheme.get('verification_status', 'unverified'),
                "level": scheme.get('level', 'Central'),
                "state": scheme.get('state', 'All India')
            })

    # Multi-tiered sort:
    # 0. is_disability_match first, ALWAYS, no matter what else matches
    #    (only kicks in when the user marked themselves disabled)
    # 1. occupation_sort_key ascending (schemes matching the user's selected
    #    occupation come first; no-op if no occupation was selected)
    # 2. demographic_tier ascending (Tier 1 < Tier 2 < Tier 3)
    # 3. -specific_trait_count ascending (intersectional matches e.g. 4, 3, 2, 1 at top of Tier 1)
    # 4. -match_score ascending (highest match_score first within each sub-tier)
    results.sort(key=lambda x: (
        0 if x['is_disability_match'] else 1,
        x['occupation_sort_key'],
        x['demographic_tier'],
        -x['specific_trait_count'],
        -x['match_score']
    ))
    return results
