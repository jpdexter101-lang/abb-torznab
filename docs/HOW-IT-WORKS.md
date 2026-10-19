# How it works

AudioBook Bay (ABB) stopped working as an indexer because it blocks four different things at once.
This project gets past all four, either as a standalone Torznab bridge or as a Prowlarr definition.

## The problem

Prowlarr does not ship an AudioBook Bay indexer, and a plain hand-written one fails four ways.

| Block | What you see | Why it happens | Fix |
| --- | --- | --- | --- |
| VPN exit blocked | Every ABB address times out | Many *arr stacks run Prowlarr inside a VPN container (gluetun etc.). ABB drops a lot of data-center / VPN IP ranges | Send only ABB requests through a small proxy outside the VPN |
| Bot user agent | `404 Not Found` from Prowlarr, `200` in a browser | ABB refuses non-browser user agents | Send a normal Chrome user agent |
| Capital letters | Searches return ABB's front page (latest uploads); Prowlarr then pauses the indexer for "recent failures" | ABB redirects any search containing a capital letter to its home page | Lowercase the search words before sending |
| No magnet in results | Search pages list books but no download link | The torrent info hash is only on each book's own page | On grab, open the book page, read the info hash, build a magnet link |

## How a search flows

1. Chaptarr / Readarr asks for a book. The indexer advertises keyword-only book search, so the app
   sends one combined query such as `Shirtaloon He Who Fights with Monsters`.
2. The query is lowercased and sent as `https://audiobookbay.lu/?s=shirtaloon+he+who+fights+with+monsters`
   with a Chrome user agent.
3. If you need it, the request goes through the ABB-only proxy instead of your VPN.
4. Each result on the page is read: title, book page link, size ("File Size: 11.62 GBs"),
   date ("Posted: 27 May 2025") and cover. ABB shows no seeder counts, so seeders are reported as 1.
5. When the app grabs a result, the book's page is opened, its 40-character Info Hash is read,
   and the download client gets a magnet link.
6. Your torrent client downloads it as usual (through your VPN, if it uses one).

## Two ways to run it

### A. The bridge (any app that speaks Torznab)

Run `abb-torznab` (see the README) and add it as a **Torznab** indexer in Chaptarr / Readarr /
LazyLibrarian, or as **Generic Torznab** in Prowlarr.

- **Lazy magnets.** Each result links back to the bridge's `/download?u=<book page>`. Only on grab does
  it open that page and answer with a 302 redirect to the magnet, so a search costs one fetch per
  results page.
- **Mirrors.** If a mirror stops answering, the next one in `ABB_MIRRORS` is tried and kept.
- **Politeness.** Searches are cached 10 minutes, magnets a day, and requests to ABB are spaced at
  least `ABB_MIN_INTERVAL` seconds apart.
- **Blocked VPN?** Set `ABB_PROXY` to the proxy below, or run the bridge outside your VPN.

### B. Prowlarr only

1. Copy `prowlarr/audiobook-bay.yml` into Prowlarr's `Definitions/Custom/` folder (create it if missing).
   Prowlarr picks it up without a restart; it shows as "AudioBook Bay".
2. If Prowlarr runs inside a VPN that ABB blocks:
   1. Run the proxy in `proxy/` on a machine **outside** the VPN.
   2. In Prowlarr: Settings → Tags, create a tag such as `abb-proxy`.
   3. Settings → Indexers → Indexer Proxies → **+** → **Http**, host/port of the proxy, tag `abb-proxy`.
      A proxy with a tag only applies to indexers with that tag; a proxy with **no** tag applies to all.
3. Add the AudioBook Bay indexer with the same tag. Prowlarr syncs it to your apps.

## The proxy

`proxy/` is tinyproxy on Alpine with two locks:

- **Who may connect:** only `127.0.0.1` and Docker networks (`172.16.0.0/12`). Add your LAN range to
  `tinyproxy.conf` (`Allow 192.168.1.0/24`) only if something outside Docker must use it.
- **Where it may go:** `filter` allows only ABB domains and `prowlarr.servarr.com` (Prowlarr's
  proxy self-test). Everything else is refused.

Trade-off: ABB sees the proxy's IP (normally your home IP) when you search or grab. The torrent
traffic itself still goes through whatever your download client uses.

## Gotchas

- **Prowlarr caches definitions.** After editing the `.yml`, restart Prowlarr, or change both the
  file name and the `id:` inside it and re-add the indexer.
- **Lidarr may receive it too**, because Prowlarr syncs audio categories to Lidarr. It is harmless:
  Lidarr only matches music albums.
- **Docker "address pools fully subnetted".** If `docker compose up` for the proxy fails with that,
  add `network_mode: bridge` to its service.
- **If ABB changes its page layout,** searches come back empty. Update the selectors in
  `prowlarr/audiobook-bay.yml` or `abb_torznab/scraper.py`.

## Undo

- Bridge: remove the indexer from your apps and stop the container.
- Prowlarr route: delete the indexer, the proxy and the tag in Prowlarr, delete the `.yml`, and
  `docker compose down` the proxy. The next sync removes it from your apps.
