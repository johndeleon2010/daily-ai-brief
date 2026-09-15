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
ACTION_TYPES = {"Hands on task", "Small experiment"}
ACTION_VERSION = 12


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


def source_sentences(item: dict) -> list[str]:
    description = re.sub(r"https?://\S+", "", clean_text(item.get("description", "")))
    description = re.sub(r"\b(?:claim yours here|get it here|learn more here)\s*:\s*", "", description, flags=re.I)
    sentences = [part.strip(" .") for part in re.split(r"(?<=[.!?])\s+|\s*[|•]\s*", description)]
    noise = (
        "sponsored by", "subscribe", "affiliate", "use code", "discount", "bonus credits",
        "sign up", "paid plan", "contact me", "newsletter", "free resources", "join my", "get 1%",
        "want to learn", "tools i use", "go here", "get 10%", "sponsorship inquiries",
        "we make no guarantees", "about me", "my family", "i grew up", "follow me",
        "if you’re serious", "if you're serious", "ecosystem", "ai-first business here",
        "i built two", "i help professionals", "my ai agency", "due diligence",
        "show you exactly how",
        "analysis & thoughts", "media license", "terms of service", "not intended as legal",
        "i believe anyone", "you don't need to be technical", "you do not need to be technical",
        "feeling overwhelmed", "as for my path", "started my first business", "pay my bills",
        "licensed attorney", "licensed cpa", "i make videos", "tutorials you can follow",
        "starting my journey", "grown a fair bit of capital",
    )
    title_words = set(re.findall(r"[a-z0-9]+", item.get("title", "").lower())) - {
        "a", "an", "and", "for", "from", "how", "i", "in", "of", "the", "this", "to", "with",
    }
    ranked = []
    for index, sentence in enumerate(sentences):
        words = sentence.split()
        lowered = sentence.lower()
        if not 6 <= len(words) <= 70 or any(term in lowered for term in noise) or re.search(r"\b\d{1,2}:\d{2}\b", sentence):
            continue
        overlap = len(title_words & set(re.findall(r"[a-z0-9]+", lowered)))
        method_words = sum(word in lowered for word in ("build", "create", "show", "learn", "method", "step", "use", "compare", "review", "start", "add", "deploy", "apply"))
        ranked.append((overlap * 3 + method_words, -index, sentence))
    ranked.sort(reverse=True)
    return [sentence for _, _, sentence in ranked[:3]]


def short_source_text(value: str, limit: int = 28) -> str:
    replacements = {
        "#": "",
        "an ATS-friendly résumé": "a résumé that hiring software can read",
        "ATS-friendly": "easy for hiring software to read",
        "keyword stuffing": "repeating key words too often",
        "Anthropic’s misuse report": "Anthropic report about harmful use",
        "Dario Amodei’s plan to slow the race": "a plan to slow AI work",
        "Trump’s response": "the US government response",
        "economically valuable": "useful",
        "utilize": "use",
        "leveraging": "using",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    words = value.split()
    if len(words) <= limit:
        return " ".join(words).rstrip(" ,;:")
    shortened = " ".join(words[:limit])
    clause_end = max(shortened.rfind(","), shortened.rfind(";"), shortened.rfind(":"))
    if clause_end > len(shortened) // 3:
        shortened = shortened[:clause_end]
    return shortened.rstrip(" ,;:")


def source_kind(title: str) -> str:
    title = title.lower()
    if "gpt-6 astra" in title and "chatgpt work" in title:
        return "chatgpt_work"
    if "office hours" in title and "ai-for-business" in title:
        return "business_qa"
    for kind, terms in (
        ("token_limit", ("claude", "token limit")),
        ("command_center", ("claude", "command center")),
        ("fruit_fly", ("fruit fly brain",)),
        ("resume", ("resume", "résumé")),
        ("news", ("news",)),
        ("four_agents", ("4 ai agents", "four ai agents")),
        ("spot_ai", ("spot ai", "detect ai")),
    ):
        if kind in {"token_limit", "command_center"} and all(term in title for term in terms):
            return kind
        if kind not in {"token_limit", "command_center"} and any(term in title for term in terms):
            return kind
    return ""


def article_content(item: dict) -> dict:
    title = item["title"].rstrip(".!?")
    kind = source_kind(title)
    if kind == "token_limit":
        return {
            "summary": f"{item['creator']} shares a prompt for Claude. The prompt is meant to help a long task continue when a chat reaches its token limit.",
            "key_takeaways": [
                "The source gives you text to paste into Claude.",
                "The goal is to save the key facts before the chat fills up.",
                "A new chat should continue from the saved handoff.",
            ],
        }
    if kind == "command_center":
        return {
            "summary": f"{item['creator']} shows a Claude command center that uses no code. The source says the setup takes about 15 minutes.",
            "key_takeaways": [
                "The project puts Claude work in one command center.",
                "The setup uses no code.",
                "The source aims for a 15 minute setup.",
            ],
        }
    if kind == "chatgpt_work":
        return {
            "summary": f"{item['creator']} reviews GPT-6 Astra and ChatGPT Work. The video covers file review, writing, coding, voice, price, and usage.",
            "key_takeaways": [
                "The source shows how the tools review files.",
                "It covers writing and coding tasks.",
                "It also reviews voice, price, and usage.",
            ],
        }
    if kind == "fruit_fly":
        return {
            "summary": f"{item['creator']} tests a fruit fly brain model with GPT-6 Astra. The goal is to see whether the model can help reply to email.",
            "key_takeaways": [
                "The test uses a fruit fly brain model.",
                "GPT-6 Astra changes the model for a useful task.",
                "The example task is replying to email.",
            ],
        }
    if kind == "business_qa":
        return {
            "summary": f"{item['creator']} answers audience questions about using AI in a business. The video uses a question and answer format instead of one fixed lesson.",
            "key_takeaways": [
                "The topic is using AI in a business.",
                "The video answers questions from the audience.",
                "Each answer may use a different method.",
            ],
        }
    sentences = source_sentences(item)
    method_steps = source_method_steps(item)
    if len(sentences) < 2 and len(method_steps) == 3:
        sentences = method_steps
    summary = f"{item['creator']} explains {title}."
    if sentences:
        summary += " The source focuses on " + short_source_text(sentences[0]).rstrip(".") + "."
    takeaways = [f"The main topic is {title}."]
    takeaways.extend(f"The source says: {short_source_text(sentence, 22)}." for sentence in sentences[:2])
    while len(takeaways) < 3:
        fill = (
            "Open the source to check the full method and examples."
            if len(takeaways) == 1
            else "Test the idea on a small example before using it more widely."
        )
        takeaways.append(fill)
    return {"summary": summary, "key_takeaways": takeaways[:3]}


def has_grounded_content(item: dict) -> bool:
    return bool(source_kind(item.get("title", ""))) or len(source_sentences(item)) >= 2 or len(source_method_steps(item)) == 3


def source_method_steps(item: dict) -> list[str]:
    candidates = []
    for sentence in source_sentences(item):
        lowered = sentence.lower()
        method = sentence
        for marker in ("you'll learn how to ", "had already ", "the move that actually works: ", "the move that works: "):
            position = lowered.find(marker)
            if position >= 0:
                method = sentence[position + len(marker):]
                break
        parts = re.split(r",\s+(?:and\s+)?|\s+and\s+(?=[a-z]+\s)", method)
        for part in parts:
            part = re.sub(r"^(?:my ai agents|the agents|you)\s+", "", part.strip(), flags=re.I)
            if len(part.split()) >= 3 and re.match(
                r"^(?:make|tailor|use|turn|write|build|create|plan|research|researched|run|ran|check|checked|generate|generated|wrap|wrapped|add|review|compare|test|start|deploy)",
                part,
                flags=re.I,
            ):
                candidates.append(short_source_text(part, 22).rstrip("."))
    unique = []
    for candidate in candidates:
        if candidate.lower() not in {step.lower() for step in unique}:
            unique.append(candidate)
    past_to_present = {
        "Researched ": "Research ",
        "Generated ": "Generate ",
        "Wrapped ": "Wrap ",
        "Checked ": "Check ",
        "Ran ": "Run ",
    }
    steps = []
    for step in unique[:3]:
        step = step[0].upper() + step[1:]
        for past, present in past_to_present.items():
            if step.startswith(past):
                step = present + step[len(past):]
                break
        steps.append(step + ".")
    return steps


def practical_action(item: dict) -> dict:
    title = item["title"].rstrip(".!?")
    kind = source_kind(title)
    source_points = source_sentences(item)
    basis = (
        f'This task uses the method from "{title}": {short_source_text(source_points[0], 24)}.'
        if source_points
        else f'This task uses the main idea from "{title}".'
    )
    if kind == "resume":
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": "Apply the source rules to one résumé entry",
            "time_needed": "20 minutes",
            "steps": [
                "Choose one job listing and one matching résumé entry.",
                "Rewrite the entry with one clear action and one measured result.",
                "Check that the wording is true and easy for hiring software to read.",
            ],
            "expected_result": "One clear résumé entry that matches the source rules.",
            "test": "The entry names your action, result, and a true number when one exists.",
            "safety": "Do not add a skill, result, or number you cannot prove.",
        }
    if kind == "news":
        return {
            "action_type": "Small experiment",
            "article_basis": basis,
            "title": "Check one news claim from the source",
            "time_needed": "15 minutes",
            "steps": [
                "Choose one claim from the source.",
                "Find the report, study, or company post behind the claim.",
                "Mark the claim as supported, unclear, or wrong. Save the source link.",
            ],
            "expected_result": "One checked claim with a link to the original evidence.",
            "test": "The evidence comes from the group that made the report or announcement.",
            "safety": "Do not repeat a serious claim as fact until the evidence supports it.",
        }
    if kind == "four_agents":
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": "Test a four role agent team",
            "time_needed": "30 minutes",
            "steps": [
                "Give one agent a made up company to research.",
                "Ask a second agent to check facts, private data, access, and cost. Ask a third agent for three ideas.",
                "Ask a fourth agent to put the results in one short review page.",
            ],
            "expected_result": "One review page built from four clear agent roles.",
            "test": "The page shows the research, risk check, three ideas, and final review.",
            "safety": "Use a made up company. Do not let an agent contact anyone or spend money.",
        }
    if kind == "spot_ai":
        return {
            "action_type": "Small experiment",
            "article_basis": basis,
            "title": "Compare real and AI made content",
            "time_needed": "15 minutes",
            "steps": [
                "Choose two real images and two AI made images.",
                "Write the signs you used to judge each image.",
                "Check each source. Count how many choices were right.",
            ],
            "expected_result": "A short list of signs that helped and signs that failed.",
            "test": "You checked the real source for all four images.",
            "safety": "Use public sample images. Do not label a person or their work without proof.",
        }
    if kind == "token_limit":
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": "Test the source prompt in a new chat",
            "time_needed": "20 minutes",
            "steps": [
                "Copy the prompt from the source into a new test chat.",
                "Give the chat a long sample task with several facts and steps.",
                "Start a second chat with its saved handoff. Check which facts remain.",
            ],
            "expected_result": "A saved handoff that carries the key facts into a new chat.",
            "test": "The second chat states the goal, work done, and next step correctly.",
            "safety": "Use made up facts. Do not paste private work data into the test.",
        }
    if kind == "command_center":
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": "Build the small command center from the source",
            "time_needed": "20 minutes",
            "steps": [
                "Follow the source with a blank test workspace.",
                "Add three sample tasks and one sample reference file.",
                "Use the command center to find one task and its reference.",
            ],
            "expected_result": "A small command center with sample work only.",
            "test": "You find the right task and reference without searching outside the command center.",
            "safety": "Use sample content. Do not connect work accounts or private files.",
        }
    if kind == "fruit_fly":
        return {
            "action_type": "Small experiment",
            "article_basis": basis,
            "title": "Compare a general agent with one small specialist",
            "time_needed": "20 minutes",
            "steps": [
                "Write one made up email that needs a short reply.",
                "Ask one general agent and one email reply agent to answer it.",
                "Compare accuracy, tone, and missing facts. Save the better reply.",
            ],
            "expected_result": "Two sample replies and one clear reason for the better choice.",
            "test": "Both agents received the same email and the same reply rules.",
            "safety": "Use a made up email. Do not send either reply.",
        }
    if kind == "chatgpt_work":
        return {
            "action_type": "Small experiment",
            "article_basis": basis,
            "title": "Test one feature shown in the source",
            "time_needed": "20 minutes",
            "steps": [
                "Choose file review, writing, coding, or voice from the source.",
                "Run one small test with a sample file or made up prompt.",
                "Compare the result with your normal way of doing the same task.",
            ],
            "expected_result": "One saved example showing where the feature helped or failed.",
            "test": "You used the same sample and goal for both results.",
            "safety": "Use sample content. Do not upload private files.",
        }
    if "certification" in title.lower() and "project" in " ".join(source_points).lower():
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": "Pair one lesson with one small project",
            "time_needed": "30 minutes",
            "steps": [
                "Choose one lesson from a certification you already started.",
                "Build one small sample that proves the lesson works.",
                "Save the sample, result, and three steps needed to repeat it.",
            ],
            "expected_result": "One small project that proves a skill instead of only naming a certificate.",
            "test": "Another person follows your three steps and gets the same result.",
            "safety": "Use sample data and a test account.",
        }
    method_steps = source_method_steps(item)
    if len(method_steps) == 3:
        return {
            "action_type": "Hands on task",
            "article_basis": basis,
            "title": f"Try the method from {title}",
            "time_needed": "20 minutes",
            "steps": method_steps,
            "expected_result": "One small result made with the article method.",
            "test": "Your steps match the source, and you saved one clear result.",
            "safety": "Use a small sample. Stop before the test affects people, money, accounts, or live systems.",
        }
    idea_step = (
        f"Test this source idea with a small example: {short_source_text(source_points[0], 36)}."
        if source_points
        else "Open the source. Choose one claim you want to check."
    )
    return {
        "action_type": "Small experiment",
        "article_basis": basis,
        "title": f"Test one idea from {title}",
        "time_needed": "15 minutes",
        "steps": [
            "Write what you expect to happen.",
            idea_step,
            "Compare what happened with what you expected. Save one finding.",
        ],
        "expected_result": "One small test showing whether the article idea helped.",
        "test": "You recorded the expected result, the real result, and one lesson.",
        "safety": "Use a small sample. Do not treat one test as final proof.",
    }


def action_text(action: dict) -> str:
    steps = " ".join(f"Step {index}: {step}" for index, step in enumerate(action["steps"], 1))
    return (
        f"{action['action_type']}. {action['article_basis']} {action['title']} "
        f"Time: {action['time_needed']}. {steps} "
        f"Result: {action['expected_result']} Test: {action['test']} Safety: {action['safety']}"
    )


def valid_practical_action(action: object) -> bool:
    if not isinstance(action, dict) or action.get("action_type") not in ACTION_TYPES:
        return False
    text_fields = ("article_basis", "title", "time_needed", "expected_result", "test", "safety")
    if any(not isinstance(action.get(field), str) or not action[field].strip() for field in text_fields):
        return False
    steps = action.get("steps")
    return isinstance(steps, list) and len(steps) == 3 and all(isinstance(step, str) and step.strip() for step in steps)


def deterministic_card(item: dict) -> dict:
    action = practical_action(item)
    content = article_content(item)
    return {
        **content,
        "why_it_matters": content["key_takeaways"][0],
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
        "action_rule": "Adapt the source method into a hands on task. Do not force it into the reader's job. If the source has no clear method, create one small experiment based on its main idea.",
        "writing_level": "ELI10. Use short words, short sentences, and clear steps. Do not add facts absent from the source metadata.",
        "required_json": {
            "summary": "One useful paragraph about the source, two or three short factual sentences",
            "key_takeaways": ["Exactly three short takeaways grounded in the source"],
            "why_it_matters": "One short sentence grounded in the source",
            "practical_action": {
                "action_type": "Hands on task or Small experiment",
                "article_basis": "One sentence naming the source idea used for this task",
                "title": "One clear task based on the source method or idea",
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
    fallback = deterministic_card(item)
    if not isinstance(card.get("summary"), str) or not card["summary"].strip():
        card["summary"] = fallback["summary"]
    takeaways = card.get("key_takeaways")
    if not isinstance(takeaways, list) or len(takeaways) != 3 or not all(isinstance(x, str) and x.strip() for x in takeaways):
        card["key_takeaways"] = fallback["key_takeaways"]
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
        content = article_content(item)
        if is_fallback and item.get("key_takeaways") != content["key_takeaways"]:
            item["key_takeaways"] = content["key_takeaways"]
            changed = True
        elif not isinstance(item.get("key_takeaways"), list) or len(item["key_takeaways"]) != 3:
            item["key_takeaways"] = content["key_takeaways"]
            changed = True
        if is_fallback and item.get("summary") != content["summary"]:
            item["summary"] = content["summary"]
            item["why_it_matters"] = content["key_takeaways"][0]
            changed = True
    return changed


def update_archive(data_dir: Path) -> dict:
    briefs = []
    archive_items = []
    for path in sorted(data_dir.glob("????-??-??.json"), reverse=True):
        brief = json.loads(path.read_text(encoding="utf-8"))
        items = brief.get("items", [])
        for item in items:
            content = article_content(item)
            action = item.get("practical_action")
            if not valid_practical_action(action):
                action = practical_action(item)
            archive_items.append({
                "brief_date": brief["date"],
                "creator": item["creator"],
                "title": item["title"],
                "published": item.get("published", ""),
                "source": item.get("source", ""),
                "score": item.get("score"),
                "summary": content["summary"],
                "why_it_matters": item.get("why_it_matters", ""),
                "key_takeaways": content["key_takeaways"],
                "topics": item.get("topics", item.get("focus", [])),
                "practical_action": action,
            })
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
    unique = {item["id"]: item for item in items if has_grounded_content(item)}
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
                "Why It Matters": rich_text(" ".join(item.get("key_takeaways", [item["why_it_matters"]]))),
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
