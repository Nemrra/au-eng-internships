"""Find the applicant-tracking system behind employers we don't have a working source for.

1. Fetch the careers / program page (robots-respecting), look for ATS links or embeds.
2. Follow up to two "jobs / vacancies / opportunities" links on that page and repeat.
3. Probe common ATS APIs with slug guesses from the company name; accept a probe only when
   the board name matches or it has Australian roles.
Results go to registry/discovered.json and are used by the collector on later runs.
"""
import json, re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import http
from .classify import classify_html, classify_url
from .filters import is_australian

FOLLOW = re.compile(r"\b(jobs?|vacanc|opportunit|positions|openings|join (us|our team)|current roles|careers|"
                    r"work with us|apply)\b", re.I)


def _name_slugs(name):
    n = re.sub(r"\(.*?\)", " ", name.lower())
    n = re.sub(r"\b(pty|ltd|limited|inc|australia|australian|group|technologies|technology|corporation|the)\b", " ", n)
    words = re.findall(r"[a-z0-9]+", n)
    if not words:
        return []
    cands = ["".join(words), "-".join(words), words[0]]
    if len(words) > 1:
        cands.append("".join(words[:2]))
    out = []
    for c in cands:
        if len(c) >= 3 and c not in out:
            out.append(c)
    return out[:4]


def _probe(name):
    found = []
    for s in _name_slugs(name):
        try:
            r = http.session().get(f"https://boards-api.greenhouse.io/v1/boards/{s}", timeout=12)
            if r.status_code == 200:
                bname = (r.json().get("name") or "").lower()
                if bname and any(w in bname for w in re.findall(r"[a-z]{4,}", name.lower())[:2]):
                    found.append({"type": "greenhouse", "token": s})
                    break
        except Exception:
            pass
    for s in _name_slugs(name):
        for typ, url, key in (
                ("lever", f"https://api.lever.co/v0/postings/{s}?mode=json", "company"),
                ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{s}", "org"),
                ("workable", f"https://apply.workable.com/api/v1/widget/accounts/{s}", "account"),
                ("smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{s}/postings?country=au&limit=20", "company")):
            if any(f["type"] == typ for f in found):
                continue
            try:
                r = http.session().get(url, timeout=12)
                if r.status_code != 200:
                    continue
                d = r.json()
                if typ == "lever":
                    locs = [((j.get("categories") or {}).get("location") or "") for j in d]
                elif typ == "ashby":
                    locs = [j.get("location") or "" for j in d.get("jobs", [])]
                elif typ == "workable":
                    if (d.get("name") or "").lower().split()[:1] != name.lower().split()[:1]:
                        continue
                    locs = [j.get("country") or "" for j in d.get("jobs", [])]
                else:
                    locs = [((j.get("location") or {}).get("country") or "") for j in d.get("content", [])]
                    if d.get("totalFound", 0) > 0:
                        locs.append("Australia")
                if any(is_australian(l) for l in locs):
                    found.append({"type": typ, key: s})
            except Exception:
                continue
    return found


def discover_one(emp):
    specs, tried = [], []
    pages = [u for u in (emp.get("careers_url"), emp.get("program_url")) if u and u.startswith("http")]
    for u in pages[:2]:
        try:
            r = http.get(u, check_robots=True, timeout=20)
        except Exception as e:
            tried.append(f"{u}: {type(e).__name__}")
            continue
        tried.append(u)
        specs += classify_html(r.text)
        if specs:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        follow = []
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True)
            href = urljoin(r.url, a["href"])
            if not href.startswith("http") or href in follow:
                continue
            spec = classify_url(href)
            if spec:
                specs.append(spec)
                continue
            if FOLLOW.search(t or "") and urlparse(href).netloc.split(".")[-2:] == urlparse(r.url).netloc.split(".")[-2:]:
                follow.append(href)
        if specs:
            break
        for f in follow[:2]:
            try:
                r2 = http.get(f, check_robots=True, timeout=20)
                specs += classify_html(r2.text)
                tried.append(f)
            except Exception:
                continue
            if specs:
                break
        if specs:
            break
    if not specs:
        specs = _probe(emp["name"])
        if specs:
            tried.append("slug-probe")
    # dedupe
    uniq, keys = [], set()
    for s in specs:
        k = json.dumps(s, sort_keys=True)
        if k not in keys:
            keys.add(k)
            uniq.append(s)
    return {"specs": uniq[:4], "checked": date.today().isoformat(), "tried": tried[:5]}
