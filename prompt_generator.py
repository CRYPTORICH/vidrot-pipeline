#!/usr/bin/env python3
"""
vidrot.ai — SURREAL CHANNEL GENERATOR v2
Creates interdimensional cable channel concepts from live trends.
No PC hardcoded paths. Runs anywhere.
"""
import json
import random
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from paths import ROOT, base_dir

CONFIG = ROOT / "config" / "channels.json"

with open(CONFIG) as f:
    data = json.load(f)

ACTION_VERBS = data["actions"]
SETTINGS = data["settings"]
STYLES = data["styles"]
NOISE = data["noise"]
CHARACTERS = data["characters"]
BUMPERS = data["bumpers"]


def channel_slug(trend, limit=28):
    """Filesystem-safe channel id. Drops punctuation so clip names stay valid."""
    text = unescape(str(trend)).upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    text = text[:limit].strip("_")
    return text or "CHANNEL"


def generate_prompts(trending_topics, count=5):
    """Build surreal prompts blending trends + interdimensional chaos."""
    if not trending_topics:
        trending_topics = ["ALGORITHM COLLAPSE", "DIGITAL DETOX", "AI TAKEOVER"]

    prompts = []
    used_channels = set()

    for _ in range(count):
        full_channel = ""
        char = random.choice(CHARACTERS)
        action = random.choice(ACTION_VERBS)
        setting = random.choice(SETTINGS)
        style = random.choice(STYLES)
        noise_effect = random.choice(NOISE)
        bumper = random.choice(BUMPERS)

        for _attempt in range(30):
            trend = random.choice(trending_topics)
            channel = channel_slug(trend)
            variant = random.randint(0, 999)
            full_channel = f"{channel}_{variant}"
            if full_channel not in used_channels:
                break
        else:
            full_channel = f"CHANNEL_{len(prompts)}_{random.randint(0, 9999)}"

        used_channels.add(full_channel)

        prompt = (
            f"{trend.strip()} — {char} is {action} "
            f"something important in {setting}. "
            f"Style: {style}. Atmosphere: unsettling but strangely compelling. "
            f"Post-processing: heavy {noise_effect}. Aspect ratio: 9:16 vertical. Duration: 5-8 seconds."
        )

        prompts.append({
            "channel": full_channel,
            "bumper": bumper,
            "prompt": prompt,
            "style": style,
            "noise": noise_effect,
            "setting": setting,
            "character": char,
            "action": action,
            "seed": random.randint(0, 999999),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return prompts


def save_batch(prompts, output_dir=None):
    """Save a batch of prompts to the prompts directory."""
    if output_dir is None:
        output_dir = base_dir() / "prompts"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"batch_{timestamp}.json"
    with open(filepath, "w") as f:
        json.dump(prompts, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✅ {len(prompts)} prompts → {filepath}")
    return filepath


if __name__ == "__main__":
    test_trends = ["AI TAKEOVER", "QUIET QUITTING", "CRYPTO CRASH", "VIRTUAL REALITY", "GREENWASHING"]
    prompts = generate_prompts(test_trends, count=3)
    for p in prompts:
        print(f"\n📺 {p['channel']}")
        print(f"   {p['prompt'][:120]}...")
