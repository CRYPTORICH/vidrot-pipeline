#!/usr/bin/env python3
"""
vidrot.ai — SURREAL CHANNEL GENERATOR v2
Creates interdimensional cable channel concepts from live trends.
No PC hardcoded paths. Runs anywhere.
"""
import json, random, os
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
CONFIG = BASE / "config" / "channels.json"

# ----- Data Bank -----
with open(CONFIG) as f:
    data = json.load(f)

ACTION_VERBS = data["actions"]
SETTINGS = data["settings"]
STYLES = data["styles"]
NOISE = data["noise"]
CHARACTERS = data["characters"]
BUMPERS = data["bumpers"]

def generate_prompts(trending_topics, count=5):
    """Build surreal prompts blending trends + interdimensional chaos."""
    if not trending_topics:
        trending_topics = ["ALGORITHM COLLAPSE", "DIGITAL DETOX", "AI TAKEOVER"]

    prompts = []
    used_channels = set()

    for i in range(count):
        trend = random.choice(trending_topics)
        # Create unique channel name
        channel = trend.replace(" ", "_").replace("'", "").replace("&", "AND").upper()[:30]
        variant = random.randint(0, 999)
        full_channel = f"{channel}_{variant}"
        while full_channel in used_channels:
            trend = random.choice(trending_topics)
            channel = trend.replace(" ", "_").replace("'", "").upper()[:30]
            variant = random.randint(0, 999)
            full_channel = f"{channel}_{variant}"
        used_channels.add(full_channel)

        char = random.choice(CHARACTERS)
        action = random.choice(ACTION_VERBS)
        setting = random.choice(SETTINGS)
        style = random.choice(STYLES)
        noise_effect = random.choice(NOISE)
        bumper = random.choice(BUMPERS)

        prompt = (
            f"{channel.replace('_',' ').title()} — {char} is {action} "
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
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    return prompts


def save_batch(prompts, output_dir=None):
    """Save a batch of prompts to the prompts directory."""
    if output_dir is None:
        output_dir = BASE / "prompts"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"batch_{timestamp}.json"
    with open(filepath, "w") as f:
        json.dump(prompts, f, indent=2, ensure_ascii=False)

    print(f"✅ {len(prompts)} prompts → {filepath}")
    return filepath


if __name__ == "__main__":
    # Test with sample trends
    test_trends = ["AI TAKEOVER", "QUIET QUITTING", "CRYPTO CRASH", "VIRTUAL REALITY", "GREENWASHING"]
    prompts = generate_prompts(test_trends, count=3)
    for p in prompts:
        print(f"\n📺 {p['channel']}")
        print(f"   {p['prompt'][:120]}...")
