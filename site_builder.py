#!/usr/bin/env python3
"""Stage 4: Generate simple HTML websites for businesses that don't have one.

Usage:
    python site_builder.py                    # build sites for all businesses without websites
    python site_builder.py --name "Joe's Cafe" --address "123 Main St" --phone "555-1234"
"""

import datetime
import html as html_mod
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent
BUSINESSES_FILE = DATA_DIR / "businesses.json"
SITES_DIR = DATA_DIR / "sites"


def generate_html(biz):
    """Generate a simple responsive HTML page for a business."""
    name = html_mod.escape(biz.get("name", "Local Business"))
    addr = html_mod.escape(biz.get("address", ""))
    phone = biz.get("phone", "")
    category = html_mod.escape(biz.get("category", ""))
    website = biz.get("website", "")
    year = datetime.datetime.now().year

    phone_section = f'<p class="phone">Phone: {html_mod.escape(phone)}</p>' if phone else ""
    website_link = f'<p><a href="{html_mod.escape(website)}" target="_blank">{html_mod.escape(website)}</a></p>' if website else ""
    category_badge = f'<span class="badge">{category}</span>' if category else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: #333; line-height: 1.6; }}
        .hero {{ background: linear-gradient(135deg, #1e3a5f, #2d5a87); color: white;
                 padding: 60px 20px; text-align: center; }}
        .hero h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .hero .badge {{ background: rgba(255,255,255,0.2); padding: 4px 12px;
                       border-radius: 20px; font-size: 0.9em; }}
        .content {{ max-width: 800px; margin: 0 auto; padding: 40px 20px; }}
        .info-card {{ background: #f8f9fa; border-radius: 8px; padding: 30px;
                     margin: 20px 0; border-left: 4px solid #2d5a87; }}
        .info-card p {{ margin: 8px 0; font-size: 1.1em; }}
        .phone {{ color: #2d5a87; font-weight: bold; font-size: 1.3em; }}
        .cta {{ text-align: center; margin: 40px 0; }}
        .cta a {{ display: inline-block; background: #2d5a87; color: white;
                 padding: 14px 32px; border-radius: 6px; text-decoration: none;
                 font-size: 1.1em; font-weight: bold; }}
        .cta a:hover {{ background: #1e3a5f; }}
        footer {{ text-align: center; padding: 20px; color: #999; font-size: 0.85em; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>{name}</h1>
        {category_badge}
    </div>
    <div class="content">
        <div class="info-card">
            <p><strong>Address:</strong> {addr}</p>
            {phone_section}
            {website_link}
        </div>
        <div class="cta">
            {'<a href="tel:' + phone + '">Call Now</a>' if phone else '<p style="color:#999">No phone number available</p>'}
        </div>
    </div>
    <footer>&copy; {year} {name}. All rights reserved.</footer>
</body>
</html>"""
    return html


def generate_site(biz, output_dir=None):
    """Generate a static HTML site for a business."""
    if output_dir is None:
        output_dir = SITES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    name_slug = re.sub(r'[^a-z0-9]+', '-', biz.get("name", "business").lower()).strip('-')
    filename = f"{name_slug}.html"
    filepath = output_dir / filename

    html = generate_html(biz)
    filepath.write_text(html)

    return {
        "filename": filename,
        "filepath": str(filepath),
        "name": biz.get("name", "Business"),
    }


def load_businesses():
    """Load businesses from JSON file."""
    if not BUSINESSES_FILE.exists():
        return []
    return json.loads(BUSINESSES_FILE.read_text())


def generate_for_all(businesses=None):
    """Generate sites for businesses without websites."""
    if businesses is None:
        businesses = load_businesses()
    results = []
    for biz in businesses:
        if not biz.get("website"):
            result = generate_site(biz)
            biz["generated_site"] = result
            results.append(result)
            print(f"  Generated site for {biz.get('name')}: {result['filename']}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate websites for businesses")
    parser.add_argument("--name", help="Business name (for single site)")
    parser.add_argument("--address", help="Address")
    parser.add_argument("--phone", help="Phone number")
    parser.add_argument("--category", help="Category")
    args = parser.parse_args()

    if args.name:
        biz = {
            "name": args.name,
            "address": args.address or "",
            "phone": args.phone or "",
            "category": args.category or "",
        }
        result = generate_site(biz)
        print(f"Generated: {result['filepath']}")
    else:
        generate_for_all()
