#!/usr/bin/env python3
"""
vidrot.ai — MAIN PIPELINE v4
Orchestrates: trend scraping → prompt generation → (you generate video) → Instagram posting

Modes:
  python pipeline.py              # Trends + prompts, saved under prompts/ and output/
  python pipeline.py --dry-run    # Print a batch, write nothing
  python pipeline.py --cron       # Same generation path used by GitHub Actions
  python pipeline.py --post       # After saving, upload any mp4s already in output/

Environment:
  TRENDS_GEO=US                   # Google Trends country code
  VIDROT_BASE=/path               # Write prompts outside the repo
  IG_USERNAME / IG_PASSWORD       # Only used with --post. See RUNBOOK.md.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from paths import base_dir
from prompt_generator import generate_prompts, save_batch
from trending import get_trends


def clip_stem(index, channel):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", channel).strip("_") or "channel"
    return f"{index:03d}_{safe}"


def build_caption(prompt):
    channel = prompt["channel"].replace("_", " ").title()
    return (
        f"{prompt['bumper']}\n\n"
        f"📺 {channel}\n\n"
        f"#vidrot #aiart #surreal #shorts #aivideo"
    )


def write_sidecars(prompts, trends, batch_file):
    """Instructions for video generation, plus the caption file the poster reads."""
    output_dir = base_dir() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    inst_file = output_dir / "generate_instructions.txt"
    lines = [
        f"VIDROT BATCH: {batch_file.stem}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Trending: {', '.join(trends[:5])}",
        "",
        "=" * 60,
        "Generate these clips with Veo or another AI video tool.",
        "Save each file under output/ using the exact name below.",
        "The caption file is keyed by that filename (without .mp4).",
        "=" * 60,
        "",
    ]
    captions = {}
    for i, prompt in enumerate(prompts):
        stem = clip_stem(i, prompt["channel"])
        caption = build_caption(prompt)
        captions[stem] = caption
        captions[prompt["channel"]] = caption
        lines.extend([
            f"CLIP {i + 1}: {prompt['channel']}",
            f"  Prompt: {prompt['prompt']}",
            f"  Seed: {prompt['seed']}",
            f"  Save as: output/{stem}.mp4",
            "",
        ])
    inst_file.write_text("\n".join(lines))

    caption_file = output_dir / f"captions_{batch_file.stem}.json"
    caption_file.write_text(json.dumps(captions, indent=2) + "\n")
    return inst_file, caption_file


def main():
    parser = argparse.ArgumentParser(description="vidrot.ai Pipeline")
    parser.add_argument("--count", type=int, default=5, help="Number of prompts to generate")
    parser.add_argument("--post", action="store_true", help="Upload mp4s in output/ after generation")
    parser.add_argument("--cron", action="store_true", help="Cron mode (same generation, quieter label)")
    parser.add_argument("--dry-run", action="store_true", help="Generate prompts only, don't save")
    args = parser.parse_args()

    if args.count < 1:
        print("Count must be at least 1")
        return 1

    mode = "CRON" if args.cron else "MANUAL"
    print(f"\n{'=' * 60}")
    print(f"  📺 VIDROT.AI PIPELINE v4 — {mode} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}\n")

    print("[1/4] Scraping trending topics...")
    trends = get_trends(write_cache=not args.dry_run)
    print(f"   ✅ {len(trends)} topics: {', '.join(trends[:5])}")

    label = "channel" if args.count == 1 else "channels"
    print(f"\n[2/4] Generating {args.count} interdimensional {label}...")
    prompts = generate_prompts(trends, count=args.count)
    for i, prompt in enumerate(prompts):
        print(f"   [{i + 1}] {prompt['channel']}")
        print(f"       {prompt['bumper']}")

    caption_file = None
    if args.dry_run:
        print("\n[3/4] Dry run — skipping save")
    else:
        print("\n[3/4] Saving prompt batch...")
        batch_file = save_batch(prompts)
        inst_file, caption_file = write_sidecars(prompts, trends, batch_file)
        print(f"   ✅ Instructions → {inst_file}")
        print(f"   ✅ Captions → {caption_file}")
        print("\n[4/4] Next steps:")
        print("   1. Generate clips with Veo (or similar) from output/generate_instructions.txt")
        print("   2. Save the mp4s in output/ using the filenames in that file")
        print(f"   3. Post: python post_instagram.py --batch output/ --caption-file {caption_file.name}")

    if args.post and not args.dry_run:
        print("\n[4/4] Instagram posting...")
        from post_instagram import post_batch

        code = post_batch(base_dir() / "output", caption_file)
        if code != 0:
            return code

    print(f"\n{'=' * 60}")
    print(f"  ✅ Pipeline complete — {len(prompts)} channels ready")
    print(f"{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
