# vidrot.ai — Interdimensional Cable Pipeline

Generates surreal "interdimensional cable" channel concepts from live Google Trends, then posts finished clips to Instagram (`@vidrot.ai`) with instagrapi.

The daily GitHub Actions job writes the prompts. Video rendering and Instagram login happen on your machine. Operations, secrets, and how to turn the schedule back on are in [RUNBOOK.md](RUNBOOK.md).

## What runs where

```
GitHub Actions (Mon–Sat, 13:00 UTC)
  ├── trending.py           Google Trends RSS, no API key
  ├── prompt_generator.py   trend + config/channels.json
  └── pipeline.py           writes prompts/ and output/

Your machine
  ├── render the clips      Veo or any other video tool
  └── post_instagram.py     instagrapi Reel upload
```

## Quick start

```bash
git clone https://github.com/CRYPTORICH/vidrot-pipeline.git
cd vidrot-pipeline

python pipeline.py --dry-run --count 3
python pipeline.py --count 5
python -m unittest discover -s tests -v
```

A real run writes:

- `prompts/batch_YYYYMMDD_HHMMSS.json`
- `output/generate_instructions.txt` (prompt, seed, and the mp4 filename)
- `output/captions_batch_*.json`

Render each clip to the filename in the instructions file, then:

```bash
pip install -r requirements.txt
python post_instagram.py --check
python post_instagram.py --dry-run
python post_instagram.py --batch output/ --caption-file output/captions_batch_YYYYMMDD_HHMMSS.json
```

`IG_USERNAME` and `IG_PASSWORD` (or a session file) are required only for posting. See [RUNBOOK.md](RUNBOOK.md) for every variable and for re-enabling the schedule, which GitHub turned off for inactivity on 2026-08-17.

## Files

```
vidrot-pipeline/
├── .github/workflows/daily-pipeline.yml
├── pipeline.py
├── prompt_generator.py
├── trending.py
├── post_instagram.py
├── scripts/commit_batch.sh
├── config/channels.json
├── config/trending_cache.json
├── prompts/
├── output/
└── RUNBOOK.md
```

## Related

- Instagram: [@vidrot.ai](https://www.instagram.com/vidrot.ai/)
