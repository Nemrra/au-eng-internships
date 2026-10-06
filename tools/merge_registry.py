"""Merge the per-sector research files into registry/employers.json.

Usage: python tools/merge_registry.py <dir with sector json files>
Deduplicates employers by normalised name, keeps every URL found in each entry
so the collector's resolver can derive adapters from them.
"""
import json, glob, os, re, sys

PRIO = {"core": 3, "adjacent": 2, "deprioritised": 1}


def norm_name(n: str) -> str:
    n = n.lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\b(pty|ltd|limited|inc|group|australia|australian|au|aus|corporation|corp|holdings|plc|co)\b", " ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    return n


def slug(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")[:60]


URL_RE = re.compile(r"https?://[^\s\"'<>()\]]+")


def urls_in(obj):
    out = []
    if isinstance(obj, str):
        out += URL_RE.findall(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += urls_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += urls_in(v)
    return out


def as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x]
    return [s.strip() for s in str(x).split(",") if s.strip()]


def main(src):
    merged = {}
    for f in sorted(glob.glob(os.path.join(src, "*.json"))):
        base = os.path.basename(f)
        if base.startswith("open_") or base == "aggregators.json":
            continue
        sector_file = base.replace(".json", "")
        for e in json.load(open(f)).get("employers", []):
            name = e.get("name") or "?"
            key = norm_name(name) or slug(name)
            ats = e.get("ats") or {}
            if isinstance(ats, str):
                ats = {"type": ats}
            verified = bool(ats.get("verified") is True)
            rec = merged.get(key)
            if rec is None:
                rec = merged[key] = {
                    "id": slug(name),
                    "name": name,
                    "sectors": [],
                    "priority": None,
                    "locations": [],
                    "careers_url": None,
                    "program_url": None,
                    "ats_hints": [],
                    "urls": [],
                    "typical_open_months": None,
                    "notes": [],
                    "source_files": [],
                }
            rec["source_files"].append(sector_file)
            for s in as_list(e.get("sectors")):
                if s not in rec["sectors"]:
                    rec["sectors"].append(s)
            for s in as_list(e.get("au_locations")):
                if s not in rec["locations"]:
                    rec["locations"].append(s)
            p = (e.get("priority_hint") or "").lower()
            if PRIO.get(p, 0) > PRIO.get(rec["priority"] or "", 0):
                rec["priority"] = p
            for fld, dst in (("careers_url", "careers_url"), ("student_program_url", "program_url")):
                v = e.get(fld)
                if isinstance(v, list):
                    v = v[0] if v else None
                if v and not rec[dst]:
                    rec[dst] = v
            hint = {"type": str(ats.get("type") or "unknown").lower(), "verified": verified,
                    "raw": ats, "from": sector_file}
            # verified hints first
            if verified:
                rec["ats_hints"].insert(0, hint)
            else:
                rec["ats_hints"].append(hint)
            for u in urls_in(e):
                u = u.rstrip(".,;")
                if u not in rec["urls"]:
                    rec["urls"].append(u)
            tom = e.get("typical_open_months")
            if tom and not rec["typical_open_months"]:
                rec["typical_open_months"] = tom if isinstance(tom, str) else json.dumps(tom)
            if e.get("notes"):
                rec["notes"].append(str(e["notes"])[:600])
    out = sorted(merged.values(), key=lambda r: (-PRIO.get(r["priority"] or "", 0), r["name"].lower()))
    seen = set()
    for r in out:
        if r["id"] in seen:
            r["id"] = r["id"] + "-" + str(len(seen))
        seen.add(r["id"])
        r["priority"] = r["priority"] or "adjacent"
        r["notes"] = " | ".join(r["notes"])[:1200]
    os.makedirs("registry", exist_ok=True)
    json.dump({"generated": "2026-10-06", "employers": out}, open("registry/employers.json", "w"), indent=1)
    print(len(out), "employers")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../registry")
