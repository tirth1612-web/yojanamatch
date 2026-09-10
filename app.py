"""
Bare-minimum local server to test the matching logic end-to-end.
Run: python3 app.py
Then open: http://localhost:5000
"""
import os
import sys
import json
import math
import secrets
from flask import Flask, request, jsonify, send_from_directory, session

# --- Google Sign-In (optional: app still runs fine without it, login routes
# just return a clear error instead of crashing the whole server) ---
try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_auth_requests
except ImportError:
    google_id_token = None
    google_auth_requests = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, 'scripts'))

from matching_engine import find_matches, EMPTY_ELIGIBILITY_MESSAGE
from pathway_engine import build_pathway
from pdf_export import export_pathway_pdf
from document_readiness import get_canonical_checklist_options
from financial_calculator import _get_terms as get_loan_terms
from goal_parser import parse_goal, merge_goal_into_user

DATA_PATH = os.path.join(BASE_DIR, 'data', 'combined_schemes.json')
ALL_SCHEMES = []
if os.path.exists(DATA_PATH):
    with open(DATA_PATH, encoding='utf-8') as f:
        ALL_SCHEMES = json.load(f)

# find_matches() results only carry scheme_name (no scheme_id), so this
# lookup lets us go back to the FULL original scheme record - needed to
# compute correct loan_terms (curated overrides use scheme_id).
SCHEME_BY_NAME = {}
for _s in ALL_SCHEMES:
    _key = (_s.get('scheme_name') or '').strip().lower()
    if _key and _key not in SCHEME_BY_NAME:
        SCHEME_BY_NAME[_key] = _s

# --- Feature #3: Channel Finance / Geo-Spatial Partner Locator ---
# Merged into this same app (same port) so the whole site is one server.
PARTNERS_PATH = os.path.join(BASE_DIR, 'data', 'channel_finance', 'channel_partners.json')
LOAN_SCHEMES_PATH = os.path.join(BASE_DIR, 'data', 'channel_finance', 'loan_schemes.json')

ALL_PARTNERS = []
if os.path.exists(PARTNERS_PATH):
    with open(PARTNERS_PATH, encoding='utf-8') as f:
        ALL_PARTNERS = json.load(f)

ALL_LOAN_SCHEMES = []
if os.path.exists(LOAN_SCHEMES_PATH):
    with open(LOAN_SCHEMES_PATH, encoding='utf-8') as f:
        ALL_LOAN_SCHEMES = json.load(f)

app = Flask(__name__)

# Needed for login sessions (the cookie that remembers who's signed in).
# Set FLASK_SECRET_KEY as a real env var in production - if it's not set,
# a random one is generated on every restart, which just means everyone
# gets logged out whenever the server restarts (fine for a demo).
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# Get this from Google Cloud Console -> APIs & Services -> Credentials ->
# OAuth Client ID (type "Web application"), then set it as an env var AND
# paste the same value into GOOGLE_CLIENT_ID near the top of index.html's
# <script> block.
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

# Where each logged-in user's saved schemes live. Structure:
# { "<google_sub>": { "<scheme_name>": <full scheme dict>, ... }, ... }
SAVED_SCHEMES_PATH = os.path.join(BASE_DIR, 'data', 'saved_schemes.json')

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50  # a ceiling per-request so a bad call can't ask for everything at once


def _load_saved_store():
    if os.path.exists(SAVED_SCHEMES_PATH):
        with open(SAVED_SCHEMES_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _write_saved_store(store):
    os.makedirs(os.path.dirname(SAVED_SCHEMES_PATH), exist_ok=True)
    with open(SAVED_SCHEMES_PATH, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def _current_user_key():
    """The signed-in user's stable ID (Google's 'sub' claim), or None for guests."""
    user = session.get('user')
    return user['sub'] if user else None


@app.route('/auth/google', methods=['POST'])
def auth_google():
    """
    Frontend sends the Google ID token it got from the "Sign in with Google"
    button. We verify it's genuinely from Google (and meant for OUR app,
    via GOOGLE_CLIENT_ID) before trusting anything in it, then start a
    session cookie for this user.
    """
    if google_id_token is None:
        return jsonify({"error": "Google sign-in isn't set up on this server (run: pip install google-auth)."}), 501
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Server is missing GOOGLE_CLIENT_ID."}), 500

    body = request.get_json(silent=True) or {}
    token = body.get('credential')
    if not token:
        return jsonify({"error": "Missing credential"}), 400

    try:
        info = google_id_token.verify_oauth2_token(
            token, google_auth_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        return jsonify({"error": "Invalid or expired Google token"}), 401

    user = {
        "sub": info["sub"],
        "email": info.get("email"),
        "name": info.get("name") or info.get("email"),
        "picture": info.get("picture"),
    }
    session['user'] = user
    session.permanent = True
    return jsonify(user)


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route('/auth/me', methods=['GET'])
def auth_me():
    """Returns the signed-in user, or null if this is a guest."""
    return jsonify(session.get('user'))


@app.route('/saved', methods=['GET'])
def get_saved():
    user_key = _current_user_key()
    if not user_key:
        return jsonify({"error": "Not logged in"}), 401
    store = _load_saved_store()
    return jsonify(list(store.get(user_key, {}).values()))


@app.route('/saved', methods=['POST'])
def add_saved():
    """
    Body: { "scheme": {...} }               - save one scheme, OR
          { "schemes": [{...}, {...}, ...] } - bulk save (used once, right
                                                after login, to carry over
                                                whatever a guest saved
                                                before signing in)
    """
    user_key = _current_user_key()
    if not user_key:
        return jsonify({"error": "Not logged in"}), 401

    body = request.get_json(silent=True) or {}
    store = _load_saved_store()
    user_saved = store.setdefault(user_key, {})

    schemes_to_add = body.get('schemes')
    if schemes_to_add is None and body.get('scheme'):
        schemes_to_add = [body['scheme']]

    for s in (schemes_to_add or []):
        name = (s or {}).get('scheme_name')
        if name:
            user_saved[name] = s

    _write_saved_store(store)
    return jsonify(list(user_saved.values()))


@app.route('/saved/<path:scheme_name>', methods=['DELETE'])
def remove_saved(scheme_name):
    user_key = _current_user_key()
    if not user_key:
        return jsonify({"error": "Not logged in"}), 401
    store = _load_saved_store()
    user_saved = store.setdefault(user_key, {})
    user_saved.pop(scheme_name, None)
    _write_saved_store(store)
    return jsonify(list(user_saved.values()))

@app.route('/')
def home():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/locator')
def locator_page():
    return send_from_directory(BASE_DIR, 'locator.html')


@app.route('/loan-schemes', methods=['GET'])
def loan_schemes():
    """List the NSFDC credit products, for the locator page's dropdown."""
    return jsonify(ALL_LOAN_SCHEMES)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lng points, in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@app.route('/nearest-partners', methods=['POST'])
def nearest_partners():
    """
    Input JSON: { "lat", "lng", "loan_category", "limit" (optional) }
    Returns nearest ELIGIBLE channel partners, sorted by distance.
    """
    body = request.get_json(silent=True) or {}
    user_lat = body.get('lat')
    user_lng = body.get('lng')
    loan_category = body.get('loan_category')
    limit = body.get('limit', 10)

    if user_lat is None or user_lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    try:
        user_lat = float(user_lat)
        user_lng = float(user_lng)
        limit = min(max(1, int(limit)), 50)
    except (TypeError, ValueError):
        return jsonify({"error": "lat/lng/limit must be numeric"}), 400

    eligible = []
    for p in ALL_PARTNERS:
        if p.get('latitude') is None or p.get('longitude') is None:
            continue
        if p.get('eligibility_status') == 'high_npa_flagged':
            continue
        if loan_category and loan_category not in p.get('loan_categories', []):
            continue
        dist = haversine_km(user_lat, user_lng, p['latitude'], p['longitude'])
        eligible.append({**p, "distance_km": round(dist, 1)})

    eligible.sort(key=lambda p: p['distance_km'])
    top = eligible[:limit]

    return jsonify({
        "results": top,
        "total_eligible": len(eligible),
        "user_location": {"lat": user_lat, "lng": user_lng},
        "loan_category": loan_category
    })


@app.route('/match', methods=['POST'])
def match():
    body = request.get_json(silent=True) or {}

    # FIX (bug): previously this always returned jsonify(results[:50]) as a
    # bare array with no total count and no way to fetch the rest - so
    # anything ranked 51st or later was permanently invisible, and the
    # frontend's "showing top 20" label was just decorative text that didn't
    # reflect what was actually cut off. Now supports real offset/limit
    # pagination ("Load more") and always reports total_matches so the
    # frontend knows how many are left.
    offset = body.pop('offset', 0)
    limit = body.pop('limit', PAGE_SIZE_DEFAULT)
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = min(max(1, int(limit)), PAGE_SIZE_MAX)
    except (TypeError, ValueError):
        limit = PAGE_SIZE_DEFAULT

    # FIX (bug #2): this route used to ignore "goal_text" entirely, even
    # though the frontend's goal box (e.g. "college fees for my daughter")
    # sent it here too - so typing a goal only ever changed the single
    # hero "Your Benefit Pathway" card at the top (which calls /pathway
    # separately), while this route's full "N schemes found" list below
    # kept ranking purely off age/gender/category/income/etc, with zero
    # awareness of the goal. Same goal_parser hint-merge that /pathway
    # already used is applied here now, so BOTH the hero card and the
    # full list agree on what the user is trying to do.
    goal_text = body.pop('goal_text', None)
    user = body
    effective_user = merge_goal_into_user(user, parse_goal(goal_text)) if goal_text else user

    results = find_matches(effective_user, ALL_SCHEMES)

    # FIX (bug): find_matches() puts the regex-extracted numbers under
    # "financial_calculator" as {interest_rate_default, interest_rate_female,
    # tenure_years} - but the frontend's EMI widget reads "loan_terms" with
    # {base_interest_rate_percent, max_loan_amount, repayment_years,
    # moratorium_months, gender_rebate, gender_locked, rate_note}. Different
    # key AND different shape, so `s.loan_terms` was always undefined and the
    # "💰 EMI Calculator" button never rendered for ANY scheme. Re-derive the
    # correctly-shaped terms here (curated loan_terms_overrides win, same as
    # the rest of the app) from the original scheme record.
    for r in results:
        original = SCHEME_BY_NAME.get((r.get('scheme_name') or '').strip().lower())
        r['loan_terms'] = get_loan_terms(original) if original else None
        r.pop('financial_calculator', None)

    total = len(results)
    page = results[offset:offset + limit]

    return jsonify({
        "results": page,
        "total_matches": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
        "message": None if total > 0 else EMPTY_ELIGIBILITY_MESSAGE
    })

@app.route('/document-checklist-options', methods=['GET'])
def document_checklist_options():
    """
    Fixed list of document checkboxes for the frontend's ONE-TIME
    'which documents do you already have?' form (see document_readiness.py).
    """
    return jsonify(get_canonical_checklist_options())


@app.route('/pathway', methods=['POST'])
def pathway():
    """
    HERO FEATURE: Government Benefit Pathway.

    Input JSON:
      {
        "user": { age, gender, category, annual_income, state, occupation, ... },
        "goal_text": "Mujhe 5 lakh chahiye business start karne ke liye"  (optional),
        "user_owned_documents": ["aadhaar", "bank_passbook"]  (optional,
             keys from /document-checklist-options),
        "requested_amount": 500000  (optional, overrides the amount parsed
             from goal_text)
      }

    Returns the full pathway: best match + eligibility checklist + financial
    breakdown + document readiness + application steps, OR (if the user
    isn't eligible for anything) near-miss analysis + fallback alternatives.
    """
    body = request.get_json(silent=True) or {}
    user = body.get('user') or {}
    goal_text = body.get('goal_text')
    user_owned_documents = body.get('user_owned_documents') or []
    requested_amount = body.get('requested_amount')

    result = build_pathway(
        user=user,
        schemes=ALL_SCHEMES,
        goal_text=goal_text,
        user_owned_documents=user_owned_documents,
        requested_amount=requested_amount,
    )
    return jsonify(result)


@app.route('/pathway/pdf', methods=['POST'])
def pathway_pdf():
    """
    Same input as /pathway, but returns a downloadable PDF summary instead
    of JSON - for printing or carrying to a bank/office in person.
    """
    body = request.get_json(silent=True) or {}
    user = body.get('user') or {}
    goal_text = body.get('goal_text')
    user_owned_documents = body.get('user_owned_documents') or []
    requested_amount = body.get('requested_amount')
    user_display_name = body.get('user_display_name')

    result = build_pathway(
        user=user,
        schemes=ALL_SCHEMES,
        goal_text=goal_text,
        user_owned_documents=user_owned_documents,
        requested_amount=requested_amount,
    )

    output_dir = os.path.join(BASE_DIR, 'generated_pdfs')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'pathway_summary.pdf')
    export_pathway_pdf(result, output_path, user_display_name=user_display_name)

    from flask import send_file
    return send_file(output_path, as_attachment=True, download_name='my_benefit_pathway.pdf')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
