"""Glue between the collector output (data/) and the dashboard's database, used by the scheduled Claude run.

  python tools/tracker_sync.py plan  --dbdump DUMP --work WORK [--sweep WORK/sweep_candidates.json]
  python tools/tracker_sync.py docs  --dbdump DUMP --work WORK
  python tools/tracker_sync.py id "Company" "Title"

DUMP is a directory written by ArtifactData list/get with out_dir (DUMP/jobs/<id>.json, DUMP/meta/<doc>.json, DUMP/marks/<id>.json).
plan  -> WORK/new_batch_NN.json (listings to analyse), WORK/new_records.json, WORK/plan.json
docs  -> reads WORK/enriched_*.json, writes WORK/docs/... and WORK/writes_NN.json (ArtifactData batch payloads),
         WORK/notify.json (what is worth telling the user)
Every job doc carries `rev` = its database version, so updates can pass if_version without re-reading.
"""
import argparse, datetime, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from collector.run import job_key, jid  # noqa: E402

SYD = datetime.timezone(datetime.timedelta(hours=11))
NOW = datetime.datetime.now(SYD)
TODAY = NOW.date().isoformat()


def load(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def dump_docs(dump, coll):
    out = {}
    for f in glob.glob(os.path.join(dump, coll, "*.json")):
        out[os.path.basename(f)[:-5]] = load(f, {})
    return out


def plan(a):
    jobs = {j["id"]: j for j in load(os.path.join(ROOT, "data/jobs.json"), {"jobs": []})["jobs"]}
    descs = load(os.path.join(ROOT, "data/descriptions.json"), {})
    state = load(os.path.join(ROOT, "data/state.json"), {})
    db = dump_docs(a.dbdump, "jobs")
    dropped = load(os.path.join(a.dbdump, "meta", "dropped.json"), {}).get("ids", {})
    sweep = load(a.sweep, []) if a.sweep else []
    os.makedirs(a.work, exist_ok=True)

    new_records = {}
    for jid_, j in jobs.items():
        if jid_ in db or jid_ in dropped:
            continue
        rec = dict(j)
        rec["description"] = (descs.get(jid_) or "")[:2600]
        new_records[jid_] = rec
    sweep_new = 0
    for c in sweep:
        if not c.get("title") or not c.get("company") or not c.get("url"):
            continue
        i = jid(job_key(c["company"], c["title"]))
        if i in db or i in dropped or i in jobs or i in new_records:
            continue
        new_records[i] = {
            "id": i, "title": c["title"], "company": c["company"], "location": c.get("location", ""),
            "states": [], "role_type": c.get("role_type"), "disciplines": [], "url": c["url"],
            "links": [{"url": c["url"], "source": c.get("found_on", "web search")}],
            "sources": ["Claude web sweep"], "posted": c.get("posted"), "closes": c.get("closes"),
            "salary": c.get("pay"), "flags": ["sweep"], "priority": "adjacent", "sectors": [],
            "first_seen": TODAY, "last_seen": TODAY, "description": (c.get("description") or "")[:2600],
        }
        sweep_new += 1

    # closures / updates for docs already on the board
    closures, updates = [], []
    for i, d in db.items():
        if d.get("status") != "open":
            continue
        rev = d.get("rev", 1)
        st = state.get(i, {})
        j = jobs.get(i)
        sweep_only = all(s == "Claude web sweep" for s in d.get("sources", [])) and i not in jobs
        closes = d.get("closes")
        if closes and closes < TODAY:
            closures.append({"id": i, "rev": rev, "reason": f"closing date {closes} passed"})
        elif j is None and not sweep_only and st.get("status") == "closed":
            closures.append({"id": i, "rev": rev, "reason": "no longer listed at source"})
        elif j is not None and j.get("closes") and j.get("closes") != closes:
            updates.append({"id": i, "rev": rev, "set": {"closes": j["closes"]}})
    recheck = [i for i, d in db.items() if d.get("status") == "open"
               and all(s == "Claude web sweep" for s in d.get("sources", []))
               and (d.get("verified_at") or d.get("first_seen") or TODAY) < (NOW - datetime.timedelta(days=10)).date().isoformat()]

    # batches for analysis (highest-potential first)
    order = {"core": 0, "adjacent": 1, "deprioritised": 2}
    todo = sorted(new_records.values(), key=lambda x: (x.get("role_type") == "graduate", order.get(x.get("priority"), 1)))
    for f in glob.glob(os.path.join(a.work, "new_batch_*.json")):
        os.remove(f)
    for n, k in enumerate(range(0, len(todo), 25), 1):
        batch = [{
            "id": r["id"], "title": r["title"], "company": r["company"], "location": r.get("location"),
            "states": r.get("states"), "role_type_guess": r.get("role_type"), "disciplines_guess": r.get("disciplines"),
            "url": r.get("url"), "other_links": [l["url"] for l in r.get("links", [])[1:4]], "sources": r.get("sources"),
            "posted": r.get("posted"), "closes": r.get("closes"), "salary": r.get("salary"),
            "employment_type": r.get("employment_type"), "flags": r.get("flags"),
            "registry_priority": r.get("priority"), "registry_sectors": (r.get("sectors") or [])[:4],
            "description": r.get("description", ""),
        } for r in todo[k:k + 25]]
        json.dump(batch, open(os.path.join(a.work, f"new_batch_{n:02d}.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(new_records, open(os.path.join(a.work, "new_records.json"), "w"), ensure_ascii=False)
    p = {"today": TODAY, "new": len(new_records), "new_from_sweep": sweep_new, "closures": closures,
         "updates": updates, "recheck_sweep_listings": recheck, "db_open": sum(1 for d in db.values() if d.get("status") == "open"),
         "batches": len(range(0, len(todo), 25))}
    json.dump(p, open(os.path.join(a.work, "plan.json"), "w"), indent=1)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in p.items()}))


def build_doc(rec, e):
    links = rec.get("links") or [{"url": rec.get("url"), "source": "link"}]
    doc = {
        "status": "open", "title": rec["title"], "company": rec["company"], "location": rec.get("location") or "",
        "states": rec.get("states") or [], "role_type": rec.get("role_type"), "disciplines": rec.get("disciplines") or [],
        "priority": rec.get("priority"),
        "links": [{"url": l["url"], "source": (l.get("source") or "").split(" [")[-1].rstrip("]") or "link"} for l in links if l.get("url")][:6],
        "apply_url": rec.get("apply_url") or (links[0]["url"] if links else rec.get("url")),
        "first_seen": rec.get("first_seen") or TODAY, "last_seen": rec.get("last_seen") or TODAY,
        "opened": rec.get("posted"), "closes": rec.get("closes"), "flags": rec.get("flags") or [],
        "pay": {"text": rec.get("salary"), "estimated": False} if rec.get("salary") else None,
        "sources": rec.get("sources") or [], "base_score": rec.get("base_score"), "fit_score": rec.get("base_score"),
        "rev": 1,
    }
    for k in ("company", "title", "industry", "work_type", "summary", "role_type", "location", "states", "dates",
              "closes_text", "pay", "eligibility", "fit_score", "fit_reason", "career_keywords", "skill_categories",
              "projects", "ideal_projects", "screen"):
        v = e.get(k)
        if v not in (None, "", [], {}):
            doc[k] = v
    for k in ("opened", "closes"):
        if e.get(k) and not doc.get(k):
            doc[k] = e[k]
    if e.get("verified"):
        doc["verified_at"] = TODAY
    doc["enriched_at"] = NOW.isoformat(timespec="seconds")
    return doc


def docs(a):
    new_records = load(os.path.join(a.work, "new_records.json"), {})
    p = load(os.path.join(a.work, "plan.json"), {})
    db = dump_docs(a.dbdump, "jobs")
    marks = dump_docs(a.dbdump, "marks")
    dropped_doc = load(os.path.join(a.dbdump, "meta", "dropped.json"), {})
    dropped = dropped_doc.get("ids", {})
    enriched = {}
    for f in sorted(glob.glob(os.path.join(a.work, "enriched_*.json"))):
        for r in load(f, []):
            if isinstance(r, dict) and r.get("id"):
                enriched[r["id"]] = r
    out = os.path.join(a.work, "docs")
    os.makedirs(out, exist_ok=True)
    writes, new_kept, new_dropped = [], [], 0
    for i, rec in new_records.items():
        e = enriched.get(i)
        if e is None:
            continue  # not analysed this run; picked up next time
        if e.get("keep") is False:
            dropped[i] = {"reason": (e.get("drop_reason") or "")[:140], "title": rec.get("title", "")[:100],
                          "company": rec.get("company", "")[:60], "on": TODAY}
            new_dropped += 1
            continue
        d = build_doc(rec, e)
        fp = os.path.join(out, f"job_{i}.json")
        json.dump(d, open(fp, "w"), ensure_ascii=False)
        writes.append({"op": "set", "collection": "jobs", "doc_id": i, "file_path": os.path.abspath(fp)})
        new_kept.append({"id": i, "title": d["title"], "company": d["company"], "fit": d.get("fit_score") or 0,
                         "closes": d.get("closes"), "role_type": d.get("role_type"), "url": d.get("apply_url")})
    for c in p.get("closures", []):
        d = dict(db.get(c["id"], {}))
        if not d:
            continue
        d.update(status="closed", closed_on=TODAY, close_reason=c["reason"], rev=c["rev"] + 1)
        fp = os.path.join(out, f"job_{c['id']}.json")
        json.dump(d, open(fp, "w"), ensure_ascii=False)
        writes.append({"op": "set", "collection": "jobs", "doc_id": c["id"], "file_path": os.path.abspath(fp), "if_version": c["rev"]})
    for u in p.get("updates", []):
        d = dict(db.get(u["id"], {}))
        if not d:
            continue
        d.update(u["set"])
        d["rev"] = u["rev"] + 1
        fp = os.path.join(out, f"job_{u['id']}.json")
        json.dump(d, open(fp, "w"), ensure_ascii=False)
        writes.append({"op": "set", "collection": "jobs", "doc_id": u["id"], "file_path": os.path.abspath(fp), "if_version": u["rev"]})
    # meta/dropped (keep the newest 3000)
    if new_dropped:
        ids = dict(sorted(dropped.items(), key=lambda kv: kv[1].get("on", ""), reverse=True)[:3000])
        drev = dropped_doc.get("rev")
        fp = os.path.join(out, "meta_dropped.json")
        json.dump({"ids": ids, "rev": (drev or 0) + 1}, open(fp, "w"))
        w = {"op": "set", "collection": "meta", "doc_id": "dropped", "file_path": os.path.abspath(fp)}
        if drev:
            w["if_version"] = drev
        writes.append(w)
    # meta/status
    lr = load(os.path.join(ROOT, "data/last_run.json"), {})
    status_doc = load(os.path.join(a.dbdump, "meta", "status.json"), {})
    open_after = p.get("db_open", 0) + len(new_kept) - len(p.get("closures", []))
    srev = status_doc.get("rev")
    st = {
        "updated_at": NOW.isoformat(timespec="seconds"), "collector_run_at": lr.get("run_at"),
        "sources_ok": lr.get("sources_ok"), "sources_total": lr.get("sources_total"), "employers": status_doc.get("employers", 682),
        "source_types": [{"name": k, "ok": v["ok"], "total": v["ok"] + v["err"]} for k, v in
                         sorted((lr.get("by_type") or {}).items(), key=lambda x: -(x[1]["ok"] + x[1]["err"]))],
        "summary": (f"{NOW.strftime('%a %d %b %H:%M')}: {len(new_kept)} new listing(s) added, {new_dropped} rejected as off-target, "
                    f"{len(p.get('closures', []))} closed, {open_after} open."),
        "rev": (srev or 0) + 1,
    }
    fp = os.path.join(out, "meta_status.json")
    json.dump(st, open(fp, "w"))
    w = {"op": "set", "collection": "meta", "doc_id": "status", "file_path": os.path.abspath(fp)}
    if srev:
        w["if_version"] = srev
    elif status_doc:
        w["if_version"] = 1
    writes.append(w)
    for f in glob.glob(os.path.join(a.work, "writes_*.json")):
        os.remove(f)
    for n, k in enumerate(range(0, len(writes), 50), 1):
        json.dump(writes[k:k + 50], open(os.path.join(a.work, f"writes_{n:02d}.json"), "w"))
    # what to tell the user
    applied = {i for i, m in marks.items() if m.get("status") in ("applied", "applying", "interview", "offer", "rejected", "hidden")}
    soon = []
    for i, d in db.items():
        if d.get("status") != "open" or i in applied or not d.get("closes"):
            continue
        days = (datetime.date.fromisoformat(d["closes"]) - NOW.date()).days
        if 0 <= days <= 3 and (d.get("fit_score") or 0) >= 60:
            soon.append({"title": d["title"], "company": d["company"], "fit": d.get("fit_score"), "days": days})
    top = sorted([n for n in new_kept if n["fit"] >= 55], key=lambda x: -x["fit"])
    notify = {"new_relevant": top, "new_total": len(new_kept), "closing_soon": sorted(soon, key=lambda x: x["days"]),
              "closed": len(p.get("closures", [])), "dropped": new_dropped,
              "worth_notifying": bool(top or soon)}
    json.dump(notify, open(os.path.join(a.work, "notify.json"), "w"), indent=1)
    print(json.dumps({"writes": len(writes), "write_batches": len(range(0, len(writes), 50)), "new_kept": len(new_kept),
                      "dropped": new_dropped, "closures": len(p.get("closures", [])), "notify": notify["worth_notifying"]}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    for c in ("plan", "docs"):
        s = sub.add_parser(c)
        s.add_argument("--dbdump", required=True)
        s.add_argument("--work", required=True)
        s.add_argument("--sweep")
    s = sub.add_parser("id")
    s.add_argument("company")
    s.add_argument("title")
    a = ap.parse_args()
    if a.cmd == "plan":
        plan(a)
    elif a.cmd == "docs":
        docs(a)
    elif a.cmd == "id":
        print(jid(job_key(a.company, a.title)))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
