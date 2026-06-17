# vidrot.ai — Interdimensional Cable Pipeline

🛰️ **Autonomous AI video pipeline for surreal content.** Generates interdimensional cable channel concepts from trending topics + glitch aesthetics. Built for Instagram (@vidrot.ai).

## Architecture

```
GitHub Actions (daily 9AM EST)
  ├── trending.py          → Google Trends RSS → clean topics
  ├── prompt_generator.py  → Surreal channel concepts + prompts
  └── pipeline.py          → Orchestrator

Your PC or VPS (video + posting)
  ├── AI video generation  → Veo / image_generate / ComfyUI
  ├── FFmpeg               → Audio, captions, end cards
  └── post_instagram.py    → instagrapi clip upload
```

## Quick Start

```bash
# Clone
git clone https://github.com/CRYPTORICH/vidrot-pipeline.git
cd vidrot-pipeline

# Generate today's batch
python pipeline.py

# With live trends
python pipeline.py --count 5

# Generate + show posting instructions
python pipeline.py --dry-run
```

## Daily Schedule

- **Mon-Sat 9:00 AM EST** — GitHub Actions runs `pipeline.py --cron`
- Generates 5 prompts from live Google Trends
- Commits batch to `prompts/` directory
- Instructions saved to `output/generate_instructions.txt`

## Posting to Instagram

```bash
# Single video
python post_instagram.py output/final_000.mp4 "Your caption"

# Batch with captions
python post_instagram.py --batch output/ --caption-file output/captions_batch_20260616.json

# Test login only
python post_instagram.py --dry-run
```

**Credentials:** Set `IG_USERNAME` + `IG_PASSWORD` env vars, or place session file at `~/.openclaw/instagram_sessions/session.json`

## Video Generation

The pipeline generates prompts. Video generation is a separate step:
1. Take the prompts from `output/generate_instructions.txt`
2. Generate using your AI video tool (Veo, Runway, etc.)
3. Save clips to `output/` as `000_channelname.mp4`
4. Run `python post_instagram.py --batch output/`

## Files

```
vidrot-pipeline/
├── .github/workflows/daily-pipeline.yml  # GitHub Actions cron
├── pipeline.py                           # Main orchestrator
├── prompt_generator.py                   # Surreal channel generator
├── trending.py                           # Google Trends scraper
├── post_instagram.py                     # Instagram uploader
├── config/
│   ├── channels.json                     # Archetypes, styles, settings
│   └── trending_cache.json              # Cached trends
├── prompts/                              # Generated prompt batches
├── output/                               # Video output + instructions
└── requirements.txt
```

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `IG_USERNAME` | For posting | `vidrot.ai` |
| `IG_PASSWORD` | For posting | (GitHub Secret) |
| `IG_SESSION_FILE` | Optional | `~/.openclaw/instagram_sessions/session.json` |

## Related

- Instagram: [@vidrot.ai](https://www.instagram.com/vidrot.ai/)
- Concept: "GasBuddy for groceries but actually interdimensional cable"
- Revenue target: $10K/month (Reels bonus, Creator Fund, sponsorships)
