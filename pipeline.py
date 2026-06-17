#!/usr/bin/env python3
"""
vidrot.ai — MAIN PIPELINE v4
Orchestrates: trend scraping → prompt generation → (video gen) → Instagram posting

Modes:
  python pipeline.py              # Full run: trends + prompts + save
  python pipeline.py --post       # Also attempt Instagram posting
  python pipeline.py --cron       # Cron mode: generate daily batch

Environment:
  IG_USERNAME=vidrot.ai
  IG_PASSWORD=*** (GitHub Secret)
  POST_AFTER_GENERATE=true
"""
import json, os, sys, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from trending import get_trends
from prompt_generator import generate_prompts, save_batch


def main():
    parser = argparse.ArgumentParser(description="vidrot.ai Pipeline")
    parser.add_argument("--count", type=int, default=5, help="Number of prompts to generate")
    parser.add_argument("--post", action="store_true", help="Post to Instagram after generation")
    parser.add_argument("--cron", action="store_true", help="Cron mode (quiet, daily batch)")
    parser.add_argument("--dry-run", action="store_true", help="Generate prompts only, don't save")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  📺 VIDROT.AI PIPELINE v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Scrape trends
    print("[1/4] Scraping trending topics...")
    trends = get_trends(force_fresh=not args.cron)
    print(f"   ✅ {len(trends)} topics: {', '.join(trends[:5])}")

    # 2. Generate prompts
    print(f"\n[2/4] Generating {args.count} interdimensional channels...")
    prompts = generate_prompts(trends, count=args.count)
    for i, p in enumerate(prompts):
        print(f"   [{i+1}] {p['channel'][:45]}")
        print(f"       {p['bumper']}")

    # 3. Save batch
    if not args.dry_run:
        print(f"\n[3/4] Saving prompt batch...")
        batch_file = save_batch(prompts)

        # Save generation instructions (for manual Veo generation)
        inst_file = BASE / "output" / "generate_instructions.txt"
        inst_file.parent.mkdir(exist_ok=True)
        with open(inst_file, "w") as f:
            f.write(f"VIDROT BATCH: {batch_file.stem}\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"Trending: {', '.join(trends[:5])}\n")
            f.write(f"\n{'='*60}\n")
            f.write("Generate these 5 clips using Veo / AI video:\n")
            f.write(f"{'='*60}\n\n")
            for i, p in enumerate(prompts):
                f.write(f"CLIP {i+1}: {p['channel']}\n")
                f.write(f"  Prompt: {p['prompt']}\n")
                f.write(f"  Seed: {p['seed']}\n")
                f.write(f"  Save as: output/{i:03d}_{p['channel'][:30]}.mp4\n\n")

        print(f"   ✅ Instructions → {inst_file}")

        # Save caption file for Instagram
        captions = {}
        for p in prompts:
            channel = p['channel'].replace("_", " ").title()
            captions[p['channel']] = (
                f"{p['bumper']}\n\n"
                f"📺 {channel}\n\n"
                f"#vidrot #aiart #surreal #shorts #aivideo"
            )
        caption_file = BASE / "output" / f"captions_{batch_file.stem}.json"
        with open(caption_file, "w") as f:
            json.dump(captions, f, indent=2)
        print(f"   ✅ Captions → {caption_file}")

        # Generate prompt summary for terminal
        print(f"\n[4/4] Next steps:")
        print(f"   1. Generate clips: Use Veo or image_generate with prompts above")
        print(f"   2. Save clips to: vidrot-pipeline/output/")
        print(f"   3. Post: python post_instagram.py --batch output/ --caption-file {caption_file.name}")
    else:
        print(f"\n[3/4] Dry run — skipping save")

    # 4. Instagram posting (optional)
    if args.post and not args.dry_run:
        print(f"\n[4/4] Instagram posting...")
        print("   ⚠️  Instagram posting needs session file or credentials")
        print("   Run: python post_instagram.py --batch output/ --caption-file captions.json")

    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline complete — {len(prompts)} channels ready")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
