"""A Torznab API in front of AudioBook Bay.

Endpoints:
  /api?t=caps
  /api?t=search&q=...            (empty q = latest uploads, used for RSS and tests)
  /api?t=book&title=...&author=...
  /download?u=<details url>      302 to the magnet; the details page is only fetched here
  /health
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.parse
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

from . import scraper

log = logging.getLogger("abb_torznab")

CATEGORY = 3030  # Audio/Audiobook


class TTLCache:
    def __init__(self, ttl: float, max_items: int = 500):
        self.ttl, self.max_items = ttl, max_items
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl:
                return hit[1]
            self._data.pop(key, None)
            return None

    def put(self, key, value):
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic(), value)


class Bridge:
    def __init__(self, fetcher: scraper.Fetcher, public_url: str, api_key: str | None, pages: int):
        self.fetcher = fetcher
        self.public_url = public_url.rstrip("/")
        self.api_key = api_key
        self.pages = pages
        self.search_cache = TTLCache(600)
        self.magnet_cache = TTLCache(86400, 5000)

    def search(self, query: str) -> list[scraper.Release]:
        key = query.strip().lower()
        cached = self.search_cache.get(key)
        if cached is not None:
            return cached
        results: list[scraper.Release] = []
        for page in range(1, (self.pages if key else 1) + 1):
            html, base = self.fetcher.get(scraper.search_path(query, page))
            found = scraper.parse_search(html, base)
            results += found
            if len(found) < 5:  # last page
                break
        self.search_cache.put(key, results)
        return results

    def magnet(self, details_url: str) -> str:
        cached = self.magnet_cache.get(details_url)
        if cached:
            return cached
        path = urllib.parse.urlsplit(details_url)
        if not path.path.startswith("/abss/"):
            raise ValueError("not an AudioBook Bay book page")
        html, _ = self.fetcher.get(path.path)
        uri = scraper.parse_details(html).uri()
        self.magnet_cache.put(details_url, uri)
        return uri

    def caps_xml(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8"?><caps>'
                '<server title="abb-torznab"/>'
                '<limits max="100" default="50"/>'
                '<searching>'
                '<search available="yes" supportedParams="q"/>'
                '<book-search available="yes" supportedParams="q,title,author"/>'
                '<tv-search available="no"/><movie-search available="no"/><music-search available="no"/>'
                '</searching>'
                f'<categories><category id="3000" name="Audio"><subcat id="{CATEGORY}" name="Audio/Audiobook"/></category></categories>'
                '</caps>')

    def results_xml(self, releases: list[scraper.Release]) -> str:
        items = []
        for r in releases:
            link = f"{self.public_url}/download?u=" + urllib.parse.quote(r.details, safe="")
            if self.api_key:
                link += "&apikey=" + urllib.parse.quote(self.api_key)
            desc = " | ".join(x for x in (r.category, r.language) if x)
            attrs = {"category": CATEGORY, "seeders": 1, "peers": 1, "downloadvolumefactor": 0,
                     "uploadvolumefactor": 1}
            if r.size:
                attrs["size"] = r.size
            if r.poster:
                attrs["coverurl"] = r.poster
            items.append(
                "<item>"
                f"<title>{escape(r.title)}</title>"
                f"<guid isPermaLink=\"true\">{escape(r.details)}</guid>"
                f"<comments>{escape(r.details)}</comments>"
                f"<link>{escape(link)}</link>"
                + (f"<pubDate>{format_datetime(r.posted)}</pubDate>" if r.posted else "")
                + (f"<size>{r.size}</size>" if r.size else "")
                + f"<description>{escape(desc)}</description>"
                f"<category>{CATEGORY}</category>"
                f"<enclosure url=\"{escape(link)}\" length=\"{r.size}\" type=\"application/x-bittorrent\"/>"
                + "".join(f'<torznab:attr name="{k}" value="{escape(str(v))}"/>' for k, v in attrs.items())
                + "</item>")
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
                'xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>'
                '<title>AudioBook Bay</title>' + "".join(items) + "</channel></rss>")


def error_xml(code: int, text: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><error code="{code}" description="{escape(text)}"/>'


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: str, ctype="application/xml", extra=None):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if url.path == "/health":
                return self._send(200, "ok", "text/plain")
            if bridge.api_key and qs.get("apikey") != bridge.api_key:
                return self._send(401, error_xml(100, "Incorrect user credentials"))
            try:
                if url.path in ("/api", "/api/"):
                    t = qs.get("t", "search")
                    if t == "caps":
                        return self._send(200, bridge.caps_xml())
                    if t in ("search", "book"):
                        cats = qs.get("cat")
                        if cats and not {"3000", str(CATEGORY)} & set(cats.split(",")):
                            return self._send(200, bridge.results_xml([]))
                        # Title alone searches best on ABB; the author narrows too hard.
                        query = qs.get("title") or qs.get("q", "")
                        if t == "book" and not query:
                            query = qs.get("author", "")
                        releases = bridge.search(query)
                        offset, limit = int(qs.get("offset", 0)), int(qs.get("limit", 100))
                        return self._send(200, bridge.results_xml(releases[offset:offset + limit]))
                    return self._send(200, error_xml(202, f"No such function ({t})"))
                if url.path == "/download":
                    magnet = bridge.magnet(qs.get("u", ""))
                    return self._send(302, "", "text/plain", {"Location": magnet})
                return self._send(404, error_xml(404, "not found"))
            except ValueError as e:
                return self._send(400, error_xml(201, str(e)))
            except ConnectionError as e:
                log.error("%s", e)
                return self._send(502, error_xml(900, "AudioBook Bay unreachable"))

    return Handler


def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mirrors = [m.strip() for m in os.environ.get("ABB_MIRRORS", "").split(",") if m.strip()] or scraper.DEFAULT_MIRRORS
    port = int(os.environ.get("PORT", "9117"))
    fetcher = scraper.Fetcher(mirrors, proxy=os.environ.get("ABB_PROXY") or None,
                              min_interval=float(os.environ.get("ABB_MIN_INTERVAL", "1.0")))
    bridge = Bridge(fetcher,
                    public_url=os.environ.get("PUBLIC_URL", f"http://localhost:{port}"),
                    api_key=os.environ.get("API_KEY") or None,
                    pages=int(os.environ.get("ABB_PAGES", "3")))
    log.info("abb-torznab on :%d, mirrors %s, proxy %s", port, ",".join(mirrors),
             "on" if fetcher.opener and os.environ.get("ABB_PROXY") else "off")
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(bridge)).serve_forever()


if __name__ == "__main__":
    main()
