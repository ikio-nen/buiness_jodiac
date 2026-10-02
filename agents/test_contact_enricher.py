"""Regression tests for the contact-enrichment layer (contact_enricher.py).

Pins the contract that makes it production-safe:
  1. Phones: libphonenumber validation — junk dies, mobiles get wa.me
     links, landlines don't.
  2. Email deliverability: syntax-bad and nonexistent domains are caught
     offline; the gmail leg is a real MX probe (network, DNS-down tolerant).
  3. Cache: roundtrip, city scoping, TTL expiry.
  4. Promotion rules: a verified+deliverable contact becomes the recipient
     (through the cache path, which skips the network entirely); an
     unverified one never does.
  5. DNS pre-filter: NXDOMAIN candidate domains die in milliseconds.
  6. Sucuri anti-bot solver: decodes a synthetic gate stub offline.
  7. CSV export carries whatsapp + email_status columns.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.contact_enricher import (
    CACHE_PATH,
    cache_get,
    cache_put,
    email_deliverability,
    enrich_businesses,
    parse_phone,
    whatsapp_link,
)
from agents.contact_export import contact_rows
from agents.contact_finder import _decode_sucuri_cookie, _dns_resolves

passed = failed = 0


def check(name: str, ok: bool, detail="") -> None:
    global passed, failed
    mark = "[ok]" if ok else "[FAIL]"
    print(f"  {mark} {name}{'' if ok else f'  {detail}'}")
    if ok:
        passed += 1
    else:
        failed += 1


print("== Phone validation (libphonenumber) ==")
m = parse_phone("+91 98301 23456")
check("indian mobile parses to E.164",
      m.get("e164") == "+919830123456" and m.get("is_mobile") is True, str(m))
check("mobile gets a wa.me link",
      whatsapp_link(m) == "https://wa.me/919830123456")
l = parse_phone("033 2248 1234")
check("landline validates but gets NO wa.me link",
      bool(l) and l.get("is_mobile") is False and whatsapp_link(l) == "", str(l))
check("harvested junk dies (timestamps, coords, short codes)",
      not parse_phone("12345") and not parse_phone("") and not parse_phone("999")
      and not parse_phone("2026-09-24"))
check("foreign junk dies",
      not parse_phone("011 555 0123", region="IN") or parse_phone("011 555 0123") == {})

print("== Email deliverability ==")
check("syntax-bad rejected offline",
      email_deliverability("not-an-email")[0] == "invalid")
check("nonexistent domain -> undeliverable (NXDOMAIN is authoritative)",
      email_deliverability("x@nonexistent-domain-xyz123abc.com")[0] == "undeliverable")
st, _det = email_deliverability("someone@gmail.com")
check("real MX probe: gmail deliverable (or DNS down -> unverified, honest)",
      st in ("deliverable", "unverified"), f"{st}")

print("== Cache ==")
CACHE_PATH.unlink(missing_ok=True)
cache_put("Test Academy", "kolkata",
          {"email": "a@b.in", "phone": "+919830123456",
           "whatsapp": "https://wa.me/919830123456",
           "sources": {"email_verified": True},
           "candidates": [{"email": "a@b.in", "status": "deliverable",
                           "detail": "mx confirmed"}]})
hit = cache_get("Test Academy", "kolkata")
check("roundtrip keeps contact + sources", hit and hit["email"] == "a@b.in"
      and hit["sources"].get("email_verified") is True, str(hit))
check("city-scoped: different city misses", cache_get("Test Academy", "delhi") is None)
cache_put("Old Academy", "kolkata", {"email": "old@b.in"})
cache = __import__("json").loads(CACHE_PATH.read_text(encoding="utf-8"))
from agents.contact_enricher import _cache_key
cache[_cache_key("Old Academy", "kolkata")]["ts"] = (
    datetime.now() - timedelta(days=20)).isoformat()
CACHE_PATH.write_text(__import__("json").dumps(cache), encoding="utf-8")
check("expired entry (>14d) treated as miss", cache_get("Old Academy", "kolkata") is None)

print("== Promotion rules (through the cache path -- no network) ==")
biz = {"name": "Test Academy", "city": "kolkata"}
enrich_businesses([biz], budget=10.0, log=lambda *a: None)
check("verified + deliverable cache contact becomes the recipient",
      biz.get("email") == "a@b.in", str(biz.get("email")))
check("validated mobile becomes the phone + carries its wa.me link",
      biz.get("phone") == "+919830123456"
      and biz.get("whatsapp_link") == "https://wa.me/919830123456",
      f"{biz.get('phone')} {biz.get('whatsapp_link')}")
cache_put("Shady College", "kolkata",
          {"email": "shady@c.in", "phone": "", "whatsapp": "",
           "sources": {"email_verified": False}})
biz2 = {"name": "Shady College", "city": "kolkata"}
enrich_businesses([biz2], budget=10.0, log=lambda *a: None)
check("UNVERIFIED contact is visible but never promoted to the recipient",
      biz2.get("email") is None
      and (biz2.get("enrichment_v2") or {}).get("unpromoted_email") == "shady@c.in",
      str(biz2.get("enrichment_v2")))

print("== DNS pre-filter ==")
check("NXDOMAIN candidate dies fast (no HTTP retry storm)",
      _dns_resolves("definitely-not-a-domain-xyz123abc.com") is False)
check("real domain resolves",
      _dns_resolves("gmail.com") is True)

print("== Sucuri anti-bot solver (synthetic gate stub) ==")
import base64
cookie_name, cookie_val = "sucuri_cloudproxy_uuid_1a2b", "3e26880ced81"
inner = (f"o='3' + 'e' + \"2\" + \"6\" + String.fromCharCode(56) + '8' + "
         f"'{cookie_val[6:]}';"
         f"document.cookie='s'+'u'+'c'+'u'+'r'+'i'+'_cloudproxy_uuid_1a2b'"
         f'+\"=\" + o + \';path=/;max-age=86400\'; location.reload();')
stub = f"<html><script>var S='{base64.b64encode(inner.encode()).decode()}';</script></html>"
solved = _decode_sucuri_cookie(stub)
check("decodes name+value from the eval-blob construction",
      solved == (cookie_name, cookie_val), str(solved))
check("ordinary page -> no solution, no crash", _decode_sucuri_cookie("<html></html>") is None)

print("== CSV export columns ==")
rows = contact_rows([biz])
check("whatsapp + email_status columns present and filled",
      rows and rows[0].get("whatsapp") == "https://wa.me/919830123456"
      and rows[0].get("email_status") == "deliverable", str(rows))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
