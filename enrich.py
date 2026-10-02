#!/usr/bin/env python3
"""Stage 2: Enrich businesses with email addresses via Hunter.io API.

Usage:
    python enrich.py                    # enrich all businesses with no email
    python enrich.py --domain example.com  # look up one domain
    python enrich.py --limit 10          # enrich only first 10

Requires: HUNTER_API_KEY in environment or .env file.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent
BUSINESSES_FILE = DATA_DIR / "businesses.json"

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
if not HUNTER_API_KEY:
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("HUNTER_API_KEY="):
                HUNTER_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")

HUNTER_API_URL = "https://api.hunter.io/v2"


def hunter_domain_search(domain):
    """Find emails for a domain using Hunter.io domain search."""
    if not HUNTER_API_KEY:
        return {"error": "HUNTER_API_KEY not set"}
    url = f"{HUNTER_API_URL}/domain-search?domain={domain}&api_key={HUNTER_API_KEY}"
    result = subprocess.run(
        ["curl", "-s", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=15)
    if result.returncode != 0:
        return {"error": f"curl failed: {result.stderr}"}
    return json.loads(result.stdout)


def hunter_email_verify(email):
    """Verify an email address via Hunter.io."""
    if not HUNTER_API_KEY:
        return {"error": "HUNTER_API_KEY not set"}
    url = f"{HUNTER_API_URL}/email-verifier?email={email}&api_key={HUNTER_API_KEY}"
    result = subprocess.run(
        ["curl", "-s", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=15)
    if result.returncode != 0:
        return {"error": f"curl failed: {result.stderr}"}
    return json.loads(result.stdout)


def extract_domain(biz):
    """Extract domain from business website URL."""
    website = biz.get("website", "")
    if not website:
        return None
    # Remove protocol
    domain = website.replace("https://", "").replace("http://", "")
    # Remove path
    domain = domain.split("/")[0]
    return domain


def enrich_business(biz):
    """Enrich a single business with email data."""
    domain = extract_domain(biz)
    if not domain:
        # Try to find domain from business name
        return {
            "email": biz.get("email", ""),
            "domain": None,
            "source": "osm",
            "confidence": 0,
        }

    data = hunter_domain_search(domain)
    if "error" in data:
        return {
            "email": biz.get("email", ""),
            "domain": domain,
            "source": "hunter_error",
            "error": data["error"],
            "confidence": 0,
        }

    emails = data.get("data", {}).get("emails", [])
    if not emails:
        return {
            "email": biz.get("email", ""),
            "domain": domain,
            "source": "hunter_no_results",
            "confidence": 0,
        }

    # Find the best email (CEO/founder/owner first, then general)
    best = None
    for e in emails:
        position = (e.get("position", "") or "").lower()
        if any(role in position for role in ["ceo", "founder", "owner", "director", "manager"]):
            best = e
            break
    if not best:
        # Fall back to first email
        best = emails[0]

    return {
        "email": best.get("value", biz.get("email", "")),
        "domain": domain,
        "source": "hunter",
        "first_name": best.get("first_name", ""),
        "last_name": best.get("last_name", ""),
        "position": best.get("position", ""),
        "confidence": best.get("confidence", 0),
        "linkedin": best.get("linkedin", ""),
        "all_emails": [e.get("value") for e in emails[:5]],
    }


def load_businesses():
    """Load businesses from JSON file."""
    if not BUSINESSES_FILE.exists():
        return []
    return json.loads(BUSINESSES_FILE.read_text())


def save_businesses(businesses):
    """Save businesses to JSON file."""
    BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))


def enrich_all(limit=None, skip_existing=True):
    """Enrich all businesses that don't have emails yet."""
    businesses = load_businesses()
    enriched_count = 0
    processed = 0

    for i, biz in enumerate(businesses):
        if limit and processed >= limit:
            break

        # Skip if already enriched
        if skip_existing and biz.get("enrichment", {}).get("email"):
            continue

        # Skip if already has email from OSM
        if skip_existing and biz.get("email") and not biz.get("enrichment"):
            continue

        processed += 1
        print(f"[{processed}/{limit or len(businesses)}] Enriching: {biz.get('name', 'Unknown')}...")
        enrichment = enrich_business(biz)
        biz["enrichment"] = enrichment
        if enrichment.get("email"):
            enriched_count += 1
            print(f"  Found email: {enrichment['email']} ({enrichment.get('position', 'N/A')})")
        else:
            print(f"  No email found")

        # Rate limit: Hunter.io free tier = 25 requests/month
        time.sleep(0.5)

    save_businesses(businesses)
    print(f"\nDone. Processed {processed} businesses, enriched {enriched_count} with emails.")
    return businesses


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enrich businesses with Hunter.io emails")
    parser.add_argument("--domain", help="Look up a single domain")
    parser.add_argument("--limit", type=int, help="Max businesses to enrich")
    parser.add_argument("--no-skip", action="store_true", help="Re-enrich all businesses")
    args = parser.parse_args()

    if args.domain:
        data = hunter_domain_search(args.domain)
        print(json.dumps(data, indent=2))
    else:
        enrich_all(limit=args.limit, skip_existing=not args.no_skip)
