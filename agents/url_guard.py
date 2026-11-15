"""One guard in front of every fetch of a scraped or model-supplied URL.

A business website, a search result and a model answer are all untrusted text,
and all three reach ``Fetcher.get`` in this codebase. Any of them can point the
fetcher at the loopback API (where the launch cookie is waiting), at a router
on the LAN, or at a cloud metadata endpoint. So every such fetch calls
:func:`safe_url` first and passes :data:`MAX_REDIRECTS` to the HTTP client.

Three checks, no cleverness:

  scheme    http/https only
  host      loopback, private, link-local, CGNAT, multicast and reserved
            ranges refused, plus the usual local-only names
  resolve   every address the host answers with must pass too, so a public
            name cannot resolve to 127.0.0.1 (DNS rebinding)

The redirect cap is enforced by the HTTP client (``max_redirects``); a cap
limits how many hops happen, not where they land, so callers that can see the
final URL re-check it with :func:`check_final_url`.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

#: Hops a scraped page may redirect us through. Small on purpose: a page that
#: needs more is either broken or walking us somewhere we did not choose.
MAX_REDIRECTS = 5

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ranges that must never be reachable from a fetch whose URL came from a
# website or a model. Listed explicitly rather than inferred from one property
# so the policy is readable and does not drift with Python's ipaddress rules.
_BLOCKED_V4 = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8",          # "this network"
    "10.0.0.0/8",         # RFC 1918
    "100.64.0.0/10",      # carrier-grade NAT
    "127.0.0.0/8",        # loopback
    "169.254.0.0/16",     # link-local + cloud metadata
    "172.16.0.0/12",      # RFC 1918
    "192.0.0.0/24",       # IETF protocol assignments
    "192.0.2.0/24",       # TEST-NET-1
    "192.168.0.0/16",     # RFC 1918
    "198.18.0.0/15",      # benchmarking
    "198.51.100.0/24",    # TEST-NET-2
    "203.0.113.0/24",     # TEST-NET-3
    "224.0.0.0/4",        # multicast
    "240.0.0.0/4",        # reserved
    "255.255.255.255/32",
))

_BLOCKED_V6 = tuple(ipaddress.ip_network(n) for n in (
    "::/128",             # unspecified
    "::1/128",            # loopback
    "fe80::/10",          # link-local
    "fc00::/7",           # unique local
    "ff00::/8",           # multicast
    "2001:db8::/32",      # documentation
))

_BLOCKED_HOSTS = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal",
})

_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


class UnsafeURL(ValueError):
    """The URL points somewhere a scraper must never go."""


def _blocked_ip(ip) -> bool:
    """True for any address a public fetch must not touch."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    nets = _BLOCKED_V4 if ip.version == 4 else _BLOCKED_V6
    if any(ip in net for net in nets):
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _blocked_hostname(host: str) -> bool:
    return host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES)


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnsafeURL(f"cannot resolve {host!r}: {exc}") from exc
    return [info[4][0] for info in infos]


def safe_url(url: str, *, resolve: bool = True) -> str:
    """Return *url* unchanged if it is safe to fetch, else raise UnsafeURL.

    ``resolve=False`` skips the DNS hop — for parsing checks and for callers
    that have already validated the host.
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURL("empty URL")
    if any(ch in raw for ch in "\r\n\t \x00"):
        # A newline here becomes header injection one layer down.
        raise UnsafeURL("whitespace or control characters in URL")

    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise UnsafeURL(f"unparseable URL: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"scheme {scheme or '(none)'!r} is not allowed")
    if parts.username or parts.password:
        raise UnsafeURL("credentials in URL")

    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise UnsafeURL("missing host")
    if _blocked_hostname(host):
        raise UnsafeURL(f"host {host!r} is local-only")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise UnsafeURL(f"address {host} is private or local")
        return raw

    if not resolve:
        return raw

    for addr in _resolve(host):
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            raise UnsafeURL(f"unparseable address {addr!r} for {host}") from None
        if _blocked_ip(ip):
            raise UnsafeURL(f"{host} resolves to private address {addr}")
    return raw


def is_safe_url(url: str, *, resolve: bool = True) -> bool:
    """Boolean form of :func:`safe_url` for callers that only branch."""
    try:
        safe_url(url, resolve=resolve)
        return True
    except UnsafeURL:
        return False


def check_final_url(url: str, *, resolve: bool = True) -> str:
    """Re-check where the HTTP client actually landed after redirects."""
    return safe_url(url, resolve=resolve)
