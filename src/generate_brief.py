from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PACIFIC = ZoneInfo("America/Los_Angeles")
USER_AGENT = "DailyAIBrief/1.0 (+https://github.com/johndeleon2010/daily-ai-brief)"
NOTION_VERSION = "2025-09-03"
CONTENT_DATA_SOURCE = os.getenv("NOTION_CONTENT_DATA_SOURCE") or "dd1bd249-dfcf-46d2-a51a-2797a070af0f"
BRIEF_DATA_SOURCE = os.getenv("NOTION_BRIEF_DATA_SOURCE") or "f9ac323a-8fc0-4abe-9ff4-e92c389dbc33"
ALLOWED_WORK_AREAS = {"SQL", "Automation and AI agents", "IT operations"}
ACTION_VERSION = 2


def request(url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> bytes:
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml, text/html"}
    if headers:
        merged.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        merged["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def resolve_feed(channel_url: str) -> str:
    if "/channel/" in channel_url:
        channel_id = channel_url.rstrip("/").split("/channel/")[-1].split("/")[0]
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    page = request(channel_url).decode("utf-8", errors="replace")
    rss = re.search(r'<link[^>]+type="application/rss\+xml"[^>]+href="([^"]+)"', page)
    if rss:
        return html.unescape(rss.group(1))
    channel = re.search(r'"channelId":"(UC[^"]+)"', page)
    if not channel:
        raise ValueError(f"YouTube channel ID was not found for {channel_url}")
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel.group(1)}"


def parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_feed(xml_bytes: bytes, creator: dict) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    atom = "{http://www.w3.org/2005/Atom}"
    yt = "{http://www.youtube.com/xml/schemas/2015}"
    media = "{http://search.yahoo.com/mrss/}"
    items = []
    for entry in root.findall(f"{atom}entry"):
        video_id = entry.findtext(f"{yt}videoId") or ""
        title = clean_text(entry.findtext(f"{atom}title") or "Untitled")
        published = parse_timestamp(entry.findtext(f"{atom}published") or entry.findtext(f"{atom}updated"))
        link_node = entry.find(f"{atom}link")
        link = link_node.attrib.get("href", "") if link_node is not None else ""
        description = ""
        group = entry.find(f"{media}group")
        if group is not None:
            description = clean_text(group.findtext(f"{media}description") or "")
        items.append({
            "id": video_id or hashlib.sha256(link.encode()).hexdigest()[:16],
            "creator": creator["name"],
            "focus": creator["focus"],
            "priority": creator["priority"],
            "title": title,
            "published": published.isoformat(),
            "source": link,
            "description": description,
        })
    return items


def collect(creators: list[dict], now: dt.datetime, hours: int = 72) -> tuple[list[dict], list[dict]]:
    cutoff = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=hours)
    items: list[dict] = []
    errors: list[dict] = []
    for creator in creators:
        try:
            feed_url = resolve_feed(creator["youtube"])
            for item in parse_feed(request(feed_url), creator):
                if parse_timestamp(item["published"]) >= cutoff:
                    items.append(item)
        except Exception as exc:
            errors.append({"creator": creator["name"], "error": str(exc)[:240]})
    return items, errors


def work_area(item: dict) -> str:
    text = " ".join([
        item.get("title", ""),
        *item.get("focus", []),
    ]).lower()
    if any(word in text for word in ("agent", "automation", "workflow", "api", "n8n", "mcp", "no code")):
        return "Automation and AI agents"
    if any(word in text for word in ("sql", "database", "query", "sql server", "reporting")):
        return "SQL"
    return "IT operations"


def practical_action(item: dict) -> dict:
    area = work_area(item)
    text = item.get("title", "").lower()
    if "resume" in text or "résumé" in text:
        return {
            "work_area": "IT operations",
            "title": "Write proof of one IT skill",
            "time_needed": "15 minutes",
            "steps": [
                "Choose one SQL, automation, or IT skill you use at work.",
                "Write the problem, your action, and the result.",
                "Add one number that proves the result.",
            ],
            "expected_result": "A short skill example backed by a real result.",
            "test": "Another manager understands what you did and why it helped.",
            "safety": "Remove staff names, account data, and private system details.",
        }
    if "instead of" in text and "agent" in text:
        return {
            "work_area": "Automation and AI agents",
            "title": "Choose a workflow or an agent",
            "time_needed": "20 minutes",
            "steps": [
                "Choose one repeated IT task.",
                "Mark each step as fixed or needing judgment.",
                "Use a simple workflow when every step is fixed. Use an agent only for judgment steps.",
            ],
            "expected_result": "A clear choice between a simple workflow and an AI agent.",
            "test": "Another technician reaches the same choice from your step list.",
            "safety": "Do not build or connect the tool until a person reviews the choice.",
        }
    if "email" in text:
        return {
            "work_area": "Automation and AI agents",
            "title": "Plan a safe email triage flow",
            "time_needed": "20 minutes",
            "steps": [
                "Write three types of IT email using sample text.",
                "Give each type one route and one reply draft.",
                "Add a person to approve every reply before sending.",
            ],
            "expected_result": "A small email routing plan with three sample cases.",
            "test": "Each sample email reaches the correct route and reply draft.",
            "safety": "Use sample email. Do not send a message or use private data.",
        }
    if any(word in text for word in ("token", "context", "memory", "handoff")):
        return {
            "work_area": "Automation and AI agents",
            "title": "Build a clean agent handoff",
            "time_needed": "20 minutes",
            "steps": [
                "Choose one long IT task an agent handles.",
                "Write the facts, work done, and next step the agent must save.",
                "Start a new test chat with only the saved handoff.",
            ],
            "expected_result": "A short handoff template for long agent tasks.",
            "test": "The new chat continues the task without missing a key fact.",
            "safety": "Use sample data. Remove names, passwords, and system secrets.",
        }
    if any(word in text for word in ("safety", "security", "risk", "misuse", "kills", "extinction", "warning", "danger")):
        return {
            "work_area": "Automation and AI agents",
            "title": "Add one human approval stop",
            "time_needed": "15 minutes",
            "steps": [
                "Choose one planned AI or automation task.",
                "Mark the step where a wrong result would cause harm.",
                "Require a named person to approve the result at that step.",
            ],
            "expected_result": "One safer workflow with a clear approval owner.",
            "test": "The workflow stops before any system or data change.",
            "safety": "Do not let an agent change a live system on its own.",
        }
    if any(word in text for word in ("spot ai", "detect ai", "ai content")):
        return {
            "work_area": "IT operations",
            "title": "Write an AI content check",
            "time_needed": "10 minutes",
            "steps": [
                "Choose one sample AI answer about an IT topic.",
                "Check its source, date, and main fact.",
                "Write pass or fail beside each check.",
            ],
            "expected_result": "A three point check for AI written IT content.",
            "test": "Another technician gets the same pass or fail result.",
            "safety": "Treat the AI answer as a draft until a person checks it.",
        }
    if any(word in text for word in ("certification", "course", "training")):
        return {
            "work_area": "IT operations",
            "title": "Turn one lesson into an IT lab",
            "time_needed": "30 minutes",
            "steps": [
                "Choose one skill from the source.",
                "Build one small test using sample data or a test system.",
                "Save the steps and the result as proof of the skill.",
            ],
            "expected_result": "A small working lab with written proof.",
            "test": "Another technician follows the steps and gets the same result.",
            "safety": "Use a test system. Do not make a production change.",
        }
    if area == "SQL":
        return {
            "work_area": area,
            "title": "Test one read only SQL idea",
            "time_needed": "20 minutes",
            "steps": [
                "Choose one slow or repeated report.",
                "Write the result you expect before you run a query.",
                "Run a read only query in a test system and compare the result.",
            ],
            "expected_result": "A tested query with the expected columns and row count.",
            "test": "The query returns the expected columns and rows.",
            "safety": "Use a test database. Do not update or delete data.",
        }
    if area == "Automation and AI agents":
        return {
            "work_area": area,
            "title": "Plan one safe IT automation",
            "time_needed": "30 minutes",
            "steps": [
                "Choose one repeated IT task.",
                "Write the trigger, input, steps, and output.",
                "Mark where a person must approve the result.",
            ],
            "expected_result": "A one page automation plan.",
            "test": "Another technician understands the plan without help.",
            "safety": "Use sample data. Do not connect production systems.",
        }
    return {
        "work_area": area,
        "title": "Improve one IT support step",
        "time_needed": "10 minutes",
        "steps": [
            "Choose one repeated support issue.",
            "Write three checks in the order they should run.",
            "Ask another technician to follow the checks.",
        ],
        "expected_result": "A short troubleshooting checklist.",
        "test": "The technician finishes the checks without extra help.",
        "safety": "Remove names, account numbers, and private data.",
    }


def action_text(action: dict) -> str:
    steps = " ".join(f"Step {index}: {step}" for index, step in enumerate(action["steps"], 1))
    return (
        f"{action['title']} Time: {action['time_needed']}. {steps} "
        f"Result: {action['expected_result']} Test: {action['test']} Safety: {action['safety']}"
    )


def valid_practical_action(action: object) -> bool:
    if not isinstance(action, dict) or action.get("work_area") not in ALLOWED_WORK_AREAS:
        return False
    text_fields = ("title", "time_needed", "expected_result", "test", "safety")
    if any(not isinstance(action.get(field), str) or not action[field].strip() for field in text_fields):
        return False
    steps = action.get("steps")
    return isinstance(steps, list) and len(steps) == 3 and all(isinstance(step, str) and step.strip() for step in steps)


def work_area_text(area: str) -> str:
    return "automation and AI agents" if area == "Automation and AI agents" else area


def deterministic_card(item: dict) -> dict:
    action = practical_action(item)
    title = item["title"].rstrip(".!?")
    return {
        "summary": f"{item['creator']} shared a new lesson called {title}.",
        "why_it_matters": f"This idea may help with {work_area_text(action['work_area'])} work.",
        "practical_action": action,
        "action_version": ACTION_VERSION,
        "try_this": action_text(action),
        "topics": item["focus"],
        "confidence": "Medium",
        "summary_mode": "source fallback",
    }


def ai_card(item: dict, api_key: str) -> dict:
    prompt = {
        "creator": item["creator"],
        "title": item["title"],
        "description": item.get("description", "")[:5000],
        "source": item["source"],
        "work_context": "Use only SQL, automation, AI agent, or IT operations examples. Use sample data. Require a person to approve system changes.",
        "writing_level": "ELI10. Use short words, short sentences, and clear steps.",
        "required_json": {
            "summary": "Two short factual sentences with no hype",
            "why_it_matters": "One short sentence about SQL, automation, AI agents, or IT operations",
            "practical_action": {
                "work_area": "SQL, Automation and AI agents, or IT operations",
                "title": "One clear task",
                "time_needed": "10, 20, or 30 minutes",
                "steps": ["Exactly three short steps"],
                "expected_result": "One clear work product",
                "test": "One check to prove the result works",
                "safety": "One safe limit using sample data and human approval",
            },
            "topics": ["one to three concise topics"],
            "confidence": "High, Medium, or Low",
        },
    }
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        "input": "Return JSON only. Do not claim facts absent from the supplied source metadata.\n" + json.dumps(prompt),
        "text": {"format": {"type": "json_object"}},
    }
    raw = request("https://api.openai.com/v1/responses", method="POST", body=payload, headers={"Authorization": f"Bearer {api_key}"})
    response = json.loads(raw)
    text = response.get("output_text")
    if not text:
        for output in response.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text")
                    break
    card = json.loads(text)
    action = card.get("practical_action")
    if not valid_practical_action(action):
        action = practical_action(item)
        card["practical_action"] = action
    card["try_this"] = action_text(action)
    card["action_version"] = ACTION_VERSION
    card["summary_mode"] = "AI assisted"
    return card


def archive_dashboard_url(date: str) -> str:
    return f"https://johndeleon2010.github.io/daily-ai-brief/?date={date}"


def upgrade_brief_actions(brief: dict) -> bool:
    changed = False
    for item in brief.get("items", []):
        is_fallback = item.get("summary_mode") == "source fallback"
        needs_upgrade = item.get("action_version", 0) < ACTION_VERSION or not valid_practical_action(item.get("practical_action"))
        if needs_upgrade:
            action = practical_action(item)
            try_this = action_text(action)
            if (
                item.get("practical_action") != action
                or item.get("try_this") != try_this
                or item.get("action_version") != ACTION_VERSION
            ):
                item["practical_action"] = action
                item["try_this"] = try_this
                item["action_version"] = ACTION_VERSION
                changed = True
        if is_fallback and needs_upgrade:
            title = item["title"].rstrip(".!?")
            summary = f"{item['creator']} shared a lesson called {title}."
            why = f"This lesson may help with {work_area_text(work_area(item))} work."
            if item.get("summary") != summary or item.get("why_it_matters") != why:
                item["summary"] = summary
                item["why_it_matters"] = why
                changed = True
    return changed


def update_archive(data_dir: Path) -> dict:
    briefs = []
    archive_items = []
    for path in sorted(data_dir.glob("????-??-??.json"), reverse=True):
        brief = json.loads(path.read_text(encoding="utf-8"))
        items = brief.get("items", [])
        changed = upgrade_brief_actions(brief)
        for item in items:
            archive_items.append({
                "brief_date": brief["date"],
                "creator": item["creator"],
                "title": item["title"],
                "published": item.get("published", ""),
                "source": item.get("source", ""),
                "score": item.get("score"),
                "summary": item.get("summary", ""),
                "why_it_matters": item.get("why_it_matters", ""),
                "topics": item.get("topics", item.get("focus", [])),
                "practical_action": item["practical_action"],
            })
        if changed:
            path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        briefs.append({
            "date": brief["date"],
            "editorial_summary": brief.get("editorial_summary", ""),
            "item_count": len(items),
        })
    archive = {"briefs": briefs, "items": archive_items}
    (data_dir / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive


def score(item: dict, now: dt.datetime) -> int:
    age_hours = max(0, (now.astimezone(dt.timezone.utc) - parse_timestamp(item["published"])).total_seconds() / 3600)
    freshness = max(0, 55 - int(age_hours))
    return min(100, freshness + item["priority"] * 12 + min(9, len(item.get("description", "")) // 300))


def select_items(items: list[dict], now: dt.datetime, limit: int = 10) -> list[dict]:
    unique = {item["id"]: item for item in items}
    ranked = sorted(unique.values(), key=lambda item: (score(item, now), item["published"]), reverse=True)
    selected = []
    counts: dict[str, int] = {}
    for item in ranked:
        if counts.get(item["creator"], 0) >= 2:
            continue
        item["score"] = score(item, now)
        selected.append(item)
        counts[item["creator"]] = counts.get(item["creator"], 0) + 1
        if len(selected) == limit:
            break
    return selected


def notion_request(path: str, token: str, body: dict) -> dict:
    raw = request(
        "https://api.notion.com" + path,
        method="POST",
        body=body,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
    )
    return json.loads(raw)


def notion_exists(data_source: str, token: str, property_name: str, value: str) -> bool:
    result = notion_request(f"/v1/data_sources/{data_source}/query", token, {"filter": {"property": property_name, "url": {"equals": value}}, "page_size": 1})
    return bool(result.get("results"))


def rich_text(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": value[:1900]}}]}


def publish_to_notion(brief: dict, token: str) -> None:
    for item in brief["items"]:
        if notion_exists(CONTENT_DATA_SOURCE, token, "Source", item["source"]):
            continue
        notion_request("/v1/pages", token, {
            "parent": {"type": "data_source_id", "data_source_id": CONTENT_DATA_SOURCE},
            "properties": {
                "Item": {"title": [{"text": {"content": item["title"][:150]}}]},
                "Creator Name": rich_text(item["creator"]),
                "Published": {"date": {"start": item["published"]}},
                "Source": {"url": item["source"]},
                "Summary": rich_text(item["summary"]),
                "Why It Matters": rich_text(item["why_it_matters"]),
                "Try This": rich_text(item["try_this"]),
                "Score": {"number": item["score"]},
                "Confidence": {"select": {"name": item["confidence"]}},
                "Status": {"status": {"name": "Done"}},
                "Fingerprint": rich_text(item["id"]),
            },
        })
        time.sleep(0.4)
    notion_request("/v1/pages", token, {
        "parent": {"type": "data_source_id", "data_source_id": BRIEF_DATA_SOURCE},
        "properties": {
            "Brief": {"title": [{"text": {"content": f"Daily AI Brief {brief['date']}"}}]},
            "Brief Date": {"date": {"start": brief["date"]}},
            "Editorial Summary": rich_text(brief["editorial_summary"]),
            "Status": {"status": {"name": "Done"}},
            "Published At": {"date": {"start": brief["generated_at"]}},
            "Item Count": {"number": len(brief["items"])},
            "Dashboard": {"url": archive_dashboard_url(brief["date"])},
        },
    })


def should_run(now: dt.datetime, force: bool) -> bool:
    local = now.astimezone(PACIFIC)
    return force or (local.weekday() < 5 and local.hour == 7)


def generate(now: dt.datetime, force: bool = False) -> dict:
    if not should_run(now, force):
        return {"skipped": True, "reason": "Outside the weekday 7 AM Pacific execution window"}
    creators = json.loads((ROOT / "creators.json").read_text(encoding="utf-8"))
    items, errors = collect(creators, now)
    selected = select_items(items, now)
    api_key = os.getenv("OPENAI_API_KEY", "")
    cards = []
    for item in selected:
        try:
            card = ai_card(item, api_key) if api_key else deterministic_card(item)
        except Exception as exc:
            card = deterministic_card(item)
            card["summary_error"] = str(exc)[:180]
        cards.append({**item, **card})
    local_date = now.astimezone(PACIFIC).date().isoformat()
    brief = {
        "date": local_date,
        "generated_at": now.astimezone(dt.timezone.utc).isoformat(),
        "timezone": "America/Los_Angeles",
        "editorial_summary": f"{len(cards)} high signal items from {len({x['creator'] for x in cards})} creators.",
        "items": cards,
        "source_errors": errors,
    }
    data_dir = ROOT / "docs" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(brief, ensure_ascii=False, indent=2) + "\n"
    (data_dir / "latest.json").write_text(rendered, encoding="utf-8")
    (data_dir / f"{local_date}.json").write_text(rendered, encoding="utf-8")
    update_archive(data_dir)
    token = os.getenv("NOTION_TOKEN", "")
    if token:
        publish_to_notion(brief, token)
    return brief


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = generate(dt.datetime.now(dt.timezone.utc), force=args.force)
        print(json.dumps({"skipped": result.get("skipped", False), "items": len(result.get("items", [])), "errors": len(result.get("source_errors", []))}))
        return 0
    except (urllib.error.URLError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"Daily brief failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
