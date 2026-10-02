#!/usr/bin/env python3
"""BizFinder — find local businesses via OpenStreetMap Overpass API."""

import json
import subprocess
import urllib.parse
import traceback
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Business category tags to search for
DEFAULT_CATEGORIES = [
    "shop", "amenity", "office", "craft",
    "healthcare", "leisure", "tourism",
]

# Category labels for the UI
CATEGORY_LABELS = {
    "shop": "Retail / Shop",
    "amenity": "Restaurant / Service",
    "office": "Office / Business",
    "craft": "Craft / Artisan",
    "healthcare": "Healthcare",
    "leisure": "Leisure / Entertainment",
    "tourism": "Tourism / Hospitality",
}


def overpass(query):
    """Send a query to the Overpass API via curl and return parsed JSON."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", OVERPASS_URL,
         "-d", f"data={query}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    if not result.stdout:
        raise RuntimeError("Overpass returned empty response")
    return json.loads(result.stdout)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    """Search for businesses near a lat/lon via Overpass API."""
    try:
        body = request.get_json()
        lat = float(body.get("lat", 0))
        lon = float(body.get("lon", 0))
        radius_m = int(body.get("radius", 1000))
        categories = body.get("categories", DEFAULT_CATEGORIES)

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

        # Build Overpass query
        parts = []
        for c in categories:
            parts.append(f'node["{c}"](around:{radius_m},{lat},{lon});')
            parts.append(f'way["{c}"](around:{radius_m},{lat},{lon});')
            parts.append(f'relation["{c}"](around:{radius_m},{lat},{lon});')

        query = '[out:json][timeout:25];(' + "".join(parts) + ");out center;"

        data = overpass(query)
        elements = data.get("elements", [])

        businesses = []
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "Unnamed")
            if not name or name == "Unnamed":
                # Try to build a name from tags
                brand = tags.get("brand", "")
                if brand:
                    name = brand
                else:
                    shop_type = tags.get("shop", tags.get("amenity", tags.get("office", "")))
                    name = f"Unnamed {shop_type}" if shop_type else "Unnamed Business"

            el_lat = el.get("lat") or el.get("center", {}).get("lat")
            el_lon = el.get("lon") or el.get("center", {}).get("lon")

            businesses.append({
                "id": el.get("id"),
                "name": name,
                "lat": el_lat,
                "lon": el_lon,
                "website": tags.get("website", tags.get("contact:website", "")),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "email": tags.get("email", tags.get("contact:email", "")),
                "address": format_address(tags),
                "opening_hours": tags.get("opening_hours", ""),
                "category": get_primary_category(tags, categories),
                "tags": tags,
            })

        return jsonify({
            "businesses": businesses,
            "count": len(businesses),
            "center": {"lat": lat, "lon": lon},
            "radius": radius_m,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/reverse", methods=["POST"])
def reverse_geocode():
    """Reverse geocode lat/lon to get a place name via Nominatim."""
    try:
        body = request.get_json()
        lat = float(body.get("lat", 0))
        lon = float(body.get("lon", 0))

        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=14"
        result = subprocess.run(
            ["curl", "-s", "-H", "User-Agent: BizFinder/1.0", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=10)
        data = json.loads(result.stdout)

        return jsonify({
            "display_name": data.get("display_name", ""),
            "address": data.get("address", {}),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def format_address(tags):
    """Format an address from OSM tags."""
    parts = []
    for key in ["housenumber", "street", "road", "suburb", "city", "town", "village",
                 "state", "postcode", "country"]:
        val = tags.get(f"addr:{key}", "")
        if val:
            parts.append(val)
    return ", ".join(parts) if parts else ""


def get_primary_category(tags, categories):
    """Get the primary category label for a business."""
    for c in categories:
        if c in tags:
            val = tags[c]
            label = CATEGORY_LABELS.get(c, c)
            return f"{label}: {val}"
    return "Other"


if __name__ == "__main__":
    print("BizFinder running at http://localhost:5000")
    app.run(debug=True, port=5000)
