"""Self-check for agents/outreach_apis.py.

Run:  python -X utf8 agents/test_outreach_apis.py   (repo root)
Exit 0 = all checks green. No network, no keys — urllib is stubbed and the
captured requests are asserted (URL, headers, payload shape).
"""
import importlib.util
import io
import json
import os
import sys
import types
import urllib.error
import urllib.request

# outreach_apis.py is stdlib-only: load it straight from the file.
spec = importlib.util.spec_from_file_location(
    "outreach_apis_under_test", os.path.join("agents", "outreach_apis.py"))
oa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oa)

CHECKS = []
CAPTURED = {}


class FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_urlopen(behavior):
    """behavior: dict with 'respond' payload or 'raise' exception."""
    def fake(req, timeout=None):
        CAPTURED["url"] = req.full_url
        CAPTURED["headers"] = dict(req.header_items())
        CAPTURED["data"] = (json.loads(req.data.decode("utf-8"))
                            if req.data else None)
        CAPTURED["method"] = req.get_method()
        if "raise" in behavior:
            raise behavior["raise"]
        return FakeResp(behavior["respond"])
    return fake


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def _with_env(env: dict, fn):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return fn()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _clear_keys():
    for k in ("RESEND_API_KEY", "BREVO_API_KEY", "TAVILY_API_KEY",
              "GEOAPIFY_API_KEY", "REACHER_URL", "OUTREACH_FROM_EMAIL"):
        os.environ.pop(k, None)


@check("resend: endpoint, bearer header, payload; ok + error paths")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"id": "re_123"}})
    try:
        r = _with_env({"RESEND_API_KEY": "k", "OUTREACH_FROM_EMAIL": "a@b.c"},
                      lambda: oa.resend_send("t@x.com", "Hi", "body"))
        assert r["status"] == "sent" and r["id"] == "re_123"
        assert r["via"] == "resend"
        assert CAPTURED["url"] == "https://api.resend.com/emails"
        hdrs = {k.lower(): v for k, v in CAPTURED["headers"].items()}
        assert hdrs["authorization"] == "Bearer k"
        assert CAPTURED["data"]["to"] == ["t@x.com"]
        assert CAPTURED["data"]["from"] == "a@b.c"
    finally:
        urllib.request.urlopen = orig
    assert oa.resend_send("t@x.com", "s", "b")["error"] == \
        "RESEND_API_KEY not set"
    r = _with_env({"RESEND_API_KEY": "k"},
                  lambda: oa.resend_send("t@x.com", "s", "b"))
    assert r["error"] == "OUTREACH_FROM_EMAIL not set"
    urllib.request.urlopen = _stub_urlopen(
        {"raise": urllib.error.HTTPError("u", 429, "x", {}, None)})
    try:
        r = _with_env({"RESEND_API_KEY": "k", "OUTREACH_FROM_EMAIL": "a@b.c"},
                      lambda: oa.resend_send("t@x.com", "s", "b"))
        assert "error" in r and "429" in r["error"]
    finally:
        urllib.request.urlopen = orig


@check("brevo: api-key header and payload shape")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"messageId": "m1"}})
    try:
        r = _with_env({"BREVO_API_KEY": "bk", "OUTREACH_FROM_EMAIL": "a@b.c"},
                      lambda: oa.brevo_send("t@x.com", "Hi", "body"))
        assert r["status"] == "sent" and r["via"] == "brevo"
        assert CAPTURED["url"] == "https://api.brevo.com/v3/smtp/email"
        hdrs = {k.lower(): v for k, v in CAPTURED["headers"].items()}
        assert hdrs["api-key"] == "bk"
        assert CAPTURED["data"]["to"] == [{"email": "t@x.com"}]
    finally:
        urllib.request.urlopen = orig
    assert "error" in oa.brevo_send("t@x.com", "s", "b")


@check("tavily_search: endpoint, bearer, results mapping")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"results": [
        {"title": "T", "url": "https://e.com", "content": "c" * 5000}]}})
    try:
        r = _with_env({"TAVILY_API_KEY": "tk"},
                      lambda: oa.tavily_search("coaching bandel", 5))
        assert len(r["results"]) == 1
        assert r["results"][0]["url"] == "https://e.com"
        assert len(r["results"][0]["content"]) == 2000  # truncated
        assert CAPTURED["url"] == "https://api.tavily.com/search"
        assert CAPTURED["data"]["query"] == "coaching bandel"
    finally:
        urllib.request.urlopen = orig
    assert oa.tavily_search("q")["error"] == "TAVILY_API_KEY not set"


@check("tavily_extract: urls payload")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"results": [
        {"url": "https://e.com", "raw_content": "hello"}]}})
    try:
        r = _with_env({"TAVILY_API_KEY": "tk"},
                      lambda: oa.tavily_extract(["https://e.com"], "q"))
        assert r["results"][0]["text"] == "hello"
        assert CAPTURED["url"] == "https://api.tavily.com/extract"
        assert CAPTURED["data"]["urls"] == ["https://e.com"]
    finally:
        urllib.request.urlopen = orig


@check("geoapify: geocode + places URLs and mapping")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"features": [
        {"properties": {"lat": 22.9, "lon": 88.4,
                        "formatted": "Bandel, IN"}}]}})
    try:
        r = _with_env({"GEOAPIFY_API_KEY": "gk"},
                      lambda: oa.geoapify_geocode("Bandel"))
        assert r["results"][0]["lat"] == 22.9
        assert "geocode/search" in CAPTURED["url"]
        assert "text=Bandel" in CAPTURED["url"]
        assert CAPTURED["method"] == "GET"
    finally:
        urllib.request.urlopen = orig
    urllib.request.urlopen = _stub_urlopen({"respond": {"features": [
        {"properties": {"name": "N1", "categories": ["education"],
                        "phone": "+91123", "website": "https://n1.in",
                        "lat": 22.9, "lon": 88.4,
                        "formatted": "Addr"}}]}})
    try:
        r = _with_env({"GEOAPIFY_API_KEY": "gk"},
                      lambda: oa.geoapify_places(22.9, 88.4, "education"))
        p = r["results"][0]
        assert (p["name"], p["phone"], p["website"]) == \
            ("N1", "+91123", "https://n1.in")
        assert p["source"] == "geoapify"
        assert "v2/places" in CAPTURED["url"]
        assert "circle%3A88.4%2C22.9%2C5000" in CAPTURED["url"] or \
            "circle:88.4,22.9,5000" in urllib.parse.unquote(CAPTURED["url"])
    finally:
        urllib.request.urlopen = orig
    assert "error" in oa.geoapify_places(0, 0, "education")


@check("reacher: posts to REACHER_URL, default localhost")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen(
        {"respond": {"is_reachable": "safe", "is_disposable": False,
                     "secret": "must-not-leak"}})
    try:
        r = _with_env({"REACHER_URL": "http://r:8080"},
                      lambda: oa.reacher_verify("a@b.com"))
        assert r["reachable"] == "safe"
        assert CAPTURED["url"] == "http://r:8080/v0/check_email"
        assert CAPTURED["data"] == {"to_email": "a@b.com"}
        assert "secret" not in r["detail"]  # allowlist only
    finally:
        urllib.request.urlopen = orig
    os.environ.pop("REACHER_URL", None)  # -> default localhost
    urllib.request.urlopen = _stub_urlopen({"respond": {"is_reachable": "x"}})
    try:
        oa.reacher_verify("a@b.com")
        assert CAPTURED["url"] == "http://localhost:8080/v0/check_email"
    finally:
        urllib.request.urlopen = orig


@check("research_search: tavily when keyed, ddgs otherwise")
def _():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub_urlopen({"respond": {"results": [
        {"title": "T", "url": "u", "content": "c"}]}})
    try:
        r = _with_env({"TAVILY_API_KEY": "tk"},
                      lambda: oa.research_search("q"))
        assert r["via"] == "tavily" and len(r["results"]) == 1
    finally:
        urllib.request.urlopen = orig
    # no key -> keyless ddgs path (stubbed module)
    fake_ddgs = types.ModuleType("ddgs")

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=5, region="in-en"):
            assert region == "in-en"
            return [{"title": "D", "href": "https://d.com", "body": "b"}]

    fake_ddgs.DDGS = FakeDDGS
    sys.modules["ddgs"] = fake_ddgs
    try:
        r = oa.research_search("q")
        assert r["via"] == "ddgs"
        assert r["results"][0]["url"] == "https://d.com"
    finally:
        del sys.modules["ddgs"]


@check("status: booleans only, never key material")
def _():
    def inner():
        st = oa.status()
        assert st["resend"] is True and st["brevo"] is False
        assert st["tavily"] is True and st["geoapify"] is False
        blob = json.dumps(st)
        assert "supersecret" not in blob  # never leak key material
    _with_env({"RESEND_API_KEY": "supersecret",
               "TAVILY_API_KEY": "tk"}, inner)


def main():
    failed = 0
    for name, fn in CHECKS:
        _clear_keys()
        CAPTURED.clear()
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    _clear_keys()
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
