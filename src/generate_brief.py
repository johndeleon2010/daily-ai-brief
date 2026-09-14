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
CONTENT_DATA_SOURCE = os.getenv("NOTION_CONTENT_DATA_SOURCE", "dd1bd249-dfcf-46d2-a51a-2797a070af0f")
BRIEF_DATA_SOURCE = os.getenv("NOTION_BRIEF_DATA_SOURCE", "f9ac323a-8fc0-4abe-9ff4-e92c389dbc33")


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


def deterministic_card(item: dict) -> dict:
    description = item.get("description", "")
    summary = description[:340].rsplit(" ", 1)[0] if len(description) > 340 else description
    if not summary:
        summary = f"New video published: {item['title']}"
    return {
        "summary": summary,
        "why_it_matters": f"Relevant to {', '.join(item['focus']).lower()}.",
        "try_this": "Review the source and capture one testable idea before adopting the recommendation.",
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
        "required_json": {
            "summary": "Two factual sentences, no hype",
            "why_it_matters": "One sentence for an experienced IT manager or AI automation consultant",
            "try_this": "One small, safe action",
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
    card["summary_mode"] = "AI assisted"
    return card


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
    data_dir.mkdir(exist_ok=True)
    rendered = json.dumps(brief, ensure_ascii=False, indent=2) + "\n"
    (data_dir / "latest.json").write_text(rendered, encoding="utf-8")
    (data_dir / f"{local_date}.json").write_text(rendered, encoding="utf-8")
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
