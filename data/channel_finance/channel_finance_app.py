"""
Backend for Feature #3: Geo-Spatial Partner Locator & Router.

Run: python3 channel_finance_app.py
Then open: http://localhost:5001

Expects (in the SAME folder as this file, or update the paths below):
  channel_partners.json  (from build_partners.py + geocode_partners.py)
  loan_schemes.json
"""
import os
import json
import math
from flask import Flask, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARTNERS_PATH = os.path.join(BASE_DIR, 'channel_partners.json')
SCHEMES_PATH = os.path.join(BASE_DIR, 'loan_schemes.json')

with open(PARTNERS_PATH, encoding='utf-8') as f:
    ALL_PARTNERS = json.load(f)

with open(SCHEMES_PATH, encoding='utf-8') as f:
    ALL_SCHEMES = json.load(f)

app = Flask(__name__)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lng points, in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@app.route('/')
def home():
    return send_from_directory(BASE_DIR, 'locator.html')


@app.route('/loan-schemes', methods=['GET'])
def loan_schemes():
    """List the 3 NSFDC credit products, for the frontend's dropdown."""
    return jsonify(ALL_SCHEMES)


@app.route('/nearest-partners', methods=['POST'])
def nearest_partners():
    """
    Input JSON: { "lat": <user_lat>, "lng": <user_lng>, "loan_category": "micro_finance" | "term_loan" | "education_loan", "limit": 10 (optional) }
    Returns nearest ELIGIBLE partners (matching loan_category, not high-NPA-flagged), sorted by distance.
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
            continue  # skip partners that failed geocoding
        # ELIGIBILITY GATE 1: excludes high-NPA-flagged partners (SIMULATED
        # field for demo - see build_partners.py docstring for why).
        if p.get('eligibility_status') == 'high_npa_flagged':
            continue
        # ELIGIBILITY GATE 2: partner must actually handle the requested
        # loan category (a pure NBFC-MFI shouldn't be suggested for an
        # Education Loan, for example).
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


if __name__ == '__main__':
    app.run(debug=True, port=5001)
