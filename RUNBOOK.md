# vidrot.ai runbook

How the pipeline works, how to run it, and what was broken.

The daily job does **not** make video and it does **not** post to Instagram by itself. It pulls live Google Trends, writes five surreal "interdimensional cable" channel prompts, and commits that batch to this repo. You generate the clips (Veo or similar) and post them with `post_instagram.py`.

## Why it was dead

Every GitHub Actions run failed, starting with the first one on 2026-06-17 (`27689212533`) through the last one on 2026-08-17 (`32036055230`). The generate step succeeded. The next step, "Commit generated prompts", exited 1.

`prompts/` and `output/` were listed in `.gitignore`, and the workflow ran `git add prompts/ output/ config/trending_cache.json`. Git exits 1 when you add an ignored path, and the shell stops there. Nothing was ever committed, so the repo's last real push stayed 2026-06-17.

Two more problems were waiting behind that one:

- The workflow token was read-only (`contents: read` in the run logs). A successful `git add` would still have died on `git push`.
- The push trigger included `config/**`. The job rewrites `config/trending_cache.json`, so a green run would have started another run, forever.

On 2026-08-17 GitHub set the workflow to `disabled_inactivity`. This is a public repo, and GitHub turns scheduled workflows off after 60 days with no commits, issues, or pull requests. Scheduled runs do not count as activity. The last push was 2026-06-17, which is why the schedule went quiet right after the 2026-08-17 run and nothing has fired since.

The Instagram job did not cause these failures. It was hardcoded `if: false`, so it was skipped every time. The poster also had bugs that would have shown up the first time someone turned it on: `clip_upload` returns a Media object, and the script called `.get()` on it as if it were a dict. It also invented a new phone fingerprint on every launch, which is the opposite of what a saved Instagram session needs.

Google Trends itself is fine. The RSS feed still returns titles, and the August logs show the scrape succeeding.

## What each file does

| File | Role |
| --- | --- |
| `pipeline.py` | Runs the batch: trends, then prompts, then caption and instruction files. |
| `trending.py` | Reads Google Trends RSS (`https://trends.google.com/trending/rss?geo=US`). No API key. |
| `prompt_generator.py` | Mixes each trend with the word banks in `config/channels.json`. |
| `config/channels.json` | The "sauce": characters, settings, styles, bumpers. Edit this to change the voice. |
| `config/trending_cache.json` | Last successful trend list. Used when Google is down. A failed fetch does not wipe it. |
| `post_instagram.py` | Uploads mp4 Reels with instagrapi. Not used by the daily schedule. |
| `scripts/commit_batch.sh` | What Actions runs after a batch. Commits prompts and caption text, never video. |
| `.github/workflows/daily-pipeline.yml` | Tests, then the daily batch. Instagram only if you opt in by hand. |
| `prompts/` | One JSON file per batch. This directory is committed. |
| `output/generate_instructions.txt` | The prompts, seeds, and exact mp4 filenames to render. |
| `output/captions_batch_*.json` | Captions keyed by those filenames. Committed. The mp4s are not. |

## Environment variables and secrets

Prompt generation needs no secrets. These are only for posting.

| Name | Required | Where to get it |
| --- | --- | --- |
| `IG_USERNAME` | For posting | The Instagram handle. The account in the README is `vidrot.ai`. |
| `IG_PASSWORD` | One of the login methods | The Instagram password for that account. Store it in `.env` locally, or as a GitHub Actions secret. Do not commit it. |
| `IG_SESSION_FILE` | Best login method | Path to a `session.json` written by a successful `python post_instagram.py --dry-run` on your own machine. |
| `IG_SESSION_JSON` | Alternative to the file | The contents of that same `session.json`, as one JSON blob. This is the value to put in a GitHub secret if a hosted runner must post. |
| `IG_SESSIONID` | Alternative | The `sessionid` cookie from a browser logged in as the account. Weaker than the full session file. |
| `IG_VERIFICATION_CODE` | Only for 2FA password logins | The current 6-digit code from the authenticator app. Not needed when a saved session still works. |
| `IG_POST_DELAY_MIN` / `IG_POST_DELAY_MAX` | No | Seconds between clips in one batch. Defaults: 300 and 900. |
| `TRENDS_GEO` | No | Google Trends country code. Default `US`. |
| `VIDROT_BASE` | No | Write prompts and captions into another directory instead of the repo. |

Session files are also picked up with no variable set, in this order:

1. `IG_SESSION_FILE`
2. `~/.openclaw/instagram_sessions/session.json` (the path this repo already looked in)
3. `config/session.json` inside the repo (gitignored)

Copy `.env.example` to `.env` for local use. The scripts do not load `.env` on their own:

```bash
set -a && source .env && set +a
```

GitHub Actions secrets, if you later post from a runner: repo → Settings → Secrets and variables → Actions → New repository secret. Names must match the table (`IG_USERNAME`, `IG_PASSWORD`, `IG_SESSION_JSON`, `IG_SESSIONID`, `IG_VERIFICATION_CODE`). This runbook's author could not list the existing secrets (the API returned 403), so treat them as unset until you check that page yourself.

There is no key for trends, and no key in this repo for video models. Rendering happens in whatever tool you already use.

## Run it locally

Python 3.12 is what Actions uses. The prompt scripts use the standard library only.

```bash
git clone https://github.com/CRYPTORICH/vidrot-pipeline.git
cd vidrot-pipeline

# Print a batch, write nothing
python pipeline.py --dry-run --count 3

# Write prompts/ and output/ in a scratch directory
VIDROT_BASE=/tmp/vidrot python pipeline.py --count 5

# Same thing, into this repo (this is what Actions does)
python pipeline.py --cron --count 5

# Tests, no network and no Instagram account
python -m unittest discover -s tests -v

# See whether posting is configured, without logging in
python post_instagram.py --check
```

After a real run, open `output/generate_instructions.txt`. Make one vertical mp4 per clip and save it under `output/` with the filename in that file (for example `output/000_SOME_TREND_42.mp4`).

Post from your own machine, not from a fresh datacenter IP, once `IG_PASSWORD` or a session file is set:

```bash
pip install -r requirements.txt
python post_instagram.py --dry-run
python post_instagram.py --batch output/ --caption-file output/captions_batch_YYYYMMDD_HHMMSS.json
```

`--dry-run` logs in and saves `config/session.json` (or `IG_SESSION_FILE` if you set it). The next run reuses that file so Instagram sees the same device. A password login that hits a challenge or 2FA has to be approved by you; the script prints which case it is. Copy the saved `session.json` somewhere safe. Anyone with that file is logged in as the account.

`python pipeline.py --post` uploads whatever mp4s are already in `output/` after it writes the new batch. With no mp4s it just tells you that and exits 0.

## Run it in Actions

Workflow file: `.github/workflows/daily-pipeline.yml`.

- **Pull requests:** unit tests only.
- **Push to `main`** that touches the pipeline, the word bank, or this workflow: tests, then a batch, then a commit.
- **Schedule:** `0 13 * * 1-6` (13:00 UTC, Monday–Saturday). Same batch and commit. No Instagram.
- **Run workflow button:** same batch. Set "post to instagram" only if this runner already has mp4s in `output/` and the IG secrets exist. It usually should stay off, because clips are produced on your machine and mp4s are gitignored.

The commit step runs `scripts/commit_batch.sh`. It commits:

- `prompts/`
- `config/trending_cache.json`
- `output/*.json`, `output/*.txt`, `output/*.md`

It does not commit mp4s or `config/session.json`. The commit message includes `[skip ci]` so the bot push does not start the workflow again. The token has `contents: write`, which is what makes `git push` legal.

## Turn the schedule back on

Merging this pull request does **not** re-enable a workflow GitHub disabled for inactivity. After the merge:

1. Open <https://github.com/CRYPTORICH/vidrot-pipeline/actions>.
2. Click **vidrot.ai Daily Pipeline** in the left sidebar.
3. If the yellow banner says the workflow is disabled, click **Enable workflow**.
4. Click **Run workflow** → branch `main` → leave "post to instagram" unchecked → **Run workflow**.
5. Confirm the run is green and that it pushed a commit named `Daily prompt batch ...`.

The schedule then runs at 13:00 UTC the next Monday–Saturday. A disabled workflow does not catch up on missed days.

To turn the schedule off later, open the same page and click the `...` menu → **Disable workflow**.

## What only the owner can do

1. **Merge the pull request.** The fixes are not on `main` until then, and the scheduled workflow that is still disabled is the old one.
2. **Enable the workflow** using the clicks above. The state on 2026-10-17 was `disabled_inactivity`. A code push does not clear that flag.
3. **Run the workflow once by hand** so you do not wait until the next 13:00 UTC to see if the commit lands.
4. **Instagram login, if you still want posting.** Check Settings → Secrets and variables → Actions. If `IG_USERNAME` and `IG_PASSWORD` are missing, add them. Better: on your own computer run `python post_instagram.py --dry-run` while those two are set, approve any Instagram challenge or 2FA prompt, and keep the `session.json` it writes. Password login from a GitHub-hosted runner is the path that gets checkpointed. This repo cannot finish that prompt for you.
5. **Render the clips.** Nothing in this repo calls Veo or any other video API. The daily job's output is the instruction file. Posting does nothing until those mp4s exist.
6. **Branch protection, only if the first green run fails on `git push`.** If `main` requires a pull request or a signed commit, the bot push will be rejected. Allow `github-actions[bot]` to push to `main`, or turn that rule off for this repo. The API used here could not read branch protection (403), so this is a "only if the push is rejected" item, not a confirmed block.
