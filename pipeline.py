#!/usr/bin/env python3
"""Pipeline orchestrator — runs all 5 stages in sequence.

Usage:
    python pipeline.py --search "London" --radius 2000
    python pipeline.py --lat 51.5074 --lon -0.1278 --radius 1000
    python pipeline.py --enrich-only
    python pipeline.py --dry-run
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent
BUSINESSES_FILE = DATA_DIR / "businesses.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

DEFAULT_CATEGORIES = ["shop", "amenity", "office", "craft", "healthcare"]


def geocode(query):
    """Geocode an address to lat/lon via Nominatim."""
    import urllib.parse
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
    result = subprocess.run(
        ["curl", "-s", "-H", "User-Agent: BizFinder/1.0", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=10)
    data = json.loads(result.stdout)
    if not data:
        return None
    return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]),
            "display": data[0].get("display_name", "")}


def stage_discover(lat, lon, radius=1000, categories=None):
    """Stage 1: Discover businesses via Overpass API."""
    print(f"\n=== Stage 1: DISCOVER ===")
    print(f"Location: {lat}, {lon} | Radius: {radius}m")

    if categories is None:
        categories = DEFAULT_CATEGORIES

    parts = []
    for c in categories:
        parts.append(f'node["{c}"](around:{radius},{lat},{lon});')
        parts.append(f'way["{c}"](around:{radius},{lat},{lon});')
        parts.append(f'relation["{c}"](around:{radius},{lat},{lon});')

    query = '[out:json][timeout:25];(' + "".join(parts) + ");out center;"
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", OVERPASS_URL, "-d", f"data={query}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=30)

    data = json.loads(result.stdout)
    elements = data.get("elements", [])

    businesses = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", tags.get("brand", f"Unnamed {tags.get('shop', tags.get('amenity', ''))}"))
        el_lat = el.get("lat") or el.get("center", {}).get("lat")
        el_lon = el.get("lon") or el.get("center", {}).get("lon")

        businesses.append({
            "id": el.get("id"),
            "name": name,
            "lat": el_lat, "lon": el_lon,
            "website": tags.get("website", tags.get("contact:website", "")),
            "phone": tags.get("phone", tags.get("contact:phone", "")),
            "email": tags.get("email", tags.get("contact:email", "")),
            "category": f"{tags.get(list(tags.keys())[0], '')}" if tags else "",
            "enrichment": {},
            "outreach": {},
        })

    print(f"Found {len(businesses)} businesses")
    return businesses


def stage_enrich(businesses):
    """Stage 2: Enrich businesses with emails."""
    print(f"\n=== Stage 2: ENRICH ===")
    # Import and use enrich module
    sys.path.insert(0, str(DATA_DIR))
    from enrich import enrich_business

    enriched = 0
    for biz in businesses:
        enrichment = enrich_business(biz)
        biz["enrichment"] = enrichment
        if enrichment.get("email"):
            enriched += 1
            print(f"  + {biz['name']}: {enrichment['email']}")
        else:
            print(f"  - {biz['name']}: no email found")

    print(f"Enriched {enriched}/{len(businesses)} businesses with emails")
    return businesses


def stage_outreach(businesses, dry_run=False):
    """Stage 3: Send cold emails."""
    print(f"\n=== Stage 3: OUTREACH (email) ===")
    if dry_run:
        print("[DRY RUN] Would send emails to businesses with emails")

    count = 0
    for biz in businesses:
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        if email:
            if dry_run:
                print(f"  [DRY RUN] Would send to {email} ({biz['name']})")
            else:
                print(f"  Sending to {email} ({biz['name']})...")
            count += 1

    print(f"{f'Would send' if dry_run else 'Sending'} {count} emails")
    return businesses


def stage_sites(businesses):
    """Stage 4: Build websites for businesses without one."""
    print(f"\n=== Stage 4: WEBSITES ===")
    sys.path.insert(0, str(DATA_DIR))
    from site_builder import generate_for_all

    results = generate_for_all(businesses)
    print(f"Generated {len(results)} websites")
    return businesses


def stage_whatsapp(businesses, dry_run=False):
    """Stage 5: WhatsApp outreach."""
    print(f"\n=== Stage 5: WHATSAPP ===")
    count = sum(1 for b in businesses if b.get("phone"))
    if dry_run:
        print(f"[DRY RUN] Would send {count} WhatsApp messages")
    return businesses


def save(businesses):
    """Save results to businesses.json."""
    BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))
    print(f"\nSaved {len(businesses)} businesses to {BUSINESSES_FILE}")


def run_pipeline(lat=None, lon=None, search=None, radius=1000, dry_run=False,
                 skip_discover=False, skip_enrich=False):
    """Run the full pipeline."""
    businesses = []

    # Stage 1: Discover
    if not skip_discover:
        if search:
            geo = geocode(search)
            if not geo:
                print(f"Could not geocode: {search}")
                return
            lat, lon = geo["lat"], geo["lon"]
            print(f"Geocoded to: {geo['display'][:80]}")

        if lat is None or lon is None:
            print("Error: provide --lat/--lon or --search")
            return

        businesses = stage_discover(lat, lon, radius)
        save(businesses)
    else:
        if BUSINESSES_FILE.exists():
            businesses = json.loads(BUSINESSES_FILE.read_text())
            print(f"Loaded {len(businesses)} businesses from file")
        else:
            print("No businesses file found. Run without --skip-discover first.")
            return

    # Stage 2: Enrich
    if not skip_enrich:
        businesses = stage_enrich(businesses)
        save(businesses)

    # Stage 3: Outreach (email)
    businesses = stage_outreach(businesses, dry_run=dry_run)

    # Stage 4: Build websites
    businesses = stage_sites(businesses)
    save(businesses)

    # Stage 5: WhatsApp
    businesses = stage_whatsapp(businesses, dry_run=dry_run)

    # Summary
    with_email = sum(1 for b in businesses if b.get("email") or b.get("enrichment", {}).get("email"))
    with_phone = sum(1 for b in businesses if b.get("phone"))
    with_site = sum(1 for b in businesses if b.get("website"))
    generated = sum(1 for b in businesses if b.get("generated_site"))

    print(f"\n=== SUMMARY ===")
    print(f"Total businesses: {len(businesses)}")
    print(f"With email: {with_email}")
    print(f"With phone: {with_phone}")
    print(f"With website: {with_site}")
    print(f"Generated sites: {generated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full lead-gen pipeline")
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--search", help="Address/city to search")
    parser.add_argument("--radius", type=int, default=1000, help="Search radius in meters")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--skip-discover", action="store_true", help="Skip discovery stage")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip enrichment stage")
    args = parser.parse_args()

    run_pipeline(
        lat=args.lat, lon=args.lon, search=args.search,
        radius=args.radius, dry_run=args.dry_run,
        skip_discover=args.skip_discover, skip_enrich=args.skip_enrich,
    )
