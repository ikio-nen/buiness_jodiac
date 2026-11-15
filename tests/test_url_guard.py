"""tests/test_url_guard.py — the SSRF guard in front of every scraper fetch.

Each blocked case is a URL that a business website, a search result or a model
answer could hand the fetcher: the loopback API (where the launch cookie
lives), a router on the LAN, the cloud metadata endpoint, and the DNS tricks
that turn a public-looking name into 127.0.0.1.
"""
import pytest

from agents.url_guard import (MAX_REDIRECTS, UnsafeURL, check_final_url,
                              is_safe_url, safe_url)

BLOCKED = [
    # loopback — the app's own API, where the session cookie is valid
    "http://127.0.0.1:8765/api/status",
    "http://127.0.0.1/",
    "https://127.1.2.3/",
    "http://localhost/",
    "http://LOCALHOST:8765/",
    "http://localhost./",
    "http://sub.localhost/",
    # private and carrier-grade ranges
    "http://10.0.0.5/",
    "http://172.16.4.4/admin",
    "http://192.168.1.1/",
    "http://100.64.0.1/",
    "http://0.0.0.0/",
    # link-local: cloud metadata
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    # IPv6 equivalents, including an IPv4-mapped loopback
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fc00::1]/",
    "http://[::ffff:127.0.0.1]/",
    # schemes that are not HTTP at all
    "file:///C:/Windows/win.ini",
    "ftp://example.com/x",
    "javascript:alert(1)",
    "gopher://example.com/",
    # credentials in the URL (they end up in logs and redirects)
    "http://user:pass@example.com/",
    "http://user@example.com/",
    # odd numeric forms of 127.0.0.1: blocked when parsed, or by resolution
    "http://2130706433/",
    "http://0x7f000001/",
    # header injection through the URL itself
    "http://example.com/\r\nX-Injected: 1",
    "http://example.com/a b",
    "",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_refuses_unsafe_urls(url):
    with pytest.raises(UnsafeURL):
        safe_url(url)
    assert is_safe_url(url) is False


ALLOWED = [
    "https://example.com/path?q=1",
    "http://www.hetc.ac.in/contact",
    "https://www.google.com/search?q=autocad",
    "http://93.184.216.34/",
]


@pytest.mark.parametrize("url", ALLOWED)
def test_allows_public_urls_unchanged(url):
    # Returned verbatim: re-encoding a URL breaks signed query strings.
    assert safe_url(url, resolve=False) == url


def test_public_name_resolving_to_private_address_is_refused(monkeypatch):
    """DNS rebinding: the name looks public, the A record is not."""
    import agents.url_guard as guard

    monkeypatch.setattr(
        guard.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(UnsafeURL):
        safe_url("http://evil.example.com/")
    assert is_safe_url("http://evil.example.com/") is False


def test_public_name_resolving_publicly_is_allowed(monkeypatch):
    import agents.url_guard as guard

    monkeypatch.setattr(
        guard.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert safe_url("https://www.hetc.ac.in/") == "https://www.hetc.ac.in/"


def test_unresolvable_host_is_refused_not_fetched():
    with pytest.raises(UnsafeURL):
        safe_url("http://no-such-host.invalid/")


def test_redirect_cap_is_small_and_positive():
    assert 1 <= MAX_REDIRECTS <= 10


def test_check_final_url_rejects_a_redirect_into_loopback():
    """A redirect cap limits hops, not destinations — so the landing URL is
    re-checked with the same guard."""
    with pytest.raises(UnsafeURL):
        check_final_url("http://127.0.0.1:8765/api/status", resolve=False)
    assert check_final_url("https://example.com/", resolve=False) == "https://example.com/"


def test_guard_is_a_valueerror():
    """Call sites catch Exception; keeping it a ValueError means a bare
    ``except ValueError`` cannot silently swallow it."""
    assert issubclass(UnsafeURL, ValueError)
