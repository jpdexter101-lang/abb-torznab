import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from abb_torznab import scraper
from abb_torznab.server import Bridge

FIX = Path(__file__).parent / "fixtures"


class ScraperTests(unittest.TestCase):
    def test_parse_search(self):
        rows = scraper.parse_search((FIX / "search.html").read_text(), "https://audiobookbay.lu")
        self.assertEqual(len(rows), 2)
        a, b = rows
        self.assertEqual(a.title, "Sample Book One - Jane Author")
        self.assertEqual(a.details, "https://audiobookbay.lu/abss/sample-book-one-jane-author/")
        self.assertEqual(a.size, int(11.62 * 1024**3))
        self.assertEqual(a.posted.strftime("%Y-%m-%d"), "2025-05-27")
        self.assertEqual(a.category, "Fantasy LitRPG")
        self.assertEqual(a.language, "English")
        self.assertEqual(a.poster, "https://example.com/cover1.jpg")
        self.assertEqual(b.size, int(512.5 * 1024**2))
        self.assertEqual(b.posted.strftime("%Y-%m-%d"), "2021-09-07")

    def test_parse_details(self):
        m = scraper.parse_details((FIX / "details.html").read_text())
        self.assertEqual(m.infohash, "5d937105e17832b0e460f5a0bac95af256f13800")
        self.assertEqual(m.trackers[0], "http://tracker.example.org:80/announce")
        self.assertEqual(len(m.trackers), len(set(m.trackers)))
        self.assertTrue(m.uri().startswith("magnet:?xt=urn:btih:5d9371"))

    def test_details_without_hash(self):
        with self.assertRaises(ValueError):
            scraper.parse_details("<html><td>Info Hash:</td><td>nope</td></html>")

    def test_search_path(self):
        self.assertEqual(scraper.search_path("He Who Fights"), "/?s=he+who+fights")
        self.assertEqual(scraper.search_path("x", 2), "/page/2/?s=x")
        self.assertEqual(scraper.search_path(""), "/")


class FeedTests(unittest.TestCase):
    def test_results_xml_is_valid_torznab(self):
        rows = scraper.parse_search((FIX / "search.html").read_text(), "https://audiobookbay.lu")
        bridge = Bridge(scraper.Fetcher(["example.invalid"]), "http://bridge:9117", "k&y", 1)
        root = ET.fromstring(bridge.results_xml(rows))
        items = root.findall("./channel/item")
        self.assertEqual(len(items), 2)
        self.assertIn("apikey=k%26y", items[0].find("link").text)
        self.assertEqual(items[0].find("enclosure").get("length"), str(int(11.62 * 1024**3)))
        ET.fromstring(bridge.caps_xml())


if __name__ == "__main__":
    unittest.main()
