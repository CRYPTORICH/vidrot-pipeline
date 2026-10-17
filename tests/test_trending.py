import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import trending


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
  <channel>
    <title>Daily Search Trends</title>
    <item>
      <title>Fish &amp; Chips</title>
      <ht:news_item>
        <ht:news_item_title>This headline is not a trend</ht:news_item_title>
      </ht:news_item>
    </item>
    <item>
      <title>  quiet   quitting  </title>
    </item>
    <item>
      <title>ok</title>
    </item>
  </channel>
</rss>
"""


class ParseTests(unittest.TestCase):
    def test_item_titles_only(self):
        titles = trending.parse_trend_titles(SAMPLE_RSS, max_results=10)
        self.assertEqual(titles, ["Fish & Chips", "quiet quitting"])

    def test_broken_xml_returns_empty(self):
        self.assertEqual(trending.parse_trend_titles("<title>not really xml"), [])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "config").mkdir()
        self.cache = self.base / "config" / "trending_cache.json"
        self.cache.write_text(json.dumps({
            "fetched_at": "2026-06-17T00:00:00",
            "source": "google_trends_rss",
            "trending": ["KEEP ME"],
            "count": 1,
        }))
        self.env = mock.patch.dict("os.environ", {"VIDROT_BASE": str(self.base)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_failed_scrape_does_not_wipe_cache(self):
        with mock.patch.object(trending, "fetch_rss", side_effect=TimeoutError("down")):
            self.assertEqual(trending.scrape_trends(), [])
            self.assertEqual(trending.get_trends(), ["KEEP ME"])
        self.assertIn("KEEP ME", self.cache.read_text())

    def test_empty_feed_does_not_wipe_cache(self):
        with mock.patch.object(trending, "fetch_rss", return_value="<rss></rss>"):
            self.assertEqual(trending.scrape_trends(), [])
        self.assertIn("KEEP ME", self.cache.read_text())

    def test_dry_fetch_does_not_rewrite_cache(self):
        with mock.patch.object(trending, "fetch_rss", return_value=SAMPLE_RSS):
            topics = trending.get_trends(write_cache=False)
        self.assertEqual(topics[0], "Fish & Chips")
        self.assertIn("KEEP ME", self.cache.read_text())

    def test_live_titles_replace_cache(self):
        with mock.patch.object(trending, "fetch_rss", return_value=SAMPLE_RSS):
            topics = trending.get_trends()
        self.assertEqual(topics[0], "Fish & Chips")
        saved = json.loads(self.cache.read_text())
        self.assertEqual(saved["trending"][0], "Fish & Chips")
        self.assertNotIn("This headline", " ".join(saved["trending"]))

    def test_missing_cache_uses_defaults(self):
        self.cache.unlink()
        with mock.patch.object(trending, "fetch_rss", side_effect=OSError("nope")):
            topics = trending.get_cached_trends()
        self.assertIn("QUIET QUITTING", topics)


if __name__ == "__main__":
    unittest.main()
