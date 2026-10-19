# abb-torznab

A small Torznab bridge for AudioBook Bay, so Chaptarr, Readarr, LazyLibrarian or Prowlarr can
search it like any other indexer.

Prowlarr and Jackett no longer ship a working AudioBook Bay indexer. The site:

- answers `404` to anything that does not look like a web browser,
- redirects any search containing capital letters to its front page,
- blocks many VPN / data-center IP ranges,
- only shows the torrent info hash on each book's own page, not in search results.

This service deals with all four. The full write-up of the problem and the fix is in
[docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

## How it works

```
Chaptarr ──Torznab──▶ abb-torznab ──HTTPS (browser UA, optional proxy)──▶ AudioBook Bay
   │                      │
   └── /download?u=… ─────┘  fetches the book page, reads the info hash, 302s to a magnet link
```

- `GET /api?t=caps` advertises one category, `3030 Audio/Audiobook`, plus `search` and `book-search`.
- `GET /api?t=search&q=…` and `t=book&title=…&author=…` scrape up to `ABB_PAGES` result pages.
  Queries are lowercased. An empty query returns the latest uploads (used for RSS and app tests).
- Each result's link points back at this service. The book page is only fetched when a
  release is actually grabbed, so searches stay fast and light on the site.
- Searches are cached for 10 minutes and magnets for a day. Requests to ABB are spaced at
  least `ABB_MIN_INTERVAL` seconds apart.
- If a mirror stops answering, the next one in `ABB_MIRRORS` is tried and kept.

## Run it

```sh
docker compose -f docker-compose.example.yml up -d --build
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `9117` | Listen port |
| `PUBLIC_URL` | `http://localhost:9117` | How your *arr apps reach this service; used in download links |
| `API_KEY` | empty | If set, every request must carry `apikey=` |
| `ABB_PROXY` | empty | HTTP proxy for requests to ABB, e.g. when your VPN exit is blocked |
| `ABB_MIRRORS` | built-in list | Comma-separated hostnames, tried in order |
| `ABB_PAGES` | `3` | Result pages fetched per search |
| `ABB_MIN_INTERVAL` | `1.0` | Seconds between requests to ABB |

## Add it to Chaptarr / Readarr

Settings → Indexers → **+** → **Torznab**

- URL: your `PUBLIC_URL`
- API Path: `/api`
- API Key: your `API_KEY` (or anything, if unset)
- Categories: `3030`

Or add it to Prowlarr as **Generic Torznab** and let Prowlarr sync it to your apps.

## Prowlarr-only alternative

`prowlarr/audiobook-bay.yml` is a Cardigann definition doing the same scrape inside Prowlarr.
Copy it to Prowlarr's `Definitions/Custom/` folder. If your VPN exit is blocked, `proxy/` has an
ABB-only HTTP proxy to pair it with (setup in [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)). Prowlarr caches definitions, so after editing
one either restart Prowlarr or change its `id` and file name.

## Tests

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -t .
```

## Disclaimer

This project is not affiliated with AudioBook Bay. It hosts no content and only translates the
site's public pages into the Torznab format. You are responsible for what you download and for
following the laws where you live.

## License

MIT
