"""Turn registry entries into adapter specs."""
import json, os, re
from urllib.parse import urlparse

from .classify import classify_url, rmk_host

URL_RE = re.compile(r"https?://[^\s\"'<>()\]]+")


def _urls(obj):
    out = []
    if isinstance(obj, str):
        out += URL_RE.findall(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _urls(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _urls(v)
    return [u.rstrip(".,;") for u in out]


def spec_key(spec):
    return json.dumps({k: v for k, v in spec.items() if not k.startswith("_")}, sort_keys=True)


def specs_for(emp, discovered=None, dead=None):
    """Return (structured_specs, page_specs)."""
    dead = dead or set()
    specs, keys = [], set()

    def add(spec):
        if not spec:
            return
        k = spec_key(spec)
        if k in keys or k in dead:
            return
        keys.add(k)
        specs.append(spec)

    for d in (discovered or {}).get("specs", []):
        add(d)
    for hint in emp.get("ats_hints", []):
        raw = hint.get("raw") or {}
        typ = hint.get("type", "")
        ident = raw.get("identifiers") or {}
        for u in _urls(raw):
            s = classify_url(u)
            if s:
                if s["type"] == "eightfold":
                    dom = ident.get("domain") or (re.search(r"domain=([a-z0-9.-]+)", u) or [None, None])[1]
                    if dom:
                        s["domain"] = dom
                add(s)
            elif "successfactors" in typ or "/services/rss/job" in u:
                h = rmk_host(u)
                if h and "successfactors" not in h:
                    add({"type": "sf_rmk", "host": h})
            elif u.endswith(".rss") or u.endswith("jobs.rss"):
                add({"type": "rss", "url": u})
        if "pageup" in typ:
            pid = ident.get("pageup_id")
            host = ident.get("custom_host") or ident.get("custom_domain")
            if pid:
                add({"type": "pageup", "base": f"https://careers.pageuppeople.com/{pid}/cw/en"})
            elif host:
                if "virginaustralia" in host:
                    add({"type": "pageup", "base": f"https://{host}/cw/en"})
                else:
                    add({"type": "pageup", "base": f"https://{host}/en"})
        if typ.startswith("successfactors") and ident.get("host") and "successfactors" not in ident["host"]:
            add({"type": "sf_rmk", "host": ident["host"]})
        if typ == "teamtailor" and ident.get("host"):
            add({"type": "teamtailor", "host": ident["host"]})
        if typ in ("hibob",) and ident.get("subdomain"):
            add({"type": "hibob", "sub": ident["subdomain"]})
        if typ == "bamboohr" and ident.get("subdomain"):
            add({"type": "bamboohr", "sub": ident["subdomain"]})
    # Pages to watch: program page always; careers page when no structured source; static pages
    pages = []
    seen_pages = set()

    def addp(u):
        if not u or not isinstance(u, str) or not u.startswith("http"):
            return
        u = u.split("#")[0]
        if u in seen_pages or classify_url(u):
            return
        host = urlparse(u).netloc
        if any(h in host for h in ("linkedin.com", "seek.com.au", "indeed.", "glassdoor.", "gradconnection.com",
                                   "prosple.com", "talent.com", "jora.com")):
            return
        seen_pages.add(u)
        pages.append({"type": "page", "url": u})

    addp(emp.get("program_url"))
    for hint in emp.get("ats_hints", []):
        if hint.get("type") in ("static_page", "custom", "email", "email/custom", "custom (cv form)") or \
                not specs:
            ep = (hint.get("raw") or {}).get("endpoint")
            if isinstance(ep, dict):
                ep = ep.get("url")
            if isinstance(ep, str):
                addp(ep.split(" ")[0])
    if not specs:
        addp(emp.get("careers_url"))
    return specs, pages[:3]
