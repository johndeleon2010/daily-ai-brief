import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
    def test_delivery_feed_contains_dated_brief_link(self):
        brief = {
            "date": "2026-09-17",
            "generated_at": "2026-09-17T14:05:00+00:00",
            "editorial_summary": "10 high signal items from 8 creators.",
            "items": [{}] * 10,
        }
        root = ET.fromstring(generate_brief.delivery_feed(brief))
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("title"), "Daily AI Brief 2026-09-17")
        self.assertEqual(
            item.findtext("link"),
            "https://johndeleon2010.github.io/daily-ai-brief/?date=2026-09-17",
        )
        self.assertIn("10 high signal items", item.findtext("description"))

    def test_parse_feed_preserves_source(self):
        creator = {"name": "Creator", "focus": ["Agents"], "priority": 3}
        item = parse_feed(FEED, creator)[0]
        self.assertEqual(item["id"], "abc123")
        self.assertEqual(item["source"], "https://youtu.be/abc123")

    def test_selection_deduplicates_and_limits_creator(self):
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)
        base = {"creator": "A", "focus": ["Agents"], "priority": 3, "published": "2026-09-14T12:00:00+00:00", "description": "This source explains an agent test with clear sample data. It compares the first result with a checked result."}
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

    def test_browser_delivery_waits_for_todays_brief_and_runs_interactively(self):
        root = Path(__file__).resolve().parents[1]
        opener = (root / "delivery" / "Open-DailyAIBrief.ps1").read_text(encoding="utf-8")
        installer = (root / "delivery" / "Install-DailyAIBriefBrowserTask.ps1").read_text(encoding="utf-8")
        self.assertIn("data/latest.json", opener)
        self.assertIn("$brief.date -eq $today", opener)
        self.assertIn("Start-Process", opener)
        self.assertIn("[string]$DataPath", opener)
        self.assertIn("[switch]$NoOpen", opener)
        self.assertIn("-StartWhenAvailable", installer)
        self.assertIn("-LogonType Interactive", installer)
        self.assertIn("-At \"07:30\"", installer)
        self.assertIn("$task.Settings.StartWhenAvailable", installer)
        self.assertIn("$task.Actions[0].Arguments", installer)
        self.assertIn("$task.Principal.UserId", installer)

    def test_workflow_starts_at_seven_and_publishes_delivery_feed(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-brief.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 14 * * 1-5"', workflow)
        self.assertIn('cron: "0 15 * * 1-5"', workflow)
        self.assertNotIn('cron: "30 14 * * 1-5"', workflow)
        self.assertIn("git add docs/data docs/feed.xml", workflow)

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

    def test_generator_writes_article_summary_takeaways_and_action(self):
        now = dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.timezone.utc)
        item = {
            "id": "agent1",
            "creator": "Creator",
            "focus": ["Agent systems", "Automation"],
            "priority": 3,
            "title": "Build an AI agent workflow with a planning loop",
            "published": "2026-09-15T14:00:00+00:00",
            "source": "https://example.com/agent1",
            "description": "You'll learn how to plan the goal with a short brief, run the agent on a sample task, and review the result before the next step.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "creators.json").write_text("[]", encoding="utf-8")
            with mock.patch.object(generate_brief, "ROOT", root), mock.patch.object(
                generate_brief, "collect", return_value=([item], [])
            ), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "", "NOTION_TOKEN": ""}):
                brief = generate_brief.generate(now, force=True)

            card = brief["items"][0]
            action = card["practical_action"]
            self.assertTrue(card["summary"])
            self.assertEqual(len(card["key_takeaways"]), 3)
            self.assertEqual(action["action_type"], "Hands on task")
            self.assertIn("planning loop", action["article_basis"].lower())
            self.assertEqual(len(action["steps"]), 3)
            self.assertIn("plan the goal", action["steps"][0].lower())
            self.assertIn("run the agent", action["steps"][1].lower())
            self.assertIn("review the result", action["steps"][2].lower())
            self.assertIn("minutes", action["time_needed"])
            self.assertTrue(action["expected_result"])
            self.assertTrue(action["test"])
            self.assertTrue(action["safety"])

            archive = json.loads((root / "docs" / "data" / "archive.json").read_text(encoding="utf-8"))
            self.assertEqual(archive["briefs"][0]["date"], "2026-09-15")
            self.assertEqual(archive["briefs"][0]["item_count"], 1)
            self.assertEqual(archive["items"][0]["brief_date"], "2026-09-15")
            self.assertEqual(len(archive["items"][0]["key_takeaways"]), 3)
            self.assertEqual(archive["items"][0]["practical_action"]["action_type"], "Hands on task")
            feed = ET.parse(root / "docs" / "feed.xml").getroot()
            self.assertEqual(feed.findtext("./channel/item/title"), "Daily AI Brief 2026-09-15")

    def test_action_follows_the_article_instead_of_forcing_it_work(self):
        item = {
            "title": "Write a Better Resume with a proof table",
            "description": "List each skill beside one result and one number that proves it.",
            "focus": ["Careers", "AI education"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["action_type"], "Hands on task")
        self.assertIn("resume", action["article_basis"].lower())
        self.assertIn("one number that proves it", action["article_basis"].lower())
        self.assertNotIn("IT skill", generate_brief.action_text(action))

    def test_non_actionable_article_creates_a_small_experiment(self):
        item = {
            "title": "What AI may look like next year",
            "description": "A discussion about several possible futures.",
            "focus": ["AI news"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["action_type"], "Small experiment")
        self.assertIn("AI may look like next year", action["article_basis"])

    def test_news_stays_a_small_experiment_when_description_has_action_words(self):
        item = {
            "title": "AI News in 10 Minutes",
            "description": "The host explains recent safety reports and says people should use AI with care.",
            "focus": ["AI news"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["action_type"], "Small experiment")
        self.assertEqual(action["title"], "Check one news claim from the source")
        self.assertIn("original evidence", action["expected_result"])

    def test_spot_ai_article_gets_a_source_specific_experiment(self):
        item = {
            "title": "How To Spot AI Content",
            "description": "AI video models are harder to tell from real video.",
            "focus": ["AI video"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["action_type"], "Small experiment")
        self.assertEqual(action["title"], "Compare real and AI made content")
        self.assertIn("two real images", action["steps"][0])

    def test_certification_article_builds_the_project_it_recommends(self):
        item = {
            "title": "Don't Just Collect AI Certifications, Do This Instead",
            "description": "Start with one certification, then add one deployed project on top.",
            "focus": ["Careers"],
        }
        action = generate_brief.practical_action(item)
        self.assertEqual(action["title"], "Pair one lesson with one small project")
        self.assertIn("proves the lesson works", action["steps"][1])

    def test_ai_prompt_requires_an_article_based_task(self):
        item = {
            "creator": "Creator",
            "title": "Use a prompt chain to compare product photos",
            "description": "Create three prompts. Keep the best result.",
            "source": "https://example.com/source",
            "focus": ["Images"],
        }
        response = {
            "output_text": json.dumps({
                "summary": "This source explains a prompt chain for product photos.",
                "key_takeaways": ["Use three prompts.", "Compare each result.", "Keep the best result."],
                "why_it_matters": "The method makes prompt tests easier to compare.",
                "practical_action": {
                    "action_type": "Hands on task",
                    "article_basis": "This task uses the three prompt comparison method.",
                    "title": "Compare three photo prompts",
                    "time_needed": "20 minutes",
                    "steps": ["Write three prompts.", "Run each prompt.", "Keep the best result."],
                    "expected_result": "Three results and one selected image.",
                    "test": "The same rule was used to compare all three results.",
                    "safety": "Use sample product data.",
                },
                "topics": ["Images", "Prompting"],
                "confidence": "High",
            })
        }
        with mock.patch.object(generate_brief, "request", return_value=json.dumps(response).encode()) as request_mock:
            card = generate_brief.ai_card(item, "test-key")
        prompt = request_mock.call_args.kwargs["body"]["input"]
        self.assertIn("Adapt the source method into a hands on task", prompt)
        self.assertIn("Do not force it into the reader's job", prompt)
        self.assertEqual(card["practical_action"]["title"], "Compare three photo prompts")

    def test_source_summary_skips_promotional_copy(self):
        item = {
            "creator": "Creator",
            "title": "Build a four agent review team",
            "description": (
                "Sign up for a paid plan and get bonus credits. "
                "The four agents research the company, check risk, make three ideas, and build one review deck. "
                "Use code SAVE10 for a discount."
            ),
        }
        content = generate_brief.article_content(item)
        joined = " ".join([content["summary"], *content["key_takeaways"]]).lower()
        self.assertIn("four agents research the company", joined)
        self.assertNotIn("bonus credits", joined)
        self.assertNotIn("discount", joined)

    def test_selection_skips_a_card_without_enough_source_detail(self):
        now = dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.timezone.utc)
        item = {
            "id": "empty", "creator": "Creator", "focus": ["AI"], "priority": 3,
            "title": "Office Hours Q and A", "published": "2026-09-15T14:00:00+00:00",
            "source": "https://example.com/empty", "description": "",
        }
        self.assertEqual(select_items([item], now), [])

    def test_archive_index_keeps_a_historical_card_without_source_detail(self):
        brief = {
            "date": "2026-09-15", "editorial_summary": "Saved brief.",
            "items": [{
                "id": "empty", "creator": "Creator", "title": "Office Hours Q and A",
                "published": "2026-09-15T14:00:00+00:00", "source": "https://example.com/empty",
                "description": "", "focus": ["AI"],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "2026-09-15.json").write_text(json.dumps(brief), encoding="utf-8")
            archive = generate_brief.update_archive(data_dir)
        self.assertEqual(archive["briefs"][0]["item_count"], 1)
        self.assertEqual(len(archive["items"]), 1)
        self.assertTrue(archive["items"][0]["summary"])

    def test_archive_uses_new_key_paragraph_without_rewriting_history(self):
        brief = {
            "date": "2026-09-15", "editorial_summary": "Saved brief.",
            "items": [{
                "id": "resume", "creator": "Creator", "title": "Write a Better Résumé",
                "published": "2026-09-15T14:00:00+00:00", "source": "https://example.com/resume",
                "description": "Make the résumé easy for hiring software to read. Add one measured result to each work example.",
                "focus": ["Careers"], "summary": "Old one line summary.",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            path = data_dir / "2026-09-15.json"
            path.write_text(json.dumps(brief), encoding="utf-8")
            archive = generate_brief.update_archive(data_dir)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotEqual(archive["items"][0]["summary"], "Old one line summary.")
        self.assertEqual(saved, brief)

    def test_fruit_fly_article_gets_an_accessible_agent_comparison(self):
        item = {"title": "I Uploaded A Fruit Fly Brain To Reply To My Emails", "description": "", "focus": ["Agents"]}
        action = generate_brief.practical_action(item)
        self.assertEqual(action["title"], "Compare a general agent with one small specialist")
        self.assertIn("made up email", action["steps"][0])

    def test_known_title_has_three_grounded_takeaways(self):
        item = {"creator": "Ben AI", "title": "Paste This Into Claude, Never Hit a Token Limit Again", "description": ""}
        content = generate_brief.article_content(item)
        self.assertEqual(len(content["key_takeaways"]), 3)
        self.assertIn("saved handoff", content["key_takeaways"][2])

    def test_office_hours_archive_card_has_useful_source_points(self):
        item = {"creator": "Liam Ottley", "title": "Office Hours: Answering Your AI-for-Business Questions (Free Q&A)", "description": ""}
        content = generate_brief.article_content(item)
        self.assertIn("audience questions", content["summary"])
        self.assertEqual(len(content["key_takeaways"]), 3)

    def test_action_basis_rewrites_complex_source_terms(self):
        item = {
            "title": "Write a Better Résumé",
            "description": "Make an #ATS-friendly résumé without keyword stuffing. Add one measured result to each work example.",
            "focus": ["Careers"],
        }
        basis = generate_brief.practical_action(item)["article_basis"]
        self.assertNotIn("ATS-friendly", basis)
        self.assertNotIn("keyword stuffing", basis)

    def test_chatgpt_work_article_gets_a_feature_test(self):
        item = {"title": "GPT-6 Astra + ChatGPT Work Changes Everything", "description": "", "focus": ["AI"]}
        action = generate_brief.practical_action(item)
        self.assertEqual(action["title"], "Test one feature shown in the source")
        self.assertIn("file review", action["steps"][0])

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

    def test_archive_does_not_rewrite_a_historical_brief(self):
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
        self.assertEqual(saved, old_brief)

    def test_archive_upgrades_old_cards_to_article_based_content(self):
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
        self.assertTrue(item["summary"])
        self.assertNotIn("http", item["summary"])
        self.assertEqual(len(item["key_takeaways"]), 3)
        self.assertIn(item["practical_action"]["action_type"], {"Hands on task", "Small experiment"})
        self.assertIn("Build a safe agent", item["practical_action"]["article_basis"])

    def test_dashboard_places_summary_and_takeaways_under_title(self):
        app = Path(__file__).resolve().parents[1] / "docs" / "app.js"
        script = """
const { cardMarkup } = require(process.argv[1]);
const html = cardMarkup({
  creator: 'Creator', title: 'Source title', published: '2026-09-15T14:00:00Z',
  summary: 'Key paragraph.', key_takeaways: ['One.', 'Two.', 'Three.'], topics: ['AI'], source: 'https://example.com',
  practical_action: { action_type: 'Hands on task', article_basis: 'Source method.', title: 'Try it', time_needed: '10 minutes', steps: ['A.', 'B.', 'C.'], expected_result: 'Result.', test: 'Test.', safety: 'Safety.' }
}, 0);
const positions = ['Source title', 'Key paragraph.', 'Three takeaways', 'Try this'].map(value => html.indexOf(value));
if (positions.some(value => value < 0)) process.exit(1);
if (!positions.every((value, index) => index === 0 || positions[index - 1] < value)) process.exit(2);
if ((html.match(/<li>/g) || []).length !== 6) process.exit(3);
"""
        result = subprocess.run(["node", "-e", script, str(app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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
