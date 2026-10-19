"""Fetch and parse AudioBook Bay pages."""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ABB answers 404 to non-browser user agents.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DEFAULT_MIRRORS = [
    "audiobookbay.lu", "audiobookbay.is", "audiobookbay.fi", "audiobookbay.se",
    "audiobookbay.li", "audiobookbay.nl", "theaudiobookbay.se",
]

DEFAULT_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
]

UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


@dataclass
class Release:
    title: str
    details: str       # absolute URL of the book page
    size: int          # bytes, 0 if unknown
    posted: datetime | None
    category: str      # ABB's own genre list, for the description
    language: str
    poster: str | None


@dataclass
class Magnet:
    infohash: str
    title: str
    trackers: list[str]

    def uri(self) -> str:
        parts = [f"magnet:?xt=urn:btih:{self.infohash}", "dn=" + urllib.parse.quote(self.title)]
        parts += ["tr=" + urllib.parse.quote(t, safe="") for t in self.trackers]
        return "&".join(parts)


class Fetcher:
    """HTTP GETs against ABB with mirror failover, an optional proxy and a polite rate limit."""

    def __init__(self, mirrors: list[str], proxy: str | None = None, min_interval: float = 1.0,
                 timeout: float = 20.0):
        self.mirrors = mirrors
        self.active = mirrors[0]
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
        self.opener = urllib.request.build_opener(*handlers)

    def _get(self, url: str) -> str:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        with self.opener.open(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def get(self, path_and_query: str) -> tuple[str, str]:
        """Fetch a path on the active mirror, moving to the next mirror on failure.

        Returns (html, base_url)."""
        order = [self.active] + [m for m in self.mirrors if m != self.active]
        last_err: Exception | None = None
        for host in order:
            base = f"https://{host}"
            try:
                html = self._get(base + path_and_query)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log.warning("mirror %s failed: %s", host, e)
                last_err = e
                continue
            if host != self.active:
                log.info("switching active mirror to %s", host)
                self.active = host
            return html, base
        raise ConnectionError(f"all mirrors failed, last error: {last_err}")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip() if node else ""


def parse_size(text: str) -> int:
    m = re.search(r"File Size:\s*([\d.]+)\s*([KMGT]B)", text)
    return int(float(m[1]) * UNITS[m[2]]) if m else 0


def parse_posted(text: str) -> datetime | None:
    m = re.search(r"Posted:\s*(\d{1,2} \w{3,4} \d{4})", text)
    if not m:
        return None
    try:
        return datetime.strptime(m[1].replace("Sept", "Sep"), "%d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_search(html: str, base: str) -> list[Release]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for post in soup.select("div.post"):
        a = post.select_one("div.postTitle h2 a")
        if not a or not a.get("href"):
            continue
        info = _text(post.select_one("div.postInfo"))
        body = _text(post.select_one("div.postContent"))
        img = post.select_one("div.postContent img")
        cat = re.search(r"Category:\s*(.*?)\s*Language:", info)
        lang = re.search(r"Language:\s*(\w+)", info)
        out.append(Release(
            title=_text(a),
            details=urllib.parse.urljoin(base + "/", a["href"]),
            size=parse_size(body),
            posted=parse_posted(body),
            category=cat[1] if cat else "",
            language=lang[1] if lang else "",
            poster=img.get("src") if img else None,
        ))
    return out


def parse_details(html: str) -> Magnet:
    soup = BeautifulSoup(html, "html.parser")
    infohash, trackers = None, []
    for td in soup.select("td"):
        label = td.get_text(strip=True)
        nxt = td.find_next_sibling("td")
        if not nxt:
            continue
        if label == "Info Hash:":
            infohash = nxt.get_text(strip=True).lower()
        elif label == "Tracker:":
            trackers.append(nxt.get_text(strip=True))
    if not infohash or not re.fullmatch(r"[0-9a-f]{40}", infohash):
        raise ValueError("no info hash on details page")
    h1 = soup.select_one("h1")
    seen = []
    for t in trackers + DEFAULT_TRACKERS:
        if t and t not in seen:
            seen.append(t)
    return Magnet(infohash=infohash, title=_text(h1) or infohash, trackers=seen)


def search_path(query: str, page: int = 1) -> str:
    # ABB ignores searches containing capitals and serves its front page instead.
    q = urllib.parse.quote_plus(query.strip().lower())
    prefix = f"/page/{page}" if page > 1 else ""
    return f"{prefix}/?s={q}" if q else (prefix + "/")
