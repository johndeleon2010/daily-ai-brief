import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from generate_brief import PACIFIC, parse_feed, select_items, should_run


FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">
  <entry><yt:videoId>abc123</yt:videoId><title>Build a useful agent</title><published>2026-09-14T12:00:00+00:00</published><link href="https://youtu.be/abc123"/><media:group><media:description>Practical agent design.</media:description></media:group></entry>
</feed>'''


class BriefTests(unittest.TestCase):
    def test_parse_feed_preserves_source(self):
        creator = {"name": "Creator", "focus": ["Agents"], "priority": 3}
        item = parse_feed(FEED, creator)[0]
        self.assertEqual(item["id"], "abc123")
        self.assertEqual(item["source"], "https://youtu.be/abc123")

    def test_selection_deduplicates_and_limits_creator(self):
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)
        base = {"creator": "A", "focus": ["Agents"], "priority": 3, "published": "2026-09-14T12:00:00+00:00", "description": "x"}
        items = [{**base, "id": str(index), "title": str(index), "source": f"https://x/{index}"} for index in range(4)]
        selected = select_items(items, now, limit=10)
        self.assertEqual(len(selected), 2)

    def test_pacific_weekday_gate_handles_dst(self):
        summer = dt.datetime(2026, 9, 14, 14, 30, tzinfo=dt.timezone.utc)
        winter = dt.datetime(2026, 12, 14, 15, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(summer.astimezone(PACIFIC).hour, 7)
        self.assertEqual(winter.astimezone(PACIFIC).hour, 7)
        self.assertTrue(should_run(summer, False))
        self.assertTrue(should_run(winter, False))

    def test_dashboard_files_are_present(self):
        docs = Path(__file__).resolve().parents[1] / "docs"
        self.assertTrue((docs / "index.html").is_file())
        self.assertTrue((docs / "app.js").is_file())
        self.assertTrue((docs / "data" / "latest.json").is_file())


if __name__ == "__main__":
    unittest.main()
