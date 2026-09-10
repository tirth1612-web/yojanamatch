"""
Comprehensive test suite for multi-tiered scheme matching engine.
Tests:
  1. Tier 1 Specific Matches (Category, Gender, Disability, Occupation, Vulnerability, Minority)
  2. Intersectionality (Multiple specific traits ranked highest in Tier 1)
  3. Tier 2 Broader/Parent Category (EWS -> General)
  4. Tier 3 Universal/Open Schemes (Unrestricted schemes at the bottom)
  5. Internal Ranking (match_score preserved within each tier/group)
  6. Empty State Handling (Exact message returned when 0 eligible schemes)
  7. Text & Node Constraint Extraction & Verification:
     - Age limits extracted from other_conditions / notes
     - Income limits (floors, annual ceilings, monthly ceilings converted to annual)
     - Statutory ceilings (BPL, Non-Taxpayer, EWS, OBC-NCL)
     - Disability and gender constraints extracted from unstructured text
  8. Autonomous Feature 1: Occupation & Livelihood Matching (Student, Farmer, Entrepreneur, Artisan, Sanitation Worker)
  9. Autonomous Feature 2: Vulnerability & Marital Status Matching (Widow, Divorced/Deserted, Single Mother, Orphan, Transgender)
  10. Autonomous Feature 3: Minority Community & Domicile Matching (Minority, Rural/Urban)
  11. High-Income (> 10 Lakhs) Strict Audit Verification
  12. Edge Cases & Bug Prevention:
     - Nested income interval and sub-range parsing
     - Deduplication of overlapping schemes
     - Missing / None / Empty user fields
     - Malformed / missing scheme fields
     - Array boundaries (None / empty scheme lists)
  13. Full Dataset Integrity & Sorting Invariants (3,449 schemes)
"""
import unittest
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from matching_engine import (
    find_matches,
    is_eligible,
    match_score,
    classify_demographic_tier,
    sanitize_user,
    extract_constraints_from_text,
    get_resolved_constraints,
    is_unrestricted,
    extract_financial_terms,
    EMPTY_ELIGIBILITY_MESSAGE
)


class TestMatchingEngine(unittest.TestCase):

    def setUp(self):
        self.mock_schemes = [
            # Tier 1 - 3 Traits: Female + SC + Disabled
            {
                "scheme_id": "S1",
                "scheme_name": "SC Disabled Women Entrepreneur Scheme",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "female",
                    "min_age": 18,
                    "max_age": 50,
                    "category": ["SC"],
                    "disability_status": "Yes",
                    "income_ceiling_annual": 300000
                },
                "official_url": "https://example.com/s1",
                "documents_required": ["Aadhaar", "Caste Certificate", "Disability Certificate"]
            },
            # Tier 1 - 2 Traits: Female + SC
            {
                "scheme_id": "S2",
                "scheme_name": "SC Women Higher Education Fellowship",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "female",
                    "min_age": 20,
                    "max_age": 35,
                    "category": ["SC"],
                    "disability_status": "not_specified",
                    "income_ceiling_annual": 500000
                },
                "official_url": "https://example.com/s2",
                "documents_required": ["Caste Certificate"]
            },
            # Tier 1 - 1 Trait: SC only (high score)
            {
                "scheme_id": "S3",
                "scheme_name": "SC Micro Finance Scheme",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 60,
                    "category": ["SC"],
                    "income_floor_annual": 50000,
                    "income_ceiling_annual": 300000,
                    "disability_status": "not_specified"
                }
            },
            # Tier 1 - 1 Trait: SC only (low score)
            {
                "scheme_id": "S4",
                "scheme_name": "SC General Awareness Grant",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 60,
                    "category": ["SC"],
                    "disability_status": "not_specified"
                }
            },
            # Tier 1 - 1 Trait: EWS only
            {
                "scheme_id": "S5",
                "scheme_name": "EWS Housing Subsidy",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 60,
                    "category": ["EWS"],
                    "income_ceiling_annual": 300000,
                    "disability_status": "not_specified"
                }
            },
            # Tier 2 - Broader Category: General category scheme
            {
                "scheme_id": "S6",
                "scheme_name": "General Category Youth Business Scheme",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 40,
                    "category": ["GENERAL"],
                    "disability_status": "not_specified"
                }
            },
            # Tier 3 - Universal / Open: High score
            {
                "scheme_id": "S7",
                "scheme_name": "Universal Farmer Support Scheme",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 65,
                    "category": "any",
                    "income_ceiling_annual": 600000,
                    "disability_status": "not_specified"
                }
            },
            # Tier 3 - Universal / Open: Low score
            {
                "scheme_id": "S8",
                "scheme_name": "National Public Health Insurance",
                "level": "Central",
                "state": "All India",
                "eligibility": {
                    "gender": "any",
                    "min_age": 18,
                    "max_age": 70,
                    "category": "any",
                    "disability_status": "not_specified"
                }
            }
        ]

    def test_tier1_and_intersectionality_ranking(self):
        """
        Verify that for an SC Female Disabled user:
        1. 3-trait scheme (SC + Female + Disabled) is #1
        2. 2-trait scheme (SC + Female) is #2
        3. 1-trait schemes (SC only) follow, sorted by match_score descending
        4. Tier 3 Universal schemes follow Tier 1, sorted by match_score descending
        """
        user = {
            "gender": "female",
            "age": 25,
            "category": "SC",
            "annual_income": 200000,
            "disability": True,
            "state": "All India"
        }
        matches = find_matches(user, self.mock_schemes)

        self.assertEqual(matches[0]['scheme_name'], "SC Disabled Women Entrepreneur Scheme")
        self.assertEqual(matches[0]['demographic_tier'], 1)
        self.assertEqual(matches[0]['specific_trait_count'], 3)

        self.assertEqual(matches[1]['scheme_name'], "SC Women Higher Education Fellowship")
        self.assertEqual(matches[1]['demographic_tier'], 1)
        self.assertEqual(matches[1]['specific_trait_count'], 2)

        self.assertEqual(matches[2]['scheme_name'], "SC Micro Finance Scheme")
        self.assertEqual(matches[2]['demographic_tier'], 1)
        self.assertEqual(matches[2]['specific_trait_count'], 1)

        self.assertEqual(matches[3]['scheme_name'], "SC General Awareness Grant")
        self.assertEqual(matches[3]['demographic_tier'], 1)
        self.assertEqual(matches[3]['specific_trait_count'], 1)

        self.assertEqual(matches[4]['demographic_tier'], 3)
        self.assertEqual(matches[4]['scheme_name'], "Universal Farmer Support Scheme")

        self.assertEqual(matches[5]['demographic_tier'], 3)
        self.assertEqual(matches[5]['scheme_name'], "National Public Health Insurance")

    def test_tier2_ews_and_general_category_hierarchy(self):
        """
        Verify that for an EWS user:
        1. EWS-specific schemes appear in Tier 1 at top.
        2. General-category schemes appear in Tier 2 immediately after.
        3. Universal/Open schemes appear in Tier 3 at bottom.
        """
        user = {
            "gender": "male",
            "age": 25,
            "category": "EWS",
            "annual_income": 200000,
            "disability": False,
            "state": "All India"
        }
        matches = find_matches(user, self.mock_schemes)

        self.assertEqual(matches[0]['scheme_name'], "EWS Housing Subsidy")
        self.assertEqual(matches[0]['demographic_tier'], 1)
        self.assertEqual(matches[0]['specific_trait_count'], 1)

        self.assertEqual(matches[1]['scheme_name'], "General Category Youth Business Scheme")
        self.assertEqual(matches[1]['demographic_tier'], 2)

        tier3_matches = [m for m in matches if m['demographic_tier'] == 3]
        self.assertEqual(len(tier3_matches), 2)
        self.assertEqual(tier3_matches[0]['scheme_name'], "Universal Farmer Support Scheme")
        self.assertEqual(tier3_matches[1]['scheme_name'], "National Public Health Insurance")

    def test_internal_ranking_within_tiers(self):
        user = {
            "gender": "male",
            "age": 25,
            "category": "General",
            "annual_income": 200000,
            "disability": False,
            "state": "All India"
        }
        matches = find_matches(user, self.mock_schemes)

        self.assertEqual(matches[0]['demographic_tier'], 1)
        self.assertEqual(matches[0]['scheme_name'], "General Category Youth Business Scheme")

        self.assertEqual(matches[1]['demographic_tier'], 3)
        self.assertEqual(matches[1]['scheme_name'], "Universal Farmer Support Scheme")
        self.assertTrue(matches[1]['match_score'] > matches[2]['match_score'])

        self.assertEqual(matches[2]['demographic_tier'], 3)
        self.assertEqual(matches[2]['scheme_name'], "National Public Health Insurance")

    def test_text_and_node_constraint_extraction(self):
        text_constrained_scheme = {
            "scheme_id": "TC1",
            "scheme_name": "Rural Women Self-Help Scheme",
            "eligibility": {
                "gender": "any",
                "min_age": None,
                "max_age": None,
                "category": ["ANY"],
                "income_ceiling_annual": None,
                "other_conditions": "Applicant must be aged between 18 and 35 years. Annual family income must not exceed Rs. 1,50,000. For women only."
            }
        }

        extracted = extract_constraints_from_text(text_constrained_scheme)
        self.assertEqual(extracted.get('min_age'), 18.0)
        self.assertEqual(extracted.get('max_age'), 35.0)
        self.assertEqual(extracted.get('income_ceiling_annual'), 150000.0)
        self.assertEqual(extracted.get('gender_restricted'), 'female')

        # Eligible User
        user_a = {"gender": "female", "age": 28, "category": "General", "annual_income": 125000}
        eligible_a, _ = is_eligible(user_a, text_constrained_scheme)
        self.assertTrue(eligible_a)
        tier_a, spec_count_a, _ = classify_demographic_tier(user_a, text_constrained_scheme)
        self.assertEqual(tier_a, 1)

        # Ineligible due to gender
        user_b = {"gender": "male", "age": 28, "category": "General", "annual_income": 125000}
        self.assertFalse(is_eligible(user_b, text_constrained_scheme)[0])

        # Ineligible due to age > 35
        user_c = {"gender": "female", "age": 42, "category": "General", "annual_income": 125000}
        self.assertFalse(is_eligible(user_c, text_constrained_scheme)[0])

        # Ineligible due to income > 150,000
        user_d = {"gender": "female", "age": 28, "category": "General", "annual_income": 175000}
        self.assertFalse(is_eligible(user_d, text_constrained_scheme)[0])

    def test_monthly_income_conversion(self):
        monthly_scheme = {
            "scheme_id": "MS1",
            "scheme_name": "Destitute Monthly Stipend",
            "eligibility": {
                "other_conditions": "Applicant monthly household income should not exceed Rs. 10,000."
            }
        }
        resolved = get_resolved_constraints(monthly_scheme)
        # 10,000 * 12 = 120,000
        self.assertEqual(resolved['income_ceiling'], 120000.0)

        # Eligible (annual income 100,000 <= 120,000)
        self.assertTrue(is_eligible({"annual_income": 100000}, monthly_scheme)[0])
        # Ineligible (annual income 150,000 > 120,000)
        self.assertFalse(is_eligible({"annual_income": 150000}, monthly_scheme)[0])

    def test_bpl_and_statutory_ceilings(self):
        bpl_scheme = {
            "scheme_id": "BPL1",
            "scheme_name": "BPL Assistive Devices Scheme",
            "eligibility": {
                "other_conditions": "Applicant must belong to BPL category and have disability of at least 40%."
            }
        }
        resolved = get_resolved_constraints(bpl_scheme)
        self.assertEqual(resolved['income_ceiling'], 120000.0)
        self.assertTrue(resolved['disability_required'])

        user_ok = {"gender": "male", "age": 30, "category": "General", "annual_income": 80000, "disability": True}
        self.assertTrue(is_eligible(user_ok, bpl_scheme)[0])

        user_no_pwd = {"gender": "male", "age": 30, "category": "General", "annual_income": 80000, "disability": False}
        self.assertFalse(is_eligible(user_no_pwd, bpl_scheme)[0])

        user_high_inc = {"gender": "male", "age": 30, "category": "General", "annual_income": 200000, "disability": True}
        self.assertFalse(is_eligible(user_high_inc, bpl_scheme)[0])

    def test_autonomous_occupation_matching(self):
        """
        Verify Autonomous Feature 1:
        Occupation targeting elevates specific occupation matches to Tier 1.
        """
        occ_schemes = [
            {
                "scheme_id": "OCC_STU",
                "scheme_name": "National Merit Scholarship for Higher Education Students",
                "short_description": "Scholarship grant for undergraduate and post graduate students."
            },
            {
                "scheme_id": "OCC_FARM",
                "scheme_name": "Kisan Credit Scheme for Agriculture Farmers",
                "short_description": "Subsidized farm loan for crop cultivators and agriculture farmers."
            },
            {
                "scheme_id": "OCC_ENT",
                "scheme_name": "MSME Small Business Startup Venture Fund",
                "short_description": "Seed funding for entrepreneurs starting micro enterprise and startup business."
            },
            {
                "scheme_id": "OCC_SAN",
                "scheme_name": "National Safai Karamchari Rehabilitation Scheme",
                "short_description": "Loan and subsidy for sanitation workers and manual scavengers."
            }
        ]

        # Student user
        student_user = {"age": 20, "occupation": "student"}
        matches_stu = find_matches(student_user, occ_schemes)
        self.assertEqual(matches_stu[0]['scheme_name'], "National Merit Scholarship for Higher Education Students")
        self.assertEqual(matches_stu[0]['demographic_tier'], 1)
        self.assertIn("occupation:student", matches_stu[0]['matched_demographics'])

        # Farmer user
        farmer_user = {"age": 40, "occupation": "farmer"}
        matches_farm = find_matches(farmer_user, occ_schemes)
        self.assertEqual(matches_farm[0]['scheme_name'], "Kisan Credit Scheme for Agriculture Farmers")
        self.assertEqual(matches_farm[0]['demographic_tier'], 1)
        self.assertIn("occupation:farmer", matches_farm[0]['matched_demographics'])

        # Sanitation worker user
        san_user = {"age": 35, "occupation": "sanitation_worker"}
        matches_san = find_matches(san_user, occ_schemes)
        self.assertEqual(matches_san[0]['scheme_name'], "National Safai Karamchari Rehabilitation Scheme")
        self.assertEqual(matches_san[0]['demographic_tier'], 1)
        self.assertIn("occupation:sanitation_worker", matches_san[0]['matched_demographics'])

    def test_autonomous_vulnerability_matching(self):
        """
        Verify Autonomous Feature 2:
        Widows, divorced/deserted women, orphans, transgender persons receive Tier 1 placement.
        """
        vuln_schemes = [
            {
                "scheme_id": "V1",
                "scheme_name": "Destitute Widow Pension and Rehabilitation Scheme",
                "short_description": "Monthly pension support for destitute widow women."
            },
            {
                "scheme_id": "V2",
                "scheme_name": "National Transgender Welfare and Skill Fund",
                "short_description": "Skill training and identity cards for transgender persons."
            },
            {
                "scheme_id": "V3",
                "scheme_name": "Orphan Child Higher Education Grant",
                "short_description": "Financial grant for orphan children and parentless students."
            }
        ]

        # Widow user
        widow_user = {"gender": "female", "age": 45, "marital_status": "widow"}
        matches_widow = find_matches(widow_user, vuln_schemes)
        self.assertEqual(matches_widow[0]['scheme_name'], "Destitute Widow Pension and Rehabilitation Scheme")
        self.assertEqual(matches_widow[0]['demographic_tier'], 1)
        self.assertIn("vulnerability:widow", matches_widow[0]['matched_demographics'])

        # Transgender user
        tg_user = {"gender": "transgender", "age": 26}
        matches_tg = find_matches(tg_user, vuln_schemes)
        self.assertEqual(matches_tg[0]['scheme_name'], "National Transgender Welfare and Skill Fund")
        self.assertEqual(matches_tg[0]['demographic_tier'], 1)
        self.assertIn("vulnerability:transgender", matches_tg[0]['matched_demographics'])

        # Orphan user
        orphan_user = {"age": 19, "is_orphan": True}
        matches_orphan = find_matches(orphan_user, vuln_schemes)
        self.assertEqual(matches_orphan[0]['scheme_name'], "Orphan Child Higher Education Grant")
        self.assertEqual(matches_orphan[0]['demographic_tier'], 1)
        self.assertIn("vulnerability:orphan", matches_orphan[0]['matched_demographics'])

    def test_autonomous_minority_and_domicile_matching(self):
        """
        Verify Autonomous Feature 3:
        Minority community targeting and Rural/Urban geographic targeting.
        """
        comm_schemes = [
            {
                "scheme_id": "MIN1",
                "scheme_name": "Maulana Azad National Minority Fellowship",
                "short_description": "Fellowship for students from minority communities (Muslim, Christian, Sikh, Buddhist, Jain, Parsi)."
            },
            {
                "scheme_id": "RUR1",
                "scheme_name": "Pradhan Mantri Gramin Awaas Yojana",
                "short_description": "Housing support strictly for families in rural areas and gram panchayat."
            }
        ]

        # Minority user
        minority_user = {"age": 24, "is_minority": True}
        matches_min = find_matches(minority_user, comm_schemes)
        self.assertEqual(matches_min[0]['scheme_name'], "Maulana Azad National Minority Fellowship")
        self.assertEqual(matches_min[0]['demographic_tier'], 1)
        self.assertIn("minority", matches_min[0]['matched_demographics'])

        # Urban user on rural-only scheme -> ineligible
        urban_user = {"age": 30, "area": "urban"}
        self.assertFalse(is_eligible(urban_user, comm_schemes[1])[0])

        # Rural user on rural-only scheme -> eligible
        rural_user = {"age": 30, "area": "rural"}
        self.assertTrue(is_eligible(rural_user, comm_schemes[1])[0])

    def test_high_income_audit_above_10_lakhs(self):
        """
        Strict audit test: Verify that users with income > 10 Lakhs (e.g. ₹12 Lakhs)
        are blocked from any scheme with income ceilings, BPL rules, or taxpayer clauses,
        and only receive genuinely open schemes (e.g. patent subsidies, universal awards).
        """
        mixed_schemes = [
            {
                "scheme_id": "H1",
                "scheme_name": "BPL Ration Subsidy",
                "eligibility": {"other_conditions": "Applicant must hold yellow ration card and be below poverty line."}
            },
            {
                "scheme_id": "H2",
                "scheme_name": "Non-Taxpayer Pension Scheme",
                "eligibility": {"other_conditions": "Beneficiary should not be an income tax payer."}
            },
            {
                "scheme_id": "H3",
                "scheme_name": "EWS Housing Scheme",
                "eligibility": {"category": ["EWS"]}
            },
            {
                "scheme_id": "H4",
                "scheme_name": "National Patent Support Grant for Innovators",
                "short_description": "Reimbursement of patent filing fees for all Indian inventors.",
                "eligibility": {"min_age": 18}
            }
        ]

        high_income_user = {
            "gender": "male",
            "age": 35,
            "category": "General",
            "annual_income": 1200000,
            "income_sub_range": 1200000,
            "disability": False,
            "state": "All India"
        }

        matches = find_matches(high_income_user, mixed_schemes)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['scheme_name'], "National Patent Support Grant for Innovators")

    def test_disability_absolute_priority_over_trait_count(self):
        """
        A disabled user must see EVERY disability-matching scheme before ANY
        non-disability scheme - even a scheme that matches MORE other traits
        (e.g. category+gender, 2 traits) than the disability-only match (1 trait).
        """
        schemes = [
            {
                "scheme_id": "D1",
                "scheme_name": "Disability-Only Scholarship",
                "eligibility": {"disability_status": "Yes"}
            },
            {
                "scheme_id": "D2",
                "scheme_name": "SC Women 2-Trait Scheme (no disability)",
                "eligibility": {"gender": "female", "category": ["SC"]}
            },
        ]
        user = {"gender": "female", "age": 25, "category": "SC", "disability": True}
        matches = find_matches(user, schemes)
        self.assertEqual(matches[0]['scheme_name'], "Disability-Only Scholarship")
        self.assertTrue(matches[0]['is_disability_match'])
        self.assertEqual(matches[1]['scheme_name'], "SC Women 2-Trait Scheme (no disability)")
        self.assertFalse(matches[1]['is_disability_match'])

    def test_gender_restriction_inferred_from_scheme_name_excludes_opposite_gender(self):
        """
        BUG PREVENTION: a scheme whose gender restriction is only stated in its
        title (e.g. "...To Women Candidates") - and NOT repeated verbatim as
        "only"/"female candidates only" in other_conditions/notes/description -
        must still be excluded for a male user, and must still be included for
        a female user. This was previously leaking through as gender-unrestricted.
        """
        scheme = {
            "scheme_id": "WOMEN1",
            "scheme_name": "Post Doctoral Fellowship To Women Candidates",
            "short_description": (
                "The UGC has initiated a scheme for those candidates, who are "
                "unemployed holding Ph.D. degrees, with an aim to accelerate "
                "the talented instincts of the women candidates to carry out "
                "advanced studies and research."
            ),
            "eligibility": {}
        }
        male_user = {"gender": "male", "age": 30, "occupation": "unemployed"}
        female_user = {"gender": "female", "age": 30, "occupation": "unemployed"}

        eligible_male, reasons = is_eligible(male_user, scheme)
        self.assertFalse(eligible_male)
        self.assertTrue(any('gender' in r.lower() for r in reasons))

        eligible_female, _ = is_eligible(female_user, scheme)
        self.assertTrue(eligible_female)

        matches_male = find_matches(male_user, [scheme])
        self.assertEqual(len(matches_male), 0)

    def test_unisex_phrasing_is_not_wrongly_gender_restricted(self):
        """
        A scheme that explicitly says it's open to "both men and women" must
        NOT be treated as female-restricted just because the word "women"
        appears in its text.
        """
        scheme = {
            "scheme_id": "UNISEX1",
            "scheme_name": "Rural Skill Development Programme",
            "short_description": "Open to both men and women aged 18 to 40 for vocational training.",
            "eligibility": {}
        }
        male_user = {"gender": "male", "age": 25}
        eligible, reasons = is_eligible(male_user, scheme)
        self.assertTrue(eligible, msg=f"Unexpectedly excluded: {reasons}")

    def test_occupation_absolute_priority_and_false_positive_fix(self):
        """
        BUG PREVENTION: when a user explicitly selects an occupation:
          1. A PhD/research fellowship that merely contains the bare word
             "unemployed" in passing must NOT be tagged as an "unemployed"
             occupation match (it's a student scheme).
          2. A genuine job-seeker scheme (skill training for unemployed youth)
             must rank ABOVE a scheme matching more generic traits (e.g. only
             category), mirroring disability's absolute top-level priority.
          3. When occupation is NOT selected, ordering falls back to the
             previous tier/trait-count/match_score logic (occupation has no effect).
        """
        phd_scheme = {
            "scheme_id": "PHD1",
            "scheme_name": "Post Doctoral Fellowship To Women Candidates",
            "short_description": "For candidates who are unemployed holding Ph.D. degrees in their subject.",
            "eligibility": {"category": ["OBC"]}
        }
        job_seeker_scheme = {
            "scheme_id": "SKILL1",
            "scheme_name": "National Action Plan for Skill Development",
            "short_description": "Vocational training for unemployed youth to gain employment.",
            "eligibility": {}
        }

        # PhD scheme must not be tagged as an unemployed-occupation match at all.
        constraints = get_resolved_constraints(phd_scheme)
        self.assertNotIn('unemployed', constraints['target_occupations'])
        self.assertIn('student', constraints['target_occupations'])

        # A male, OBC, unemployed user should see the genuine job-seeker
        # scheme ranked above the OBC-only-matching PhD scheme.
        user = {"gender": "male", "age": 25, "category": "OBC", "occupation": "unemployed"}
        matches = find_matches(user, [phd_scheme, job_seeker_scheme])
        self.assertEqual(matches[0]['scheme_name'], "National Action Plan for Skill Development")
        self.assertTrue(matches[0]['occupation_sort_key'] == 0)

        # Without an occupation filter, the occupation key must not affect ordering.
        user_no_occ = {"gender": "male", "age": 25, "category": "OBC"}
        matches_no_occ = find_matches(user_no_occ, [phd_scheme, job_seeker_scheme])
        self.assertTrue(all(m['occupation_sort_key'] == 0 for m in matches_no_occ))

    def test_financial_calculator_extraction(self):
        """
        FEATURE: Financial Calculator support. Covers:
          1. A clean "beneficiary interest rate is X%" statement.
          2. A multi-hop funding chain where a naive "first % found" grab
             would pick the WRONG actor's rate.
          3. A direct dual-rate "X% (Y% for Women)" statement.
          4. A "women receive a rebate of X%" statement (subtract from base).
          5. A stray "beneficiary" + "%" that is NOT about interest at all
             (a funding/subsidy split) - must not be picked up as a rate.
          6. A scheme with no rate/tenure info at all - must return None so
             no calculator is shown.
        """
        clean_scheme = {
            "scheme_name": "Term Loan",
            "benefits_summary": "Beneficiary interest rate is 8% p.a. Repayment period is up to 7 years.",
            "eligibility": {}
        }
        r = extract_financial_terms(clean_scheme)
        self.assertEqual(r['interest_rate_default'], 8.0)
        self.assertEqual(r['tenure_years'], 7)

        chain_scheme = {
            "scheme_name": "AMY",
            "benefits_summary": "NSFDC charges 5% interest from NBFC-MFIs, which in turn charge 15% interest from beneficiaries.",
            "eligibility": {}
        }
        r = extract_financial_terms(chain_scheme)
        self.assertEqual(r['interest_rate_default'], 15.0, msg="Must pick the beneficiary's actual rate, not the intermediate NBFC rate")

        dual_scheme = {
            "scheme_name": "Dual rate scheme",
            "benefits_summary": "Interest rates chargeable at 11% (10% for Women).",
            "eligibility": {}
        }
        r = extract_financial_terms(dual_scheme)
        self.assertEqual(r['interest_rate_default'], 11.0)
        self.assertEqual(r['interest_rate_female'], 10.0)

        rebate_scheme = {
            "scheme_name": "Rebate scheme",
            "benefits_summary": "Beneficiaries are charged 4% p.a. Women receive an interest rebate of 0.5%.",
            "eligibility": {}
        }
        r = extract_financial_terms(rebate_scheme)
        self.assertEqual(r['interest_rate_default'], 4.0)
        self.assertEqual(r['interest_rate_female'], 3.5)

        funding_split_scheme = {
            "scheme_name": "Funding split, not a rate",
            "short_description": "At least 50% of funding to the beneficiaries having annual family income up to Rs. 1.50 lakh.",
            "eligibility": {}
        }
        r = extract_financial_terms(funding_split_scheme)
        self.assertIsNone(r, msg="A funding-split percentage near 'beneficiaries' must NOT be mistaken for an interest rate")

        empty_scheme = {"scheme_name": "No financial info", "short_description": "Apply within 30 days of notification.", "eligibility": {}}
        self.assertIsNone(extract_financial_terms(empty_scheme))

    def test_financial_calculator_wired_into_find_matches(self):
        """
        Each match result must carry 'financial_calculator' (None if nothing
        found) and 'gender_restricted' (for the frontend to decide whether
        to show a gender TOGGLE or a FIXED gender label).
        """
        scheme_with_rate = {
            "scheme_id": "F1", "scheme_name": "Term Loan",
            "benefits_summary": "Beneficiary interest rate is 8% p.a. Repayment period is up to 7 years.",
            "eligibility": {}
        }
        women_only_scheme = {
            "scheme_id": "F2", "scheme_name": "Loan Scheme For Women",
            "benefits_summary": "No rate info here.",
            "eligibility": {}
        }
        user = {"gender": "female", "age": 30}
        matches = find_matches(user, [scheme_with_rate, women_only_scheme])
        by_id = {m['scheme_name']: m for m in matches}
        self.assertIsNotNone(by_id['Term Loan']['financial_calculator'])
        self.assertEqual(by_id['Term Loan']['financial_calculator']['interest_rate_default'], 8.0)
        self.assertIsNone(by_id['Loan Scheme For Women']['financial_calculator'])
        self.assertEqual(by_id['Loan Scheme For Women']['gender_restricted'], 'female')
        self.assertIsNone(by_id['Term Loan']['gender_restricted'])

    def test_empty_state_handling(self):
        user = {
            "gender": "male",
            "age": 150,
            "category": "SC",
            "annual_income": 999999999,
            "disability": False,
            "state": "All India"
        }
        matches = find_matches(user, self.mock_schemes)
        self.assertEqual(len(matches), 0)
        self.assertEqual(EMPTY_ELIGIBILITY_MESSAGE, "You are not eligible for any schemes at the moment.")

    def test_deduplication(self):
        duplicate_list = self.mock_schemes + [self.mock_schemes[0], self.mock_schemes[1]]
        user = {
            "gender": "female",
            "age": 25,
            "category": "SC",
            "annual_income": 200000,
            "disability": True,
            "state": "All India"
        }
        matches = find_matches(user, duplicate_list)
        scheme_names = [m['scheme_name'] for m in matches]
        self.assertEqual(len(scheme_names), len(set(scheme_names)))

    def test_missing_and_null_user_data(self):
        user_incomplete = {
            "gender": None,
            "age": "",
            "category": None,
            "annual_income": "invalid_income",
            "disability": "true",
            "state": None
        }
        matches = find_matches(user_incomplete, self.mock_schemes)
        self.assertIsInstance(matches, list)

        matches_empty = find_matches({}, self.mock_schemes)
        self.assertIsInstance(matches_empty, list)

        matches_none = find_matches(None, self.mock_schemes)
        self.assertIsInstance(matches_none, list)

    def test_nested_income_interval_string_parsing(self):
        user_range = {"income_sub_range": "125000-150000"}
        sanitized = sanitize_user(user_range)
        self.assertEqual(sanitized['annual_income'], 150000.0)

    def test_malformed_and_boundary_schemes(self):
        bad_schemes = [
            None,
            {},
            {"scheme_name": None, "eligibility": None},
            {"scheme_name": "Malformed Scheme", "eligibility": "not a dict"},
            {"scheme_name": "Invalid numbers", "eligibility": {"min_age": "abc", "income_floor_annual": None}}
        ]
        user = {"gender": "male", "age": 30, "category": "General", "annual_income": 100000}
        matches = find_matches(user, bad_schemes)
        self.assertIsInstance(matches, list)

        self.assertEqual(find_matches(user, []), [])
        self.assertEqual(find_matches(user, None), [])

    def test_real_dataset_integrity(self):
        """
        Verify invariants across the actual 3,449-scheme dataset in combined_schemes.json.
        """
        data_path = os.path.join(BASE_DIR, '..', 'data', 'combined_schemes.json')
        if os.path.exists(data_path):
            with open(data_path, encoding='utf-8') as f:
                real_schemes = json.load(f)

            # NOTE: exact count intentionally not hardcoded - it shifts every
            # time merge_dedup.py is re-run against an updated Tier-2 dump
            # (e.g. 3449 vs 3450 across recent regenerations). We only assert
            # it's in the expected ballpark so this test doesn't break on
            # every routine data refresh.
            self.assertGreater(len(real_schemes), 3000)

            test_user = {
                "gender": "female",
                "age": 28,
                "category": "EWS",
                "annual_income": 200000,
                "disability": True,
                "occupation": "student",
                "state": "All India"
            }
            matches = find_matches(test_user, real_schemes)
            self.assertTrue(len(matches) > 0)

            # Invariant 0: disability-first is an ABSOLUTE top-level key - once
            # a non-disability match appears, no disability match may follow it.
            seen_non_disability = False
            for m in matches:
                if not m['is_disability_match']:
                    seen_non_disability = True
                else:
                    self.assertFalse(seen_non_disability,
                        "A disability match appeared after a non-disability match")

            # Invariant 1: Demographic tiers strictly non-decreasing (1 <= 2 <= 3)
            # WITHIN each of the two disability-priority groups (since disability
            # match is now sorted ahead of tier, not inside it).
            for is_disab in (True, False):
                group = [m for m in matches if m['is_disability_match'] == is_disab]
                tiers = [m['demographic_tier'] for m in group]
                self.assertEqual(tiers, sorted(tiers))

            # Invariant 2: within (is_disability_match, demographic_tier==1),
            # specific_trait_count strictly non-increasing
            for is_disab in (True, False):
                tier1_spec_counts = [
                    m['specific_trait_count'] for m in matches
                    if m['demographic_tier'] == 1 and m['is_disability_match'] == is_disab
                ]
                self.assertEqual(tier1_spec_counts, sorted(tier1_spec_counts, reverse=True))

            # Invariant 3: Within identical (is_disability_match, tier, specific_trait_count),
            # match_score non-increasing
            groups = {}
            for m in matches:
                key = (m['is_disability_match'], m['demographic_tier'], m['specific_trait_count'])
                groups.setdefault(key, []).append(m['match_score'])
            for key, scores in groups.items():
                self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == '__main__':
    unittest.main()
