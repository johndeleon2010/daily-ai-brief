import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import generate_brief
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

    def test_public_dashboard_does_not_expose_private_notion_link(self):
        index = (Path(__file__).resolve().parents[1] / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("app.notion.com", index)

    def test_empty_notion_variables_use_default_data_sources(self):
        src = Path(__file__).resolve().parents[1] / "src"
        env = {**os.environ, "PYTHONPATH": str(src), "NOTION_CONTENT_DATA_SOURCE": "", "NOTION_BRIEF_DATA_SOURCE": ""}
        result = subprocess.run(
            [sys.executable, "-c", "import generate_brief; print(generate_brief.CONTENT_DATA_SOURCE); print(generate_brief.BRIEF_DATA_SOURCE)"],
            capture_output=True,
            check=True,
            env=env,
            text=True,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["dd1bd249-dfcf-46d2-a51a-2797a070af0f", "f9ac323a-8fc0-4abe-9ff4-e92c389dbc33"],
        )

    def test_generator_writes_practical_action_and_archive(self):
        now = dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.timezone.utc)
        item = {
            "id": "agent1",
            "creator": "Creator",
            "focus": ["Agent systems", "Automation"],
            "priority": 3,
            "title": "Build an AI agent workflow",
            "published": "2026-09-15T14:00:00+00:00",
            "source": "https://example.com/agent1",
            "description": "Build a safe agent for a repeated task.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "creators.json").write_text("[]", encoding="utf-8")
            with mock.patch.object(generate_brief, "ROOT", root), mock.patch.object(
                generate_brief, "collect", return_value=([item], [])
            ), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "", "NOTION_TOKEN": ""}):
                brief = generate_brief.generate(now, force=True)

            action = brief["items"][0]["practical_action"]
            self.assertEqual(action["work_area"], "Automation and AI agents")
            self.assertEqual(len(action["steps"]), 3)
            self.assertIn("minutes", action["time_needed"])
            self.assertTrue(action["expected_result"])
            self.assertTrue(action["test"])
            self.assertTrue(action["safety"])

            archive = json.loads((root / "docs" / "data" / "archive.json").read_text(encoding="utf-8"))
            self.assertEqual(archive["briefs"][0]["date"], "2026-09-15")
            self.assertEqual(archive["briefs"][0]["item_count"], 1)
            self.assertEqual(archive["items"][0]["brief_date"], "2026-09-15")
            self.assertEqual(archive["items"][0]["practical_action"]["work_area"], "Automation and AI agents")

    def test_agent_work_has_priority_over_general_data_words(self):
        item = {
            "title": "Build an AI agent that reads data",
            "description": "Use an agent workflow to review sample data.",
            "focus": ["Agent systems", "Automation"],
        }
        self.assertEqual(generate_brief.work_area(item), "Automation and AI agents")

    def test_resume_lesson_creates_an_it_skill_proof(self):
        item = {
            "title": "Write a Better Resume in the AI Era",
            "description": "Links about memory, email, and many other videos.",
            "focus": ["Productivity", "AI education"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["title"], "Write proof of one IT skill")
        self.assertEqual(action["work_area"], "IT operations")

    def test_safety_news_creates_an_approval_review(self):
        item = {
            "title": "AI News: A chance AI kills all humans",
            "description": "",
            "focus": ["Agent systems"],
        }
        self.assertEqual(generate_brief.practical_action(item)["title"], "Add one human approval stop")

    def test_instead_of_agents_creates_a_workflow_choice(self):
        item = {
            "title": "What to Build Instead of AI Agents",
            "description": "",
            "focus": ["Agent systems"],
        }
        self.assertEqual(generate_brief.practical_action(item)["title"], "Choose a workflow or an agent")

    def test_dashboard_search_matches_practical_action(self):
        app = Path(__file__).resolve().parents[1] / "docs" / "app.js"
        script = """
const { filterItems } = require(process.argv[1]);
const items = [
  { brief_date: '2026-09-15', creator: 'Nate Herk', title: 'Agent workflow', topics: ['Automation'], practical_action: { work_area: 'Automation and AI agents', title: 'Plan one safe IT automation', steps: ['Choose one repeated IT task.'] } },
  { brief_date: '2026-09-14', creator: 'Tech With Tim', title: 'SQL lab', topics: ['Coding'], practical_action: { work_area: 'SQL', title: 'Test one query', steps: ['Use a test database.'] } },
  { brief_date: '2026-09-14', creator: 'Nate Herk', title: 'IT checklist', topics: ['Education'], practical_action: { work_area: 'IT operations', title: 'Write a checklist', steps: ['Write three checks.'] } }
];
if (filterItems(items, { query: 'safe automation' }).length !== 1) process.exit(1);
if (filterItems(items, { creator: 'Nate Herk' }).length !== 2) process.exit(2);
if (filterItems(items, { date: '2026-09-14', topic: 'Coding' }).length !== 1) process.exit(3);
"""
        result = subprocess.run(["node", "-e", script, str(app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_archive_upgrades_old_cards_with_a_practical_action(self):
        old_brief = {
            "date": "2026-09-14",
            "editorial_summary": "Old brief.",
            "items": [{
                "id": "old1",
                "creator": "Creator",
                "title": "Keep agent context between tasks",
                "description": "Avoid token limits with a clear handoff.",
                "focus": ["Agent systems"],
                "try_this": "Old generic text.",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            dated_file = data_dir / "2026-09-14.json"
            dated_file.write_text(json.dumps(old_brief), encoding="utf-8")
            generate_brief.update_archive(data_dir)
            saved = json.loads(dated_file.read_text(encoding="utf-8"))
        action = saved["items"][0]["practical_action"]
        self.assertEqual(action["title"], "Build a clean agent handoff")
        self.assertNotEqual(saved["items"][0]["try_this"], "Old generic text.")

    def test_archive_rewrites_old_fallback_summary_in_eli10(self):
        old_brief = {
            "date": "2026-09-14",
            "editorial_summary": "Old brief.",
            "items": [{
                "id": "old2",
                "creator": "Creator",
                "title": "Build a safe agent",
                "description": "Sponsor copy https://example.com followed by a long sales pitch.",
                "focus": ["Agent systems"],
                "summary": "Sponsor copy https://example.com followed by a long sales pitch.",
                "why_it_matters": "Relevant to agent systems.",
                "summary_mode": "source fallback",
                "practical_action": {
                    "work_area": "Automation and AI agents",
                    "title": "Old wrong action",
                    "time_needed": "20 minutes",
                    "steps": ["One.", "Two.", "Three."],
                    "expected_result": "Old result.",
                    "test": "Old test.",
                    "safety": "Old safety.",
                },
            }],
        }
        generate_brief.upgrade_brief_actions(old_brief)
        item = old_brief["items"][0]
        self.assertEqual(item["summary"], "Creator shared a lesson called Build a safe agent.")
        self.assertNotIn("http", item["summary"])
        self.assertEqual(item["why_it_matters"], "This lesson may help with automation and AI agents work.")
        self.assertEqual(item["practical_action"]["title"], "Plan one safe IT automation")

    def test_archive_only_lists_existing_dated_files(self):
        data_dir = Path(__file__).resolve().parents[1] / "docs" / "data"
        archive = json.loads((data_dir / "archive.json").read_text(encoding="utf-8"))
        for brief in archive["briefs"]:
            self.assertTrue((data_dir / f"{brief['date']}.json").is_file())

    def test_notion_archive_uses_dated_dashboard_link(self):
        brief = {
            "date": "2026-09-15",
            "generated_at": "2026-09-15T15:00:00+00:00",
            "editorial_summary": "One useful item.",
            "items": [],
        }
        with mock.patch.object(generate_brief, "notion_request", return_value={}) as request_mock:
            generate_brief.publish_to_notion(brief, "token")
        body = request_mock.call_args.args[2]
        self.assertEqual(
            body["properties"]["Dashboard"]["url"],
            "https://johndeleon2010.github.io/daily-ai-brief/?date=2026-09-15",
        )


if __name__ == "__main__":
    unittest.main()
