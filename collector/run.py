"""Collector entry point: python -m collector.run [--discover] [--only TYPE]"""
import argparse, hashlib, json, os, re, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from . import adapters, http
from .classify import classify_url
from .discover import discover_one
from .filters import (FOREIGN_TITLE, au_states, disciplines, is_australian, is_student_or_grad, is_technical, role_type,
                      EXCLUDE_TITLE, PLACEMENT_AGENCIES, NON_AU_ONLY)
from .resolve import specs_for, spec_key
from .sources import AGGREGATORS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REG = os.path.join(ROOT, "registry")
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(timezone(timedelta(hours=11))).date().isoformat()  # Sydney-ish date


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        else:
            json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b20\d\d\s*[/\-–]\s*(20)?\d\d\b|\b20\d\d\b", " ", s)
    s = re.sub(r"\b(pty|ltd|limited|inc|australia|au|the|program|programme|opportunity|role|position)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def job_key(company, title):
    return norm(company) + "|" + norm(title)


def jid(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


KIND_RANK = {"ats": 3, "manual": 2, "aggregator": 1, "page": 0}
DISC_W = {"Semiconductors/FPGA": 15, "Electronics/Hardware": 14, "Embedded/Firmware": 14, "RF/Comms": 12,
          "Robotics/Autonomy": 12, "Quantum/Photonics": 12, "Controls/Automation": 10, "ML/AI/Data": 10,
          "Electrical": 10, "Power/Energy": 8, "Aerospace/Space": 8, "Systems/Integration": 8, "Mechatronics": 8,
          "Defence": 5, "Research": 5, "Biomedical": 4, "Software": 4, "Networks/Cyber": 2, "Quant/Trading": 4,
          "Mechanical": 1, "Manufacturing/Quality": 1, "Mining/Resources": -12, "Civil/Construction": -12,
          "Chemical/Process": -8}
ROLE_W = {"summer": 10, "part-time": 9, "year-long": 7, "vacation-research": 7, "cadetship": 7, "intern-other": 6,
          "winter": 5, "graduate": -8}


def base_score(priority, discs, rtype, flags):
    s = {"core": 55, "adjacent": 40, "deprioritised": 22}.get(priority, 35)
    s += max(-20, min(30, sum(DISC_W.get(d, 0) for d in discs)))
    s += ROLE_W.get(rtype, 0)
    if "placement-agency" in flags:
        s -= 40
    return max(0, min(100, s))


def run_task(task):
    kind, ctx, spec = task
    t0 = time.time()
    fn = adapters.ADAPTERS.get(spec["type"])
    if not fn:
        return task, [], f"no adapter for {spec['type']}", 0.0
    try:
        res = fn(spec, ctx)
        return task, res or [], None, time.time() - t0
    except http.Blocked as e:
        return task, [], f"blocked: {e}", time.time() - t0
    except Exception as e:
        return task, [], f"{type(e).__name__}: {str(e)[:200]}", time.time() - t0


JOBLIKE_URL = re.compile(r"/jobs?/|/job-|apply|position|vacanc|requisition|careers?/[^/]+/\d|opportunit|/role/|"
                         r"/details/|jobid|job_id|reqid", re.I)
INTAKE_TEXT = re.compile(r"20(2[6-9])|apply now|applications? (are )?(now )?open|now open|intake|expression of interest|"
                         r"\beoi\b|register (your )?interest", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="run ATS discovery for unresolved employers")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0, help="only first N employers (testing)")
    args = ap.parse_args()

    employers = load(os.path.join(REG, "employers.json"), {}).get("employers", [])
    if args.limit:
        employers = employers[: args.limit]
    emp_by_id = {e["id"]: e for e in employers}
    emp_by_norm = {}
    for e in employers:
        emp_by_norm.setdefault(norm(e["name"]), e)
    discovered = load(os.path.join(REG, "discovered.json"), {})
    health = load(os.path.join(DATA, "source_health.json"), {})
    state = load(os.path.join(DATA, "state.json"), {})
    details_cache = load(os.path.join(DATA, "details_cache.json"), {})
    page_watch = load(os.path.join(DATA, "page_watch.json"), {})
    manual = load(os.path.join(DATA, "manual.json"), {"jobs": []}).get("jobs", [])

    dead = {k for k, v in health.items() if v.get("fails", 0) >= 4 and v.get("last_error", "").startswith(("HTTPError: 404", "HTTPError: 410"))
            and v.get("retry_after", "") > TODAY}

    tasks, claimed = [], set()
    for emp in employers:
        specs, pages = specs_for(emp, discovered.get(emp["id"]), dead)
        for sp in specs + pages:
            k = spec_key(sp)
            if k in claimed:
                continue
            claimed.add(k)
            tasks.append(("page" if sp["type"] == "page" else "ats", emp, sp))
    for agg in AGGREGATORS:
        tasks.append(("aggregator", agg, dict(agg["spec"])))
    print(f"{len(tasks)} source tasks for {len(employers)} employers", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_task, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            results.append(f.result())
            if i % 100 == 0:
                print(f"  {i}/{len(tasks)} done", flush=True)

    # ------------------------------------------------------------ source health + page watch
    src_status, ok_sources, emp_ok = [], set(), {}
    for (kind, ctx, spec), raws, err, dur in results:
        k = spec_key(spec)
        name = ctx.get("name")
        sname = f"{name} [{spec['type']}]"
        src_status.append({"source": sname, "kind": kind, "spec": {kk: vv for kk, vv in spec.items() if not kk.startswith("_")},
                           "ok": err is None, "error": err, "raw_count": len(raws), "secs": round(dur, 1)})
        h = health.setdefault(k, {"employer": name})
        if err is None:
            ok_sources.add(sname)
            h.update(fails=0, last_ok=TODAY, last_error="")
            if kind == "ats":
                emp_ok[ctx["id"]] = True
        else:
            h["fails"] = h.get("fails", 0) + 1
            h["last_error"] = err
            if h["fails"] >= 4:
                h["retry_after"] = (NOW + timedelta(days=7)).date().isoformat()
        if spec["type"] == "page" and err is None:
            text = spec.get("_page_text", "")
            sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
                     if re.search(r"intern|vacation|graduate|student|cadet|summer|winter|applications?|clos|open", s, re.I)]
            sig = hashlib.sha1(" ".join(sents)[:8000].encode()).hexdigest()[:16]
            pw = page_watch.get(spec["url"], {})
            changed = pw.get("sig") and pw.get("sig") != sig
            page_watch[spec["url"]] = {
                "employer": name, "employer_id": ctx.get("id"), "sig": sig, "checked": TODAY,
                "changed": TODAY if changed else pw.get("changed"), "first_seen": pw.get("first_seen", TODAY),
                "keywords": sents[:12], "links": [{"title": r["title"], "url": r["url"]} for r in raws][:25],
            }

    # ------------------------------------------------------------ normalise + filter
    recs, auto_expected = [], []
    for (kind, ctx, spec), raws, err, dur in results:
        sname = f"{ctx.get('name')} [{spec['type']}]"
        for r in raws:
            title = re.sub(r"\s+", " ", (r.get("title") or "")).strip()
            url = r.get("url")
            if not title or not url:
                continue
            if kind == "page":
                if not (JOBLIKE_URL.search(url) or INTAKE_TEXT.search(title) or classify_url(url)):
                    continue
                # Global corporate portals list worldwide roles: need Australian evidence somewhere
                from urllib.parse import urlparse as _up
                pu, lu = _up(spec["url"]), _up(url)
                au_page = re.search(r"\.au$|australia|/au(/|$)|/en[-_]au|-au/", (pu.netloc + pu.path).lower())
                au_link = re.search(r"\.au$|australia|/au(/|$)|/en[-_]au|-au/", (lu.netloc + lu.path).lower())
                if not (au_page or au_link or au_states(title + " " + (r.get("row_text") or ""))):
                    continue
            desc = r.get("description") or ""
            card = r.get("card_text") or ""
            if EXCLUDE_TITLE.search(title):
                continue
            if FOREIGN_TITLE.search(title) and not au_states(title):
                continue
            if r.get("notify_only"):
                auto_expected.append({"company": r.get("company"), "program": re.sub(r"^Notify Me\s*-\s*", "", title),
                                      "url": url, "source": "GradConnection notify-me", "seen": TODAY})
                continue
            if spec["type"] == "gradconnection" and re.search(r"-(sg|hk|nz|my|in|uk|ph|id|vn|th|jp|cn|us)$", r.get("org_slug") or "x"):
                continue
            agg_student_site = spec["type"] in ("prosple", "gradconnection")
            if not (agg_student_site or is_student_or_grad(title, desc)):
                continue
            loc = r.get("location") or ""
            if kind == "aggregator":
                default_au = bool(ctx.get("default_au"))
                company = r.get("company") or ctx.get("company") or ""
                nc = norm(company)
                emp = emp_by_norm.get(nc) if nc else None
            else:
                emp = ctx
                company = emp["name"]
                default_au = kind == "page" or not loc
            loc_all = " ".join([loc, card if kind == "aggregator" else ""])
            if spec["type"] in ("prosple", "gradconnection"):
                au_ok = bool(au_states(loc)) if loc.strip() else not NON_AU_ONLY.search(title + " " + company)
            else:
                au_ok = is_australian(loc_all, default_au=default_au)
            if not au_ok:
                continue
            priority = (emp or {}).get("priority", "adjacent" if kind == "aggregator" else "adjacent")
            if not is_technical(title, desc + " " + card) and not (priority == "core" and len(desc) < 50):
                continue
            flags = []
            if PLACEMENT_AGENCIES.search(company + " " + title + " " + card):
                flags.append("placement-agency")
            if r.get("notify_only"):
                flags.append("notify-only")
            if kind == "page":
                flags.append("from-careers-page")
            rtype = role_type(title, desc + " " + card)
            if r.get("gc_kind") == "graduate-jobs" or r.get("prosple_type") == "graduate":
                if rtype == "intern-other" and not re.search(r"intern|student|vacation|cadet", title, re.I):
                    rtype = "graduate"
            discs = disciplines(title + " " + desc[:3000])
            recs.append({
                "key": job_key(company, title), "title": title, "company": company,
                "employer_id": (emp or {}).get("id"), "priority": priority,
                "sectors": (emp or {}).get("sectors", []), "location": loc[:300], "states": au_states(loc_all) or ["AU"],
                "url": url, "apply_url": r.get("apply_url"), "source": sname, "source_kind": kind, "source_type": spec["type"],
                "posted": r.get("posted"), "closes": r.get("closes"), "salary": r.get("salary"),
                "employment_type": r.get("employment_type"), "start_date": r.get("start_date"),
                "role_type": rtype, "disciplines": discs, "flags": flags, "description": desc[:6000],
                "card_text": card[:600],
            })

    for m in manual:
        if m.get("status") == "closed":
            continue
        if m.get("closes") and m["closes"] < TODAY:
            continue
        title, company = m.get("title", ""), m.get("company", "")
        emp = emp_by_norm.get(norm(company))
        recs.append({
            "key": job_key(company, title), "title": title, "company": company,
            "employer_id": (emp or {}).get("id"), "priority": (emp or {}).get("priority", m.get("priority", "adjacent")),
            "sectors": (emp or {}).get("sectors", []), "location": m.get("location", ""),
            "states": au_states(m.get("location", "")) or ["AU"], "url": m.get("url"), "source": "Claude web sweep",
            "source_kind": "manual", "source_type": m.get("found_via", "web"), "posted": m.get("opened"),
            "closes": m.get("closes"), "salary": m.get("pay"), "employment_type": None, "start_date": None,
            "role_type": m.get("role_type") or role_type(title, m.get("dates", "")),
            "disciplines": disciplines(title + " " + " ".join(m.get("discipline", []) if isinstance(m.get("discipline"), list) else [str(m.get("discipline", ""))])),
            "flags": ["manual"], "description": m.get("notes", "")[:3000], "card_text": "",
        })

    # ------------------------------------------------------------ detail pages for new aggregator items
    budget = 300
    for r in recs:
        if r["source_type"] not in ("prosple",) or budget <= 0:
            continue
        d = details_cache.get(r["url"])
        if d is None:
            budget -= 1
            try:
                d = adapters.prosple_detail(r["url"])
                d["fetched"] = TODAY
            except Exception as e:
                d = {"error": str(e)[:200], "fetched": TODAY}
            details_cache[r["url"]] = d
        if d and not d.get("error"):
            r["closes"] = d.get("closes") or r["closes"]
            r["posted"] = d.get("posted") or r["posted"]
            r["salary"] = d.get("salary") or r["salary"]
            r["employment_type"] = d.get("employment_type") or r["employment_type"]
            if d.get("description"):
                r["description"] = d["description"][:6000]
                r["role_type"] = role_type(r["title"], r["description"])
                r["disciplines"] = disciplines(r["title"] + " " + r["description"][:3000])
            if d.get("location"):
                r["location"] = d["location"][:300]
                st = au_states(d["location"])
                if not st:
                    r["drop"] = True
                r["states"] = st or r["states"]
            if d.get("company") and r["source_type"] == "prosple":
                r["company"] = d["company"]
                r["key"] = job_key(r["company"], r["title"])
    # Drop aggregator listings already closed according to detail page
    recs = [r for r in recs if not r.get("drop") and not (r.get("closes") and r["closes"] < TODAY)]

    # ------------------------------------------------------------ dedupe
    groups, url_key = {}, {}
    recs.sort(key=lambda x: KIND_RANK.get(x["source_kind"], 0), reverse=True)
    for r in recs:
        u = re.sub(r"[?#].*$", "", r["url"] or "").rstrip("/").lower()
        if u in url_key:
            r["key"] = url_key[u]
        else:
            url_key[u] = r["key"]
        groups.setdefault(r["key"], []).append(r)
    jobs = {}
    for key, rs in groups.items():
        rs.sort(key=lambda x: (KIND_RANK.get(x["source_kind"], 0), len(x["description"])), reverse=True)
        p = dict(rs[0])
        links, sources = [], []
        for x in rs:
            if x["url"] not in [l["url"] for l in links]:
                links.append({"url": x["url"], "source": x["source"]})
            if x["source"] not in sources:
                sources.append(x["source"])
            for f in ("closes", "salary", "posted", "employment_type", "start_date", "apply_url"):
                if not p.get(f) and x.get(f):
                    p[f] = x[f]
            if x.get("posted") and p.get("posted") and x["posted"] < p["posted"]:
                p["posted"] = x["posted"]
            p["states"] = sorted(set(p["states"]) | set(x["states"]))
            p["disciplines"] = sorted(set(p["disciplines"]) | set(x["disciplines"]))
            p["flags"] = sorted(set(p["flags"]) | set(x["flags"]))
            if len(x["description"]) > len(p["description"]):
                p["description"] = x["description"]
        if len(p["states"]) > 1 and "AU" in p["states"]:
            p["states"].remove("AU")
        p["links"] = links[:6]
        p["sources"] = sources
        p["id"] = jid(key)
        p["base_score"] = base_score(p["priority"], p["disciplines"], p["role_type"], p["flags"])
        jobs[p["id"]] = p

    # ------------------------------------------------------------ state, open/closed
    for id_, j in jobs.items():
        st = state.get(id_, {})
        st.update(first_seen=st.get("first_seen", TODAY), last_seen=TODAY, misses=0, status="open",
                  title=j["title"], company=j["company"], sources=j["sources"])
        state[id_] = st
        j["first_seen"] = st["first_seen"]
        j["last_seen"] = TODAY
    closed_now = []
    for id_, st in state.items():
        if id_ in jobs or st.get("status") == "closed":
            continue
        # only count a miss if at least one of its sources ran fine this time
        if any(s in ok_sources for s in st.get("sources", [])) or "Claude web sweep" in st.get("sources", []):
            st["misses"] = st.get("misses", 0) + 1
        if st.get("misses", 0) >= 3:
            st["status"] = "closed"
            st["closed_on"] = TODAY
            closed_now.append(id_)
    # prune long-closed state
    cutoff = (NOW - timedelta(days=120)).date().isoformat()
    state = {k: v for k, v in state.items() if not (v.get("status") == "closed" and v.get("closed_on", TODAY) < cutoff)}

    # ------------------------------------------------------------ outputs
    out_jobs, descs = [], {}
    for j in sorted(jobs.values(), key=lambda x: (x["first_seen"], x["base_score"]), reverse=True):
        descs[j["id"]] = j.pop("description", "")
        j.pop("card_text", None)
        j["snippet"] = descs[j["id"]][:400]
        out_jobs.append(j)
    save(os.path.join(DATA, "jobs.json"), {"count": len(out_jobs), "jobs": out_jobs})
    save(os.path.join(DATA, "descriptions.json"), descs, compact=True)
    save(os.path.join(DATA, "state.json"), state)
    save(os.path.join(DATA, "closed.json"), {"jobs": [dict(id=k, **{kk: v.get(kk) for kk in ("title", "company", "first_seen", "closed_on")})
                                                       for k, v in state.items() if v.get("status") == "closed"]})
    save(os.path.join(DATA, "source_health.json"), health)
    save(os.path.join(DATA, "details_cache.json"), details_cache, compact=True)
    save(os.path.join(DATA, "page_watch.json"), page_watch)
    ae = {}
    for a in auto_expected:
        ae.setdefault(a["url"], a)
    save(os.path.join(DATA, "expected_auto.json"), {"programs": sorted(ae.values(), key=lambda x: (x.get("company") or ""))})
    src_status.sort(key=lambda s: (s["ok"], s["source"]))
    ok = sum(1 for s in src_status if s["ok"])
    summary = {
        "run_at": NOW.isoformat(timespec="seconds"), "date": TODAY, "sources_total": len(src_status), "sources_ok": ok,
        "jobs_open": len(out_jobs), "new_today": sum(1 for j in out_jobs if j["first_seen"] == TODAY),
        "closed_this_run": len(closed_now),
        "by_type": {}, "errors_sample": [s for s in src_status if not s["ok"]][:60],
    }
    for s in src_status:
        bt = summary["by_type"].setdefault(s["spec"]["type"], {"ok": 0, "err": 0, "raw": 0})
        bt["ok" if s["ok"] else "err"] += 1
        bt["raw"] += s["raw_count"]
    save(os.path.join(DATA, "last_run.json"), summary)
    save(os.path.join(DATA, "sources_status.json"), src_status)
    print(json.dumps({k: v for k, v in summary.items() if k != "errors_sample"}, indent=1))

    # ------------------------------------------------------------ discovery
    if args.discover:
        todo = []
        for emp in employers:
            if emp_ok.get(emp["id"]):
                continue
            d = discovered.get(emp["id"])
            if d and d.get("checked", "") > (NOW - timedelta(days=6)).date().isoformat():
                continue
            todo.append(emp)
        print(f"discovery for {len(todo)} employers", flush=True)
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(discover_one, e): e for e in todo}
            for f in as_completed(futs):
                e = futs[f]
                try:
                    discovered[e["id"]] = f.result()
                except Exception as err:
                    discovered[e["id"]] = {"specs": [], "checked": TODAY, "error": str(err)[:200]}
        save(os.path.join(REG, "discovered.json"), discovered)
        print("discovered specs for", sum(1 for v in discovered.values() if v.get("specs")), "employers")


if __name__ == "__main__":
    main()
