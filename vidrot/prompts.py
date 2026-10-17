"""Interdimensional-cable prompts. The word banks are the desktop generator's."""
import json
import random
from pathlib import Path

BANKS_PATH = Path(__file__).with_name("banks.json")
HASHTAGS = "#vidrot #aiart #surreal #shorts #aivideo"


def load_banks():
    return json.loads(BANKS_PATH.read_text(encoding="utf-8"))


def _caption(bumper, channel):
    title = channel.replace("_", " ").title()
    return f"{bumper}\n\n📺 {title}\n\n{HASHTAGS}"


def generate_one(trend, banks, rng, channel=None):
    channel = channel or rng.choice(banks["channels"])
    style = rng.choice(banks["styles"])
    noise = rng.choice(banks["noise"])
    action = rng.choice(banks["actions"])
    setting = rng.choice(banks["settings"])
    modifier = rng.choice(banks["modifiers"])
    bumper = rng.choice(banks["bumpers"])
    entity = channel.replace("_", " ").title()
    trend_text = (trend or "something the timeline will not explain").strip()
    prompt = (
        f"{entity} — a being {modifier} is {action} the idea of \"{trend_text}\" "
        f"in {setting}. Style: {style}. Atmosphere: unsettling but strangely compelling. "
        f"Post-processing: heavy {noise}. Aspect ratio: 9:16 vertical. Duration: 6-8 seconds."
    )
    return {
        "channel": channel,
        "trend": trend_text,
        "bumper": bumper,
        "prompt": prompt,
        "caption": _caption(bumper, channel),
        "style": style,
        "status": "draft",
        "operation": "",
        "clip": "",
        "error": "",
    }


def generate_batch(trends, count=5, banks=None, rng=None):
    banks = banks or load_banks()
    rng = rng or random
    topics = [t for t in (trends or []) if str(t).strip()] or ["a signal from nowhere"]
    used = set()
    prompts = []
    for index in range(count):
        channel = None
        for _ in range(12):
            pick = rng.choice(banks["channels"])
            if pick not in used:
                channel = pick
                break
        used.add(channel or banks["channels"][index % len(banks["channels"])])
        item = generate_one(topics[index % len(topics)], banks, rng, channel=channel)
        item["id"] = f"p{index + 1}"
        prompts.append(item)
    return prompts


def apply_edits(prompts, edits):
    """Replace prompt and caption text. Unknown ids are ignored."""
    by_id = {item.get("id"): item for item in edits or []}
    updated = []
    for prompt in prompts:
        edit = by_id.get(prompt.get("id"))
        if not edit:
            updated.append(prompt)
            continue
        copy = dict(prompt)
        text = str(edit.get("prompt") or "").strip()
        caption = str(edit.get("caption") or "").strip()
        if text:
            copy["prompt"] = text
        if caption:
            copy["caption"] = caption
        if copy.get("status") == "failed":
            copy["status"] = "draft"
            copy["error"] = ""
        updated.append(copy)
    return updated
