"""
Hand-curated loan/EMI terms for Tier-1 schemes, built by reading each
scheme's benefits_summary/other_conditions/notes text directly (see
/tmp/loan_texts.txt). Only schemes with an explicit, numeric interest rate
get an entry here - schemes that only say "reasonable interest rate" or
"concessional rate" with no number are intentionally left out, since there's
nothing an EMI calculator could compute from them.

Fields:
  base_interest_rate_percent : the rate a "default" applicant pays (float)
  rate_note                  : short human-readable caveat about tiering/variants
  max_loan_amount            : int (INR) - representative ceiling to cap the input
  repayment_years            : typical/maximum repayment period, in years
  moratorium_months          : typical moratorium before EMIs start, in months
  gender_rebate              : optional dict:
        { "gender": "female", "rebate_percent": 0.5, "note": "..." }
     -> means the given gender pays (base_interest_rate_percent - rebate_percent)
  gender_locked              : "female" | "male" | None
     -> if set, the scheme itself is only open to that gender (comes from
        eligibility.gender == 'female'/'male' already in the data - repeated
        here just for clarity/testing)
"""

LOAN_TERMS_BY_SCHEME_ID = {
    "TIER1-1": dict(base_interest_rate_percent=6.5, max_loan_amount=125000,
                     repayment_years=3, moratorium_months=3),
    "TIER1-2": dict(base_interest_rate_percent=15.0, max_loan_amount=125000,
                     repayment_years=3, moratorium_months=3,
                     rate_note="15% p.a. is the rate NBFC-MFIs charge beneficiaries."),
    "TIER1-3": dict(base_interest_rate_percent=8.0, max_loan_amount=4500000,
                     repayment_years=7, moratorium_months=6,
                     rate_note="Moratorium extends to 12 months for plantation/construction activities."),
    "TIER1-4": dict(base_interest_rate_percent=13.0, max_loan_amount=450000,
                     repayment_years=5, moratorium_months=3,
                     rate_note="13% via Cooperative Banks/Societies; 15% via Small Finance Banks."),
    "TIER1-5": dict(base_interest_rate_percent=6.5, max_loan_amount=4000000,
                     repayment_years=12, moratorium_months=None,
                     rate_note="Moratorium is course period + 1 year before repayment starts (variable)."),
    "TIER1-7": dict(base_interest_rate_percent=4.0, max_loan_amount=400000,
                     repayment_years=7, moratorium_months=None,
                     gender_rebate={"gender": "female", "rebate_percent": 0.5,
                                    "note": "Women receive an interest rebate of 0.5%."}),
    "TIER1-8": dict(base_interest_rate_percent=4.0, max_loan_amount=2700000,
                     repayment_years=10, moratorium_months=6,
                     rate_note="Rate depends on unit-cost tier: 4% / 6% / 7%."),
    "TIER1-10": dict(base_interest_rate_percent=5.0, max_loan_amount=200000,
                      repayment_years=8, moratorium_months=6,
                      gender_locked="female"),
    "TIER1-11": dict(base_interest_rate_percent=6.0, max_loan_amount=1500000,
                      repayment_years=8, moratorium_months=6,
                      rate_note="6% to 8% depending on loan amount; 6% used as the base rate."),
    "TIER1-12": dict(base_interest_rate_percent=4.0, max_loan_amount=2000000,
                      repayment_years=10, moratorium_months=60,
                      gender_rebate={"gender": "female", "rebate_percent": 0.5,
                                     "note": "Interest is 4% p.a. for boys and 3.5% p.a. for girls."}),
    "TIER1-16": dict(base_interest_rate_percent=5.0, max_loan_amount=5000000,
                      repayment_years=10, moratorium_months=None,
                      rate_note="Self-employment rate tiers from 5% (up to Rs.50,000) to 9% (above Rs.30 lakh).",
                      gender_rebate={"gender": "female", "rebate_percent": 1.0,
                                     "note": "Women with disabilities receive a 1% rebate, on self-employment loans up to Rs.50,000 only."}),
    "TIER1-18": dict(base_interest_rate_percent=6.0, max_loan_amount=1500000,
                      repayment_years=7, moratorium_months=None,
                      gender_rebate={"gender": "female", "rebate_percent": 1.0,
                                     "note": "1% interest rebate for women beneficiaries (a further 0.5% rebate applies for timely repayment, not gender-based)."}),
    "TIER1-19": dict(base_interest_rate_percent=4.0, max_loan_amount=None,
                      repayment_years=10, moratorium_months=None,
                      gender_locked="female",
                      rate_note="Loan amount follows the underlying NSFDC scheme's unit cost; moratorium ranges 3-24 months."),
    "TIER1-20": dict(base_interest_rate_percent=7.0, max_loan_amount=200000,
                      repayment_years=5, moratorium_months=6,
                      gender_locked="female"),
    "TIER1-22": dict(base_interest_rate_percent=4.0, max_loan_amount=500000,
                      repayment_years=None, moratorium_months=None),
    "TIER1-25": dict(base_interest_rate_percent=4.0, max_loan_amount=50000,
                      repayment_years=None, moratorium_months=None),
    "TIER1-26": dict(base_interest_rate_percent=2.0, max_loan_amount=100000,
                      repayment_years=None, moratorium_months=None),
    "TIER1-27": dict(base_interest_rate_percent=0.0, max_loan_amount=5000000,
                      repayment_years=2, moratorium_months=None,
                      rate_note="Interest-free loan."),
    "TIER1-32": dict(base_interest_rate_percent=6.0, max_loan_amount=2500000,
                      repayment_years=4, moratorium_months=36,
                      rate_note="Effective net rate is ~3% with the on-time-repayment rebate (not gender-based)."),
    "TIER1-33": dict(base_interest_rate_percent=4.0, max_loan_amount=60000,
                      repayment_years=8, moratorium_months=24),
    "TIER1-34": dict(base_interest_rate_percent=0.0, max_loan_amount=1000000,
                      repayment_years=None, moratorium_months=None,
                      rate_note="Effectively interest-free: the Maharashtra government pays up to 12% p.a. on the beneficiary's behalf, subject to timely repayment."),
    "TIER1-36": dict(base_interest_rate_percent=7.0, max_loan_amount=500000,
                      repayment_years=5, moratorium_months=None,
                      rate_note="7% for loans up to Rs.5 lakh; 9% above Rs.5 lakh."),
    "TIER1-37": dict(base_interest_rate_percent=6.0, max_loan_amount=2000000,
                      repayment_years=None, moratorium_months=None),
    "TIER1-53": dict(base_interest_rate_percent=0.0, max_loan_amount=50000,
                      repayment_years=5, moratorium_months=None,
                      gender_locked="female",
                      rate_note="Interest-free up to Rs.50,000; a flat 3% applies only on any amount borrowed above that."),
    "TIER1-58": dict(base_interest_rate_percent=6.0, max_loan_amount=1000000,
                      repayment_years=None, moratorium_months=None,
                      rate_note="6% for loans up to Rs.5 lakh; 8% for the portion above Rs.5 lakh up to Rs.10 lakh."),
    "TIER1-59": dict(base_interest_rate_percent=4.0, max_loan_amount=50000,
                      repayment_years=None, moratorium_months=None,
                      rate_note="4% to 6% after the on-time-repayment interest subsidy."),
}
