"""Source adapters. Each returns a list of raw listing dicts:
  {native_id, title, company, location, url, posted, closes, salary, description, employment_type}
Only `title` and `url` are required; everything else may be None.
"""
import html as htmlmod, json, re, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlencode, quote

from bs4 import BeautifulSoup

from . import http
from .filters import STUDENT_RE, GRAD_RE

SEARCH_TERMS = ["intern", "graduate", "student", "vacation", "cadet", "summer"]


def _iso(ts):
    if ts in (None, ""):
        return None
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        s = str(ts)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            return m.group(1)
        for fmt in ("%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%a, %d %b %Y %H:%M:%S %Z",
                    "%a, %d %b %Y %H:%M:%S %z", "%a %d %b %Y"):
            try:
                return datetime.strptime(s.strip(), fmt).date().isoformat()
            except ValueError:
                pass
    except Exception:
        pass
    return None


def relative_date(text, now=None):
    """'Posted 3 Days Ago' / 'Posted Today' / '30+ days ago' -> ISO date (approx)."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    t = text.lower()
    if "today" in t or "just posted" in t or "hours ago" in t:
        return now.date().isoformat()
    if "yesterday" in t:
        return (now - timedelta(days=1)).date().isoformat()
    m = re.search(r"(\d+)\+?\s*(day|week|month)s?\s*ago", t)
    if m:
        n = int(m.group(1))
        mult = {"day": 1, "week": 7, "month": 30}[m.group(2)]
        return (now - timedelta(days=n * mult)).date().isoformat()
    return _iso(text)


def closing_from_text(text, now=None):
    """'Closing in 10 days' / 'Closes 24 Oct 2026' -> ISO date."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    t = text.lower()
    m = re.search(r"clos\w*\s+in\s+(\d+)\s+(day|week|month)s?", t)
    if m:
        n = int(m.group(1))
        return (now + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[m.group(2)])).date().isoformat()
    if re.search(r"clos\w*\s+in\s+a\s+month", t):
        return (now + timedelta(days=30)).date().isoformat()
    if re.search(r"clos\w*\s+(today|tonight)", t):
        return now.date().isoformat()
    if re.search(r"clos\w*\s+tomorrow", t):
        return (now + timedelta(days=1)).date().isoformat()
    m = re.search(r"clos\w*[:\s]+(?:on\s+)?(?:\w+day,?\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|"
                  r"\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})", text, re.I)
    if m:
        return _iso(re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(1)).replace(",", ", ").replace(",  ", ", "))
    return None


def strip_html(s, limit=6000):
    if not s:
        return ""
    s = htmlmod.unescape(s) if "&lt;" in s else s
    txt = BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt)[:limit]


def _student_title(t):
    return bool(STUDENT_RE.search(t or "") or GRAD_RE.search(t or ""))


# ---------------------------------------------------------------- ATS adapters

def greenhouse(spec, emp):
    tok = spec["token"]
    r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs", params={"content": "true"})
    out = []
    for j in r.json().get("jobs", []):
        locs = [j.get("location", {}).get("name") or ""] + [o.get("name", "") for o in j.get("offices", []) or []]
        out.append(dict(native_id=j.get("id"), title=j.get("title"), location=" | ".join(l for l in locs if l),
                        url=j.get("absolute_url"), posted=_iso(j.get("first_published") or j.get("updated_at")),
                        description=strip_html(j.get("content"))))
    return out


def lever(spec, emp):
    host = "api.eu.lever.co" if spec.get("eu") else "api.lever.co"
    r = http.get(f"https://{host}/v0/postings/{spec['company']}", params={"mode": "json"})
    out = []
    for j in r.json():
        c = j.get("categories") or {}
        locs = c.get("allLocations") or [c.get("location")]
        sal = j.get("salaryRange")
        out.append(dict(native_id=j.get("id"), title=j.get("text"), location=" | ".join(l for l in locs if l),
                        url=j.get("hostedUrl"), posted=_iso(j.get("createdAt")),
                        employment_type=c.get("commitment"),
                        salary=(f"{sal.get('currency','')} {sal.get('min')}-{sal.get('max')} {sal.get('interval','')}"
                                if sal else None),
                        description=(j.get("descriptionPlain") or "")[:6000]))
    return out


def ashby(spec, emp):
    r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{spec['org']}", params={"includeCompensation": "true"})
    out = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        try:
            country = j["address"]["postalAddress"].get("addressCountry")
            if country:
                locs.append(country)
        except Exception:
            pass
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        out.append(dict(native_id=j.get("id"), title=j.get("title"), location=" | ".join(l for l in locs if l),
                        url=j.get("jobUrl"), posted=_iso(j.get("publishedAt")), salary=comp,
                        employment_type=j.get("employmentType"), description=(j.get("descriptionPlain") or "")[:6000]))
    return out


def smartrecruiters(spec, emp):
    cid = spec["company"]
    out, offset = [], 0
    while offset < 1000:
        r = http.get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings",
                     params={"country": "au", "limit": 100, "offset": offset})
        d = r.json()
        for j in d.get("content", []):
            loc = j.get("location") or {}
            title = j.get("name")
            desc = ""
            if _student_title(title):
                try:
                    dd = http.get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{j['id']}").json()
                    secs = (dd.get("jobAd") or {}).get("sections") or {}
                    desc = strip_html(" ".join((secs.get(k) or {}).get("text", "") for k in
                                               ("companyDescription", "jobDescription", "qualifications", "additionalInformation")))
                except Exception:
                    pass
            out.append(dict(native_id=j.get("id"), title=title,
                            location=", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x),
                            url=f"https://jobs.smartrecruiters.com/{cid}/{j.get('id')}",
                            posted=_iso(j.get("releasedDate")),
                            employment_type=(j.get("typeOfEmployment") or {}).get("label"), description=desc))
        total = d.get("totalFound", 0)
        offset += 100
        if offset >= total:
            break
    return out


AU_HINT = re.compile(r"australia|sydney|melbourne|brisbane|perth|adelaide|canberra|hobart|darwin|gold coast|newcastle|"
                     r"geelong|wollongong|toowoomba|townsville|\b(nsw|vic|qld|act|tas)\b|locations", re.I)


def workday(spec, emp):
    host, tenant, site = spec["host"], spec["tenant"], spec["site"]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    seen, out, details = set(), [], 0
    for q in SEARCH_TERMS:
        try:
            r = http.post(base + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q})
        except http.Blocked:
            raise
        except Exception:
            continue
        for j in r.json().get("jobPostings", []) or []:
            path = j.get("externalPath")
            if not path or path in seen:
                continue
            seen.add(path)
            title = j.get("title") or ""
            loc = j.get("locationsText") or ""
            rec = dict(native_id=path, title=title, location=loc,
                       url=f"https://{host}/en-US/{site}{path}", posted=relative_date(j.get("postedOn")))
            if _student_title(title) and AU_HINT.search(loc + " " + title) and details < 25:
                details += 1
                try:
                    info = http.get(base + path).json().get("jobPostingInfo", {})
                    locs = [info.get("location") or ""] + (info.get("additionalLocations") or [])
                    if info.get("country"):
                        locs.append(info["country"].get("descriptor", ""))
                    rec.update(location=" | ".join(l for l in locs if l) or loc,
                               url=info.get("externalUrl") or rec["url"],
                               employment_type=info.get("timeType"),
                               description=strip_html(info.get("jobDescription")),
                               start_date=_iso(info.get("startDate")))
                except Exception:
                    pass
            out.append(rec)
    return out


def workable(spec, emp):
    r = http.get(f"https://apply.workable.com/api/v1/widget/accounts/{spec['account']}", params={"details": "true"})
    out = []
    for j in r.json().get("jobs", []):
        locs = [", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x)
                for l in j.get("locations") or []] or [", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)]
        out.append(dict(native_id=j.get("shortcode"), title=j.get("title"), location=" | ".join(locs),
                        url=j.get("url") or j.get("shortlink"), posted=_iso(j.get("published_on") or j.get("created_at")),
                        employment_type=j.get("employment_type"), description=strip_html(j.get("description"))))
    return out


def recruitee(spec, emp):
    r = http.get(f"https://{spec['sub']}.recruitee.com/api/offers/")
    return [dict(native_id=j.get("id"), title=j.get("title"),
                 location=", ".join(x for x in [j.get("city"), j.get("state_name"), j.get("country")] if x) or j.get("location"),
                 url=j.get("careers_url"), posted=_iso(j.get("published_at")),
                 employment_type=j.get("employment_type_code"), description=strip_html(j.get("description")))
            for j in r.json().get("offers", [])]


def _rss(url):
    r = http.get(url)
    soup = BeautifulSoup(r.content, "xml")
    out = []
    for it in soup.find_all("item"):
        title = (it.title.text if it.title else "").strip()
        link = (it.link.text if it.link else "").strip()
        loc = ""
        for tag in ("location", "tt:location", "city", "region"):
            el = it.find(tag)
            if el:
                loc += " " + el.get_text(" ", strip=True)
        desc = it.description.text if it.description else ""
        out.append(dict(native_id=link, title=title, location=loc.strip(), url=link,
                        posted=_iso(it.pubDate.text) if it.pubDate else None, description=strip_html(desc)))
    return out


def teamtailor(spec, emp):
    host = spec.get("host") or f"{spec['sub']}.teamtailor.com"
    return _rss(f"https://{host}/jobs.rss")


def breezy(spec, emp):
    r = http.get(f"https://{spec['sub']}.breezy.hr/json")
    out = []
    for j in r.json():
        loc = j.get("location") or {}
        out.append(dict(native_id=j.get("id"), title=j.get("name"),
                        location=", ".join(x for x in [loc.get("city"), (loc.get("state") or {}).get("name") if isinstance(loc.get("state"), dict) else loc.get("state"),
                                                         (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else loc.get("country"),
                                                         loc.get("name")] if x),
                        url=j.get("url"), posted=_iso(j.get("published_date")),
                        employment_type=(j.get("type") or {}).get("name") if isinstance(j.get("type"), dict) else j.get("type")))
    return out


def bamboohr(spec, emp):
    sub = spec["sub"]
    r = http.get(f"https://{sub}.bamboohr.com/careers/list", headers={"Accept": "application/json"})
    out = []
    for j in r.json().get("result", []):
        loc = j.get("atsLocation") or j.get("location") or {}
        title = j.get("jobOpeningName")
        desc = ""
        if _student_title(title):
            try:
                dd = http.get(f"https://{sub}.bamboohr.com/careers/{j['id']}/detail", headers={"Accept": "application/json"}).json()
                desc = strip_html(((dd.get("result") or {}).get("jobOpening") or {}).get("description"))
            except Exception:
                pass
        out.append(dict(native_id=j.get("id"), title=title,
                        location=", ".join(x for x in [loc.get("city"), loc.get("state"), loc.get("country")] if x),
                        url=f"https://{sub}.bamboohr.com/careers/{j.get('id')}",
                        employment_type=j.get("employmentStatusLabel"), description=desc))
    return out


def personio(spec, emp):
    r = http.get(f"https://{spec['sub']}.jobs.personio.com/xml")
    soup = BeautifulSoup(r.content, "xml")
    out = []
    for p in soup.find_all("position"):
        pid = p.find("id").text if p.find("id") else None
        out.append(dict(native_id=pid, title=p.find("name").text if p.find("name") else "",
                        location=p.find("office").text if p.find("office") else "",
                        url=f"https://{spec['sub']}.jobs.personio.com/job/{pid}",
                        posted=_iso(p.find("createdAt").text) if p.find("createdAt") else None,
                        employment_type=p.find("schedule").text if p.find("schedule") else None,
                        description=strip_html(" ".join(v.text for v in p.find_all("value")))))
    return out


def rippling(spec, emp):
    out, page = [], 0
    while page < 10:
        d = http.get(f"https://ats.rippling.com/api/v2/board/{spec['board']}/jobs", params={"page": page}).json()
        items = d.get("items") or d.get("results") or d.get("jobs") or (d if isinstance(d, list) else [])
        for j in items:
            locs = j.get("locations") or j.get("workLocations") or []
            loc = " | ".join((l.get("name") or l.get("city") or "") + (" " + (l.get("country") or "") if isinstance(l, dict) else "")
                             if isinstance(l, dict) else str(l) for l in locs)
            out.append(dict(native_id=j.get("id") or j.get("uuid"), title=j.get("name") or j.get("title"), location=loc,
                            url=j.get("url") or f"https://ats.rippling.com/{spec['board']}/jobs/{j.get('id')}"))
        total_pages = d.get("totalPages") or d.get("total_pages") if isinstance(d, dict) else None
        page += 1
        if not items or (total_pages is not None and page >= total_pages):
            break
    return out


def oracle(spec, emp):
    host, site = spec["host"], spec["site"]
    out, seen = [], set()
    for q in ("intern", "graduate", "student", "vacation", "cadet"):
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
               f"&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},"
               f"keyword=%22{q}%22,limit=50,sortBy=POSTING_DATES_DESC")
        try:
            d = http.get(url).json()
        except http.Blocked:
            raise
        except Exception:
            continue
        for item in d.get("items", []):
            for j in item.get("requisitionList", []) or []:
                if j.get("Id") in seen:
                    continue
                seen.add(j.get("Id"))
                locs = [j.get("PrimaryLocation") or "", j.get("PrimaryLocationCountry") or ""] + \
                       [s.get("Name", "") for s in j.get("secondaryLocations") or []]
                out.append(dict(native_id=j.get("Id"), title=j.get("Title"), location=" | ".join(l for l in locs if l),
                                url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j.get('Id')}",
                                posted=_iso(j.get("PostedDate")), description=strip_html(j.get("ShortDescriptionStr"))))
    return out


def eightfold(spec, emp):
    sub = spec["sub"]
    host = spec.get("host") or f"{sub}.eightfold.ai"
    domain = spec.get("domain") or f"{sub}.com"
    out, seen = [], set()
    for q in ("intern", "graduate", "student"):
        try:
            d = http.get(f"https://{host}/api/apply/v2/jobs",
                         params={"domain": domain, "location": "Australia", "query": q, "num": 50}).json()
        except http.Blocked:
            raise
        except Exception:
            continue
        for j in d.get("positions", []):
            if j.get("id") in seen:
                continue
            seen.add(j.get("id"))
            out.append(dict(native_id=j.get("id"), title=j.get("name"),
                            location=" | ".join(j.get("locations") or [j.get("location") or ""]),
                            url=j.get("canonicalPositionUrl") or f"https://{host}/careers?pid={j.get('id')}",
                            posted=_iso(j.get("t_create")), description=strip_html(j.get("job_description"))))
    return out


def sf_rmk(spec, emp):
    host = spec["host"]
    out, seen = [], set()
    for q in SEARCH_TERMS:
        try:
            r = http.get(f"https://{host}/search/", params={"q": q, "sortColumn": "referencedate", "sortDirection": "desc"})
        except http.Blocked:
            raise
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("tr.data-row") or soup.select("li.job-tile") or []
        for row in rows:
            a = row.select_one("a.jobTitle-link") or row.find("a", href=re.compile(r"/job/"))
            if not a:
                continue
            href = urljoin(f"https://{host}/", a.get("href"))
            if href in seen:
                continue
            seen.add(href)
            loc = row.select_one(".jobLocation")
            dt = row.select_one(".jobDate")
            out.append(dict(native_id=href, title=a.get_text(" ", strip=True), location=loc.get_text(" ", strip=True) if loc else "",
                            url=href, posted=_iso(dt.get_text(strip=True)) if dt else None))
        if not rows:  # fall back to any /job/ links
            for a in soup.find_all("a", href=re.compile(r"/job/")):
                href = urljoin(f"https://{host}/", a.get("href"))
                t = a.get_text(" ", strip=True)
                if href in seen or len(t) < 6:
                    continue
                seen.add(href)
                out.append(dict(native_id=href, title=t, location="", url=href))
    return out


def pageup(spec, emp):
    base = spec["base"].rstrip("/")
    out, seen = [], set()
    urls = [f"{base}/listing/?page=1&page-items=100"] + [f"{base}/filter/?search-keyword={q}&page-items=100" for q in
                                                       ("intern", "graduate", "student", "vacation", "cadet", "summer")]
    for u in urls:
        try:
            r = http.get(u)
        except http.Blocked:
            raise
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/job/\d+")):
            href = urljoin(u, a.get("href"))
            title = a.get_text(" ", strip=True)
            if href in seen or not title:
                continue
            seen.add(href)
            row = a.find_parent("tr") or a.find_parent("li") or a.find_parent("div")
            loc = close = None
            if row:
                le = row.select_one(".location")
                loc = le.get_text(" ", strip=True) if le else None
                ce = row.select_one(".close-date time, time.close-date, .close-date")
                if ce:
                    close = _iso(ce.get("datetime") or ce.get_text(" ", strip=True))
            out.append(dict(native_id=href, title=title, location=loc or "", url=href, closes=close))
    return out


def livehire(spec, emp):
    co = spec["company"]
    out = []
    for u in (f"https://www.livehire.com/widgets/job-listings/{co}?multiSegment=true", f"https://www.livehire.com/careers/{co}/jobs"):
        try:
            r = http.get(u)
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/job/|/jobs/")):
            t = a.get_text(" ", strip=True)
            if len(t) < 5:
                continue
            href = urljoin(u, a.get("href"))
            out.append(dict(native_id=href, title=t, location="", url=href))
        if out:
            break
    return out


def employmenthero(spec, emp):
    u = f"https://employmenthero.com/jobs/organisations/{spec['org']}/"
    soup = BeautifulSoup(http.get(u).text, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"/jobs/position/")):
        t = a.get_text(" ", strip=True)
        if t:
            out.append(dict(native_id=a["href"], title=t, location="", url=urljoin(u, a["href"])))
    return out


def icims(spec, emp):
    u = f"https://{spec['host']}/jobs/search?ss=1&searchKeyword=&in_iframe=1"
    soup = BeautifulSoup(http.get(u).text, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"/jobs/\d+/")):
        t = a.get_text(" ", strip=True)
        if len(t) > 4:
            href = urljoin(u, a["href"]).split("?")[0]
            out.append(dict(native_id=href, title=t, location="", url=href))
    return out


def hibob(spec, emp):
    u = f"https://{spec['sub']}.careers.hibob.com/api/job-ad"
    d = http.get(u, headers={"Accept": "application/json"}).json()
    items = d if isinstance(d, list) else d.get("jobAdDetails") or d.get("jobAds") or d.get("items") or []
    out = []
    for j in items:
        out.append(dict(native_id=j.get("id"), title=j.get("title") or j.get("name"),
                        location=j.get("site") or j.get("location") or j.get("country") or "",
                        url=f"https://{spec['sub']}.careers.hibob.com/jobs/{j.get('id')}",
                        description=strip_html(j.get("description"))))
    return out


LINK_WORDS = re.compile(r"intern|vacation|summer|winter|student|cadet|graduate|placement|undergrad|early career|"
                        r"scholarship|studentship|co-?op|work experience|future talent", re.I)


def page(spec, emp):
    """Generic careers/program page: anchors whose text mentions student programs."""
    u = spec["url"]
    r = http.get(u, check_robots=True)
    soup = BeautifulSoup(r.text, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if not t or len(t) < 6 or len(t) > 160 or not LINK_WORDS.search(t):
            continue
        href = urljoin(u, a["href"])
        if href.startswith("mailto:") or href in seen or href.rstrip("/") == u.rstrip("/"):
            continue
        if re.search(r"\b(privacy|cookie|login|sign in|register|news|blog|story|stories|faq|meet our|life at|"
                     r"read more|learn more about|alumni)\b", t, re.I):
            continue
        seen.add(href)
        out.append(dict(native_id=href, title=t, location="", url=href, from_page=u, page_link=True))
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    spec["_page_text"] = text[:20000]
    return out


# ---------------------------------------------------------------- aggregators

def prosple(spec, emp):
    out, seen = [], set()
    kws = ["engineering", "electrical", "electronics", "software", "data science", "mechatronics", "research",
           "robotics", "physics"]
    for ot in ("2", "1"):  # internships, graduate jobs
        for kw in kws:
            for start in (0, 20, 40):
                url = ("https://au.prosple.com/search-jobs?defaults_applied=1&location=Australia&locations=9692"
                       f"&opportunity_types={ot}&keywords={quote(kw)}&start={start}")
                try:
                    r = http.get(url, check_robots=True)
                except http.Blocked:
                    raise
                except Exception:
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"/graduate-employers/[^/]+/jobs-internships/[^/?#]+"))
                new = 0
                for a in links:
                    href = urljoin("https://au.prosple.com", a["href"].split("?")[0])
                    t = a.get_text(" ", strip=True)
                    if not t or href in seen:
                        continue
                    seen.add(href)
                    new += 1
                    card = a.find_parent(["li", "article"]) or a.parent.parent
                    ctext = card.get_text(" | ", strip=True) if card else ""
                    m = re.search(r"/graduate-employers/([^/]+)/", href)
                    company = m.group(1).replace("-", " ").title() if m else None
                    out.append(dict(native_id=href, title=t, company=company, location=ctext[:300], url=href,
                                    closes=closing_from_text(ctext), card_text=ctext[:600],
                                    prosple_type="internship" if ot == "2" else "graduate"))
                if new == 0 or len(links) < 15:
                    break
    return out


def prosple_detail(url):
    """JSON-LD JobPosting from a Prosple/GradConnection detail page."""
    r = http.get(url, check_robots=True)
    soup = BeautifulSoup(r.text, "html.parser")
    info = {}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "")
        except Exception:
            continue
        for obj in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
                info["title"] = obj.get("title")
                org = obj.get("hiringOrganization")
                info["company"] = org.get("name") if isinstance(org, dict) else org
                info["posted"] = _iso(obj.get("datePosted"))
                info["closes"] = _iso(obj.get("validThrough"))
                locs = obj.get("jobLocation") or []
                if isinstance(locs, dict):
                    locs = [locs]
                parts = []
                for l in locs:
                    addr = (l or {}).get("address") or {}
                    if isinstance(addr, dict):
                        parts.append(", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"),
                                                           addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None] if x))
                info["location"] = " | ".join(p for p in parts if p)
                sal = obj.get("baseSalary")
                if isinstance(sal, dict):
                    v = sal.get("value") or {}
                    if isinstance(v, dict):
                        info["salary"] = f"{sal.get('currency','AUD')} {v.get('minValue') or v.get('value') or ''}" \
                                         f"{'-' + str(v.get('maxValue')) if v.get('maxValue') else ''} {v.get('unitText','')}".strip()
                info["employment_type"] = obj.get("employmentType") if isinstance(obj.get("employmentType"), str) else \
                    ", ".join(obj.get("employmentType") or [])
                info["description"] = strip_html(obj.get("description"))
    if not info.get("description"):
        main = soup.find("main") or soup
        info["description"] = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:6000]
    if not info.get("closes"):
        info["closes"] = closing_from_text(soup.get_text(" ", strip=True)[:20000])
    return info


GC_DISCIPLINES = ["engineering", "engineering-electrical", "engineering-software", "engineering-mechatronics",
                  "engineering-mechanical", "engineering-aerospace", "engineering-electronics", "computer-science",
                  "data-science-and-analytics", "information-technology", "mathematics", "physics", "science"]


def gradconnection(spec, emp):
    out, seen = [], set()
    for kind in ("internships", "graduate-jobs"):
        for disc in GC_DISCIPLINES:
            for pg in range(1, 6):
                url = f"https://au.gradconnection.com/{kind}/{disc}/" + (f"?page={pg}" if pg > 1 else "")
                try:
                    r = http.get(url, check_robots=True)
                except http.Blocked:
                    raise
                except Exception:
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"^/employers/[^/]+/(jobs|notifyme)/[^/]+/?"))
                new = 0
                for a in links:
                    href = urljoin("https://au.gradconnection.com", a["href"].split("?")[0])
                    t = a.get_text(" ", strip=True)
                    if not t or len(t) < 4 or href in seen:
                        continue
                    seen.add(href)
                    new += 1
                    card = a.find_parent(["li", "article"]) or a.parent.parent.parent
                    ctext = card.get_text(" | ", strip=True) if card else ""
                    m = re.search(r"/employers/([^/]+)/", href)
                    out.append(dict(native_id=href, title=t, company=m.group(1).replace("-", " ").title() if m else None,
                                    location=ctext[:300], url=href, closes=closing_from_text(ctext),
                                    card_text=ctext[:600], notify_only="/notifyme/" in href,
                                    gc_kind=kind))
                if new == 0:
                    break
    return out


def getro_board(spec, emp):
    base = spec["base"].rstrip("/")
    out, seen = [], set()
    for q in ("intern", "graduate", "student", "summer"):
        url = f"{base}/jobs?q={q}"
        try:
            r = http.get(url, check_robots=True)
        except http.Blocked:
            raise
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        nd = soup.find("script", id="__NEXT_DATA__")
        jobs = []
        if nd:
            try:
                data = json.loads(nd.string)
                stack = [data]
                while stack:
                    x = stack.pop()
                    if isinstance(x, dict):
                        if "title" in x and ("organization" in x or "url" in x) and ("locations" in x or "slug" in x):
                            jobs.append(x)
                        stack.extend(x.values())
                    elif isinstance(x, list):
                        stack.extend(x)
            except Exception:
                pass
        for j in jobs:
            org = j.get("organization") or {}
            href = j.get("url") or f"{base}/companies/{org.get('slug','')}/jobs/{j.get('slug','')}"
            if href in seen:
                continue
            seen.add(href)
            locs = j.get("locations") or []
            out.append(dict(native_id=href, title=j.get("title"), company=org.get("name"),
                            location=" | ".join(l if isinstance(l, str) else (l.get("name") or "") for l in locs),
                            url=href, posted=_iso(j.get("createdAt") or j.get("created_at"))))
        if not jobs:
            for a in soup.find_all("a", href=re.compile(r"/companies/[^/]+/jobs/")):
                href = urljoin(base, a["href"])
                t = a.get_text(" ", strip=True)
                if not t or href in seen:
                    continue
                seen.add(href)
                card = a.find_parent(["li", "article", "div"])
                m = re.search(r"/companies/([^/]+)/", href)
                out.append(dict(native_id=href, title=t, company=m.group(1).replace("-", " ").title() if m else None,
                                location=card.get_text(" | ", strip=True)[:300] if card else "", url=href))
    return out


def talent(spec, emp):
    out, seen = [], set()
    for kw in ("engineering intern", "graduate engineer", "summer vacation engineering", "electrical engineering student",
               "cadet engineer", "undergraduate engineer", "research intern"):
        for p in (1, 2):
            url = f"https://au.talent.com/jobs?k={quote(kw)}&l=Australia&p={p}"
            try:
                r = http.get(url, check_robots=True)
            except http.Blocked:
                raise
            except Exception:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"/view\?id=")):
                href = urljoin("https://au.talent.com", a["href"].split("&")[0])
                t = a.get_text(" ", strip=True)
                if not t or href in seen:
                    continue
                seen.add(href)
                card = a.find_parent(["section", "article", "li"]) or a.parent.parent
                ctext = card.get_text(" | ", strip=True) if card else ""
                parts = [x for x in ctext.split(" | ") if x and x != t]
                out.append(dict(native_id=href, title=t, company=parts[0] if parts else None,
                                location=" ".join(parts[1:3]), url=href, posted=relative_date(ctext), card_text=ctext[:500]))
    return out


AU_STRICT = re.compile(r"\bAustralia\b|,\s*(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b|\b(Sydney|Melbourne|Brisbane|Perth|Adelaide|Canberra|Hobart),\s*(Australia|AU|NSW|VIC|QLD|WA|SA|ACT|TAS)", re.I)


def simplify(spec, emp):
    r = http.get(spec["url"], timeout=60)
    out = []
    for j in r.json():
        locs = j.get("locations") or []
        loc = " | ".join(locs)
        if not AU_STRICT.search(loc) or not j.get("active", True) or j.get("is_visible") is False:
            continue
        out.append(dict(native_id=j.get("id"), title=j.get("title"), company=j.get("company_name"), location=loc,
                        url=j.get("url"), posted=_iso(j.get("date_posted"))))
    return out


def amazon(spec, emp):
    out, seen = [], set()
    for q in ("intern", "graduate", "student"):
        d = http.get("https://www.amazon.jobs/en/search.json",
                     params={"country": "AUS", "base_query": q, "result_limit": 100}).json()
        for j in d.get("jobs", []):
            if j.get("id_icims") in seen:
                continue
            seen.add(j.get("id_icims"))
            out.append(dict(native_id=j.get("id_icims"), title=j.get("title"),
                            location=j.get("normalized_location") or j.get("location"),
                            url="https://www.amazon.jobs" + (j.get("job_path") or ""), posted=_iso(j.get("posted_date")),
                            description=strip_html((j.get("description_short") or "") + " " + (j.get("basic_qualifications") or ""))))
    return out


def atlassian(spec, emp):
    d = http.get("https://www.atlassian.com/endpoint/careers/listings").json()
    items = d if isinstance(d, list) else d.get("listings") or d.get("data") or []
    out = []
    for j in items:
        locs = j.get("locations") or []
        out.append(dict(native_id=j.get("id"), title=j.get("title"),
                        location=" | ".join(l if isinstance(l, str) else str(l) for l in locs),
                        url=(j.get("portalJobPost") or {}).get("portalUrl") or j.get("applyUrl") or
                            f"https://www.atlassian.com/company/careers/details/{j.get('id')}",
                        description=strip_html(j.get("overview") or j.get("description") or "")))
    return out


def apple(spec, emp):
    u = "https://jobs.apple.com/en-au/search?location=australia-AUSC&team=internships-STDNT-INTRN"
    soup = BeautifulSoup(http.get(u).text, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"/details/")):
        t = a.get_text(" ", strip=True)
        if t:
            out.append(dict(native_id=a["href"], title=t, location="Australia", url=urljoin(u, a["href"])))
    for s in soup.find_all("script"):
        txt = s.string or ""
        for m in re.finditer(r'"postingTitle":"([^"]+)".{0,400}?"transformedPostingTitle":"([^"]+)".{0,400}?"positionId":"([^"]+)"', txt):
            out.append(dict(native_id=m.group(3), title=m.group(1), location="Australia",
                            url=f"https://jobs.apple.com/en-au/details/{m.group(3)}/{m.group(2)}"))
    return out


def google(spec, emp):
    u = ("https://www.google.com/about/careers/applications/jobs/results/?location=Australia"
         "&employment_type=INTERN&target_level=EARLY")
    soup = BeautifulSoup(http.get(u).text, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"jobs/results/\d+")):
        card = a.find_parent("li") or a.parent
        t = card.find("h3").get_text(strip=True) if card and card.find("h3") else a.get_text(" ", strip=True)
        if t:
            out.append(dict(native_id=a["href"], title=t, location="Australia", url=urljoin(u, a["href"])))
    return out


def readme_list(spec, emp):
    txt = http.get(spec["url"]).text
    out = []
    for line in txt.splitlines():
        if not AU_STRICT.search(line):
            continue
        cells = [c.strip() for c in re.split(r"\|", line) if c.strip()]
        if len(cells) < 3:
            continue
        links = re.findall(r"\((https?://[^)\s]+)\)|href=\"(https?://[^\"]+)\"", line)
        href = next((a or b for a, b in links), None)
        clean = [re.sub(r"<[^>]+>|\[|\]\([^)]*\)|\*\*", "", c).strip() for c in cells]
        out.append(dict(native_id=href or line[:80], title=clean[1] if len(clean) > 1 else clean[0],
                        company=clean[0], location=clean[2] if len(clean) > 2 else "", url=href))
    return out


ADAPTERS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters, "workday": workday,
    "workable": workable, "recruitee": recruitee, "teamtailor": teamtailor, "breezy": breezy, "bamboohr": bamboohr,
    "personio": personio, "rippling": rippling, "oracle": oracle, "eightfold": eightfold, "sf_rmk": sf_rmk,
    "pageup": pageup, "livehire": livehire, "employmenthero": employmenthero, "icims": icims, "hibob": hibob,
    "page": page, "rss": lambda spec, emp: _rss(spec["url"]),
    # aggregators / special
    "prosple": prosple, "gradconnection": gradconnection, "getro_board": getro_board, "talent": talent,
    "simplify": simplify, "amazon": amazon, "atlassian": atlassian, "apple": apple, "google": google,
    "readme_list": readme_list,
}
