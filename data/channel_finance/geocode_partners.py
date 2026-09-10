"""
Adds latitude/longitude to each channel partner using OpenStreetMap's free
Nominatim geocoding API. Run this on YOUR machine (needs internet) - it can't
run in the sandbox that built channel_partners.json.

Run: python3 geocode_partners.py
Input:  channel_partners.json
Output: channel_partners.json  (overwritten in place, with lat/lng filled in)

Nominatim's usage policy requires max 1 request/second and a real User-Agent -
this script respects both. For 106 partners this takes ~2 minutes.

NOTE: if your channel_partners.json already has latitude/longitude filled in
from an OLDER run of this script (before the "location_precision" field
existed), re-running this script as-is will NOT fix them - the skip check
below now looks for "location_precision", not latitude, specifically so it
re-geocodes those stale/bad entries instead of leaving them alone.
"""
import json
import time
import re
import ssl
import certifi
import urllib.request
import urllib.parse

IN_PATH = "channel_partners.json"

HEADERS = {"User-Agent": "YojanaMatch-ChannelFinance-Locator/1.0 (hackathon project)"}
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def raw_geocode(query, retries=1):
    """
    BUG FIX: the old version put `time.sleep(1)` AFTER the success `return`,
    inside the same function - so it only ever ran on the FAILURE path. Every
    successful lookup (the vast majority - ~100 of 106 partners) returned
    immediately with NO delay before the next request fired, silently
    violating Nominatim's 1-request/second policy for most of the run. That's
    the most likely reason a handful of otherwise-fine addresses (Gandhinagar,
    Dumka, Agartala, Mumbai) came back empty and fell all the way through to
    the state-centroid fallback - Nominatim was probably throttling/dropping
    requests fired too close together, not failing to find the place.
    Now the sleep always runs (success or failure, via `finally`), and a
    failed lookup gets one retry after that same 1s wait before giving up.
    """
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1
    })
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            print(f"  ! geocoding failed for '{query}' (attempt {attempt+1}): {e}")
        finally:
            time.sleep(1)  # always wait 1s, success or failure, before the next call
    return None, None


def geocode(address, state):
    """
    BUG FIX: previously, when the full-address query failed, this fell
    straight back to geocoding just the STATE NAME - which gives every
    failed partner in the same state the exact same coordinate (state
    centroid). That's why 3 different Gujarat partners (Gandhinagar,
    Rajkot, Vadodara) all showed an identical, wrong distance in the
    locator - they'd all silently collapsed onto one point.
    Now tries three levels of precision, in order, and records which level
    actually worked so the frontend can flag low-precision entries instead
    of silently pretending they're exact:
      1. Full address + state (most precise)
      2. The 6-digit PIN code alone, if the address has one (city-level -
         Nominatim has solid coverage of Indian postal codes)
      3. State name only (last resort - explicitly marked as approximate)
    """
    lat, lon = raw_geocode(f"{address}, {state}, India")
    if lat is not None:
        return lat, lon, "exact"

    pin_match = re.search(r'\b(\d{6})\b', address)
    if pin_match:
        lat, lon = raw_geocode(f"{pin_match.group(1)}, India")
        if lat is not None:
            return lat, lon, "pincode"

    # NEW: locality fallback. Addresses full of internal building references
    # ("Karmayogi Bhavan, Block 2, D2 Wing, 4th Floor...") or landmark-style
    # text ("Near Nagar Palika Chowk...") confuse Nominatim as a whole string,
    # even though the city/town name buried in there would geocode fine on
    # its own. Take the last comma-separated segment that ISN'T just the
    # state name repeated, and try that alone - city-level, much better than
    # the whole state.
    segments = [s.strip() for s in address.split(',') if s.strip()]
    locality = None
    for seg in reversed(segments):
        seg_clean = re.sub(r'-?\s*\d{6}\b', '', seg).strip()  # strip trailing PIN if attached
        if seg_clean and seg_clean.lower() != state.lower():
            locality = seg_clean
            break
    if locality:
        lat, lon = raw_geocode(f"{locality}, {state}, India")
        if lat is not None:
            return lat, lon, "locality"

    lat, lon = raw_geocode(f"{state}, India")
    return lat, lon, "state_approximate"

with open(IN_PATH, encoding="utf-8") as f:
    partners = json.load(f)

for i, p in enumerate(partners):
    if p.get("location_precision") not in (None, "state_approximate"):
        # Skip entries that already got a good result (exact/pincode/locality).
        # Re-attempt anything still stuck at "state_approximate" too, since the
        # rate-limit and locality-fallback fixes above mean a previously-failed
        # address may succeed this time around.
        continue
    lat, lon, precision = geocode(p["address"], p["state"])
    p["latitude"] = lat
    p["longitude"] = lon
    p["location_precision"] = precision  # "exact" / "pincode" / "state_approximate"
    print(f"[{i+1}/{len(partners)}] {p['name'][:50]:50s} -> {lat}, {lon} ({precision})")

with open(IN_PATH, "w", encoding="utf-8") as f:
    json.dump(partners, f, indent=2, ensure_ascii=False)

missing = sum(1 for p in partners if p["latitude"] is None)
locality_tier = sum(1 for p in partners if p.get("location_precision") == "locality")
approx = sum(1 for p in partners if p.get("location_precision") == "state_approximate")
print(f"\nDone. {len(partners) - missing}/{len(partners)} geocoded successfully.")
if locality_tier:
    print(f"{locality_tier} partner(s) only matched at city/locality level (address text was too messy for an exact match) - these are city-accurate, fine to use.")
print(f"{approx} partner(s) only got a STATE-LEVEL approximate location (no precise address/pincode/locality match) - these will show noticeably wrong distances for nearby users.")
if missing:
    print(f"{missing} partners still missing coordinates - check their address text manually.")
