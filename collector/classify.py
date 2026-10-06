"""Recognise applicant-tracking systems from URLs and page HTML.

classify_url(url) -> adapter spec dict or None, e.g.
  {"type": "greenhouse", "token": "andurilindustries"}
  {"type": "workday", "host": "cochlear.wd3.myworkdayjobs.com", "tenant": "cochlear", "site": "Cochlear_Careers"}
"""
import re
from urllib.parse import urlparse, parse_qs, unquote

IGNORE_SLUGS = {"embed", "jobs", "job", "v1", "boards", "api", "js", "css", "static", "assets", "careers",
                "en", "en-us", "en-au", "search", "widget", "job_board", "job-board", "apply", "www"}

PATTERNS = [
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)")),
    ("lever_eu", re.compile(r"(?:jobs|api)\.eu\.lever\.co/(?:v0/postings/)?([A-Za-z0-9_.-]+)")),
    ("lever", re.compile(r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.%-]+)")),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com")),
    ("teamtailor", re.compile(r"([a-z0-9-]+)\.teamtailor\.com")),
    ("breezy", re.compile(r"([a-z0-9-]+)\.breezy\.hr")),
    ("bamboohr", re.compile(r"([a-z0-9-]+)\.bamboohr\.com")),
    ("personio", re.compile(r"([a-z0-9-]+)\.jobs\.personio\.(?:com|de)")),
    ("rippling", re.compile(r"ats\.rippling\.com/(?:api/v2/board/)?([A-Za-z0-9_-]+)")),
    ("hibob", re.compile(r"([a-z0-9-]+)\.careers\.hibob\.com")),
    ("livehire", re.compile(r"livehire\.com/(?:careers|widgets/job-listings)/([A-Za-z0-9_-]+)")),
    ("pageup", re.compile(r"careers\.pageuppeople\.com/(\d+)/")),
    ("employmenthero", re.compile(r"employmenthero\.com/jobs/organisations/([a-z0-9-]+)")),
    ("eightfold", re.compile(r"([a-z0-9-]+)\.eightfold\.ai")),
    ("icims", re.compile(r"(careers-[a-z0-9-]+\.icims\.com)")),
]
WORKDAY_RE = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/([A-Za-z0-9_-]+)/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")
ORACLE_RE = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*\.fa(?:\.[a-z0-9]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}(?:-[A-Z]{2})?/sites/([A-Za-z0-9_]+)")
ORACLE_API_RE = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*\.fa(?:\.[a-z0-9]+)?\.oraclecloud\.com)/hcmRestApi/.*?siteNumber=([A-Za-z0-9_]+)")
SF_CLASSIC_RE = re.compile(r"(career\d*\.successfactors\.(?:com|eu))/career\?(?:[^\"'\s]*?)company=([A-Za-z0-9_]+)")
SF_RMK_HINT = re.compile(r"/services/rss/job/|/search/\?q=|jobs?\.[a-z0-9-]+\.[a-z.]+/job/[^/]+/\d{6,}")


def classify_url(url):
    if not url or not isinstance(url, str):
        return None
    u = unquote(url)
    m = WORKDAY_RE.search(u)
    if m:
        tenant, wd, cxs_tenant, site = m.groups()
        if site.lower() in ("wday", "job", "jobs", "details"):
            return None
        return {"type": "workday", "host": f"{tenant}.{wd}.myworkdayjobs.com",
                "tenant": cxs_tenant or tenant, "site": site}
    m = ORACLE_API_RE.search(u) or ORACLE_RE.search(u)
    if m:
        return {"type": "oracle", "host": m.group(1), "site": m.group(2)}
    m = SF_CLASSIC_RE.search(u)
    if m:
        return {"type": "sf_classic", "host": m.group(1), "company": m.group(2)}
    for typ, rx in PATTERNS:
        m = rx.search(u)
        if m:
            val = m.group(1)
            if val.lower() in IGNORE_SLUGS:
                continue
            if typ == "pageup":
                return {"type": "pageup", "base": f"https://careers.pageuppeople.com/{val}/cw/en"}
            if typ == "icims":
                return {"type": "icims", "host": val}
            if typ == "eightfold":
                return {"type": "eightfold", "sub": val}
            key = {"greenhouse": "token", "lever": "company", "lever_eu": "company", "ashby": "org",
                   "smartrecruiters": "company", "workable": "account", "rippling": "board",
                   "livehire": "company", "employmenthero": "org"}.get(typ, "sub")
            spec = {"type": "lever" if typ == "lever_eu" else typ, key: val}
            if typ == "lever_eu":
                spec["eu"] = True
            return spec
    return None


def classify_html(html):
    """Find ATS references inside a careers page. Returns list of unique specs."""
    found, seen = [], set()
    for m in re.finditer(r"https?:(?:\\?/){2}[^\s\"'<>]+|(?:boards|job-boards)\.greenhouse\.io[^\s\"'<>]*", html):
        s = m.group(0).replace("\\/", "/")
        if not s.startswith("http"):
            s = "https://" + s
        spec = classify_url(s)
        if spec:
            k = tuple(sorted(spec.items()))
            if k not in seen:
                seen.add(k)
                found.append(spec)
    # Greenhouse embed script: Grnhse.Settings / data-for
    for m in re.finditer(r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)", html):
        spec = {"type": "greenhouse", "token": m.group(1)}
        k = tuple(sorted(spec.items()))
        if k not in seen:
            seen.add(k)
            found.append(spec)
    return found


def rmk_host(url):
    """SuccessFactors Recruiting Marketing (RMK) career sites: jobs.csiro.au/search/?q=..."""
    if not url:
        return None
    p = urlparse(url)
    if SF_RMK_HINT.search(url) and p.netloc:
        return p.netloc
    return None
