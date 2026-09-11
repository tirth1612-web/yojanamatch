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
import logging
import traceback
from flask import Flask, request, jsonify, send_from_directory, session

# Make sure errors actually show up in Vercel's runtime logs (stdout/stderr),
# instead of just a bare "500 -" with no detail like we were seeing before.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


@app.errorhandler(Exception)
def handle_any_uncaught_exception(e):
    """
    Safety net: any exception ANYWHERE in the app that wasn't already caught
    now gets its full traceback printed to the Vercel runtime logs, instead
    of showing up as just a bare 'POST /whatever 500 -' with no detail
    (which is what we were seeing for /auth/google before this fix).
    """
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.path, traceback.format_exc())
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.after_request
def add_coop_header(response):
    """
    Fixes the 'Cross-Origin-Opener-Policy policy would block the
    window.postMessage call' console warnings that show up during the
    Google Sign-In popup flow. Harmless on their own, but this quiets them
    and is the correct header for apps that open OAuth popups.
    """
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
    return response

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
if not GOOGLE_CLIENT_ID:
    logger.warning(
        "GOOGLE_CLIENT_ID is not set as an environment variable on this server. "
        "Google sign-in will return 500 until this is set in Vercel's "
        "Project Settings -> Environment Variables (and the app is redeployed)."
    )

# --- Persistent storage for logged-in users' saved schemes ---
#
# Vercel's serverless functions run on a read-only filesystem except /tmp,
# and /tmp itself is NOT persistent - it can be wiped between requests
# whenever a cold start happens or a request lands on a different
# underlying instance. A JSON file on disk therefore cannot reliably keep a
# signed-in user's saved schemes around, which was the root cause of
# "I save it, refresh, and it's gone" even while logged in.
#
# Fix: use Vercel KV (a managed Redis, free tier available) when it's
# connected to this project - Vercel auto-injects KV_REST_API_URL and
# KV_REST_API_TOKEN as environment variables once you attach a KV store
# from the Vercel dashboard's "Storage" tab. Each user's saved schemes are
# stored under their own key ("saved:<google_sub>"), so it's one small
# read/write per request instead of loading everyone's data every time.
#
# If those env vars aren't present (e.g. running locally with
# `python3 app.py`), everything falls back to the old /tmp JSON file so
# local development keeps working without any extra setup - it just won't
# survive a real Vercel cold start, exactly as before.
KV_REST_API_URL = os.environ.get('KV_REST_API_URL')
KV_REST_API_TOKEN = os.environ.get('KV_REST_API_TOKEN')
SAVED_SCHEMES_PATH = os.environ.get('SAVED_SCHEMES_PATH') or os.path.join('/tmp', 'saved_schemes.json')


def _kv_configured():
    return bool(KV_REST_API_URL and KV_REST_API_TOKEN)


def _kv_get_json(key, default):
    """GET a JSON value from Vercel KV via its REST API. Returns `default` on any miss/error."""
    import urllib.request
    import urllib.parse
    url = f"{KV_REST_API_URL.rstrip('/')}/get/{urllib.parse.quote(key, safe='')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        raw = payload.get('result')
        return json.loads(raw) if raw else default
    except Exception:
        logger.error("Vercel KV GET failed for key %s:\n%s", key, traceback.format_exc())
        return default


def _kv_set_json(key, value):
    """SET a JSON value in Vercel KV via its REST API. Returns True on success."""
    import urllib.request
    import urllib.parse
    url = f"{KV_REST_API_URL.rstrip('/')}/set/{urllib.parse.quote(key, safe='')}"
    body = json.dumps(value, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        return True
    except Exception:
        logger.error("Vercel KV SET failed for key %s:\n%s", key, traceback.format_exc())
        return False


def _load_file_store():
    if os.path.exists(SAVED_SCHEMES_PATH):
        with open(SAVED_SCHEMES_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _write_file_store(store):
    os.makedirs(os.path.dirname(SAVED_SCHEMES_PATH), exist_ok=True)
    with open(SAVED_SCHEMES_PATH, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def _load_user_saved(user_key):
    """Returns {scheme_name: scheme_dict, ...} for this signed-in user."""
    if _kv_configured():
        return _kv_get_json(f"saved:{user_key}", {})
    store = _load_file_store()
    return store.get(user_key, {})


def _write_user_saved(user_key, user_saved):
    if _kv_configured():
        _kv_set_json(f"saved:{user_key}", user_saved)
        return
    store = _load_file_store()
    store[user_key] = user_saved
    _write_file_store(store)


def _current_user_key():
    """The signed-in user's stable ID (Google's 'sub' claim), or None for guests."""
    user = session.get('user')
    return user['sub'] if user else None


PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50  # a ceiling per-request so a bad call can't ask for everything at once


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
    except ValueError as e:
        logger.warning("Google token verification failed: %s", e)
        return jsonify({"error": "Invalid or expired Google token"}), 401
    except Exception:
        # Catch-all so an unexpected error (network issue, library bug, etc.)
        # still logs a full traceback instead of dying silently.
        logger.error("Unexpected error verifying Google token:\n%s", traceback.format_exc())
        return jsonify({"error": "Sign-in failed unexpectedly. Please try again."}), 500

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
    user_saved = _load_user_saved(user_key)
    return jsonify(list(user_saved.values()))


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
    user_saved = _load_user_saved(user_key)

    schemes_to_add = body.get('schemes')
    if schemes_to_add is None and body.get('scheme'):
        schemes_to_add = [body['scheme']]

    for s in (schemes_to_add or []):
        name = (s or {}).get('scheme_name')
        if name:
            user_saved[name] = s

    _write_user_saved(user_key, user_saved)
    return jsonify(list(user_saved.values()))


@app.route('/saved/<path:scheme_name>', methods=['DELETE'])
def remove_saved(scheme_name):
    user_key = _current_user_key()
    if not user_key:
        return jsonify({"error": "Not logged in"}), 401
    user_saved = _load_user_saved(user_key)
    user_saved.pop(scheme_name, None)
    _write_user_saved(user_key, user_saved)
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
