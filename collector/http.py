"""Shared HTTP session: retries, per-host politeness, robots.txt for HTML pages."""
import threading, time, urllib.robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 au-eng-internships-tracker/1.0 (+https://github.com/Nemrra/au-eng-internships)")
BOT_NAME = "au-eng-internships-tracker"

_local = threading.local()
_host_lock = threading.Lock()
_host_next = {}
_robots = {}
_robots_lock = threading.Lock()
MIN_GAP = 0.6  # seconds between requests to the same host


class Blocked(Exception):
    pass


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        retry = Retry(total=2, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET", "POST"]), respect_retry_after_header=True)
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"})
        _local.s = s
    return s


def _wait_host(host):
    with _host_lock:
        now = time.time()
        nxt = _host_next.get(host, now)
        delay = max(0.0, nxt - now)
        _host_next[host] = max(now, nxt) + MIN_GAP
    if delay:
        time.sleep(delay)


def robots_ok(url):
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    with _robots_lock:
        rp = _robots.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = session().get(root + "/robots.txt", timeout=10)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.parse([])
        except Exception:
            rp.parse([])
        with _robots_lock:
            _robots[root] = rp
    try:
        return rp.can_fetch(BOT_NAME, url)
    except Exception:
        return True


def get(url, *, params=None, headers=None, timeout=25, check_robots=False, **kw):
    if check_robots and not robots_ok(url):
        raise Blocked(f"robots.txt disallows {url}")
    _wait_host(urlparse(url).netloc)
    r = session().get(url, params=params, headers=headers, timeout=timeout, **kw)
    if r.status_code in (401, 403, 999):
        raise Blocked(f"HTTP {r.status_code} for {r.url}")
    r.raise_for_status()
    return r


def post(url, *, json=None, data=None, headers=None, timeout=25):
    _wait_host(urlparse(url).netloc)
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = session().post(url, json=json, data=data, headers=h, timeout=timeout)
    if r.status_code in (401, 403, 999):
        raise Blocked(f"HTTP {r.status_code} for {r.url}")
    r.raise_for_status()
    return r
