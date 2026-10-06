"""One-off: save raw HTML of a few pages so parsers can be tuned (writes data/debug/)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collector import http
URLS = {
    "gc_list.html": "https://au.gradconnection.com/internships/engineering-electrical/",
    "gc_detail_tiktok.html": "https://au.gradconnection.com/employers/tiktok/jobs/tiktok-machine-learning-engineer-graduate-trust-and-safety-engineering-2027-start/",
    "gc_detail_lucid.html": "https://au.gradconnection.com/employers/lucid-consulting-australia/jobs/lucid-consulting-australia-undergraduate-electrical-engineer/",
}
os.makedirs("data/debug", exist_ok=True)
for name, u in URLS.items():
    try:
        r = http.get(u)
        open(f"data/debug/{name}", "w").write(r.text[:600000])
        print(name, r.status_code, len(r.text))
    except Exception as e:
        print(name, "ERR", e)
