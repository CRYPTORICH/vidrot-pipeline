# vidrot.ai — install and daily use

This is the app that replaces the 9:00 and 12:00 Windows scheduled tasks. It runs on the same PC, uses the same Veo call Ralph's scripts used, and does not pop a console window.

## Install on Windows

1. Install **Python 3.11** from [python.org](https://www.python.org/downloads/windows/). On the first installer page, leave the **py launcher** enabled. The shortcut tries `pyw -3.11`, then any windowless Python.
2. Install **ffmpeg** and make sure `ffmpeg` works in a terminal. [gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/) are fine. If you would rather not put it on PATH, set the full path on the Settings page later (`C:\ffmpeg\bin\ffmpeg.exe` or wherever it landed).
3. In a terminal, once:

```bat
cd C:\Users\dejes\Desktop\vidrot_pipeline
pip install -r requirements.txt
```

Use the folder where this repo actually lives. `instagrapi` is only needed when you post. Prompt generation and dry-run previews use the standard library plus ffmpeg.

4. Right-click `windows\Start Vidrot.vbs` → **Create shortcut**, and put that shortcut on the desktop. Do not copy the `.vbs` file itself. A copy loses the path back to `console\server.py`.

## Start and stop

Double-click the shortcut. The browser opens `http://127.0.0.1:8765/`. There is no terminal window. Closing the browser does **not** stop the app, which is what lets the scheduler keep running.

To stop it, double-click `windows\Stop Vidrot.vbs`. That sends a shutdown to the local page. It also has no console window.

A second double-click of Start, while the app is already running, only opens the browser again.

Dry run is **on** the first time you open it. Leave it on until a batch, a preview reel, and a dry-run "post" all look right. Dry run does not call Google and does not upload.

## First-time setup

Open **Settings**. Everything on that page is saved under:

```
%LOCALAPPDATA%\vidrot\settings.json
```

That folder is outside the git repo. Do not copy `settings.json` or `session.json` into the repo.

### Veo

Clips are generated the way `generate_veo_batch.py` and `generate_more_veo.py` did it, not through the OpenClaw gateway:

- `POST https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-fast-generate-preview:predictLongRunning?key=…`
- body: `instances[0].prompt`, `parameters.aspectRatio = 9:16`, `parameters.durationSeconds` of 4, 6, or 8
- poll the long-running operation, then download `generatedSamples[0].video.uri`

The key is the same **Gemini API key** that used to live in `GEMINI_API_KEY` or `GOOGLE_API_KEY`. Create or copy it at [aistudio.google.com](https://aistudio.google.com/apikey) and paste it into Settings. A blank field does not erase a key you already saved.

**Health → Test Veo key** is the only button that talks to Google for a status check. The health panel itself only looks at whether a key is saved, so refreshing the page does not spend quota.

Ralph (OpenClaw) was the agent that *ran* those scripts. The scripts themselves called Google. The console does that call directly. OpenClaw can stay running on `http://127.0.0.1:18790`; Health reports whether that port answers. It is not required to make a clip.

The one-off repairs in `check_veo_auth.py` and `fix_veo.py` patched a broken `@google/genai` install inside OpenClaw's `node_modules`. Those are not part of this app.

### Instagram

Two ways, in the order the poster tries them:

1. Copy an existing session file to `%LOCALAPPDATA%\vidrot\session.json`. The old tools looked in `C:\Users\dejes\.openclaw\instagram_sessions\session.json` and in `config\session.json`.
2. Or type the Instagram username and password on Settings and use **Health → Test Instagram login** (or just post). The first successful login writes `session.json`. Later posts reuse it and do not send the password again.

If Instagram wants a checkpoint or a 6-digit code, the Post page says so and has a code field. It does not call `input()`, which is what used to hang a hidden window. Approve the prompt on the phone, or type the current authenticator code, and try the post again.

Health never logs in by itself. It only checks that a session file or a password is present.

### OpenClaw

Leave the gateway on port 18790 if you still use Ralph for other work. Point Settings at a different URL only if you moved it. The morning job does not call the gateway.

## A normal day, by hand

| Page | What it does |
| --- | --- |
| Today | New batch reads Google Trends (RSS, no key) and writes five channels from the same word banks as the desktop `prompt_generator.py`. Render clips, then Stitch and brand. |
| Prompts | Edit the Veo prompt and the caption, then Save. Regenerate replaces one channel. |
| Clips | One card per job: waiting, rendering, ready, or the error text. |
| Reel | Plays the stitched 1080×1920 file. |
| Post | Caption, optional authenticator code, then Post now. History is the list of what was posted (or dry-run saved). |
| Schedule | Two toggles and two times. See below. |
| Health | Veo key, Instagram session, OpenClaw, ffmpeg, free disk, how many clips and reels are on disk, last run. |
| Logs | The same lines the morning job writes, in `%LOCALAPPDATA%\vidrot\logs\console.log`. |

Branding re-encodes each clip to 1080×1920 before joining. The old `pipeline.py` concat of mismatched files is what used to fail. If you drop a bumper mp4 into `%LOCALAPPDATA%\vidrot\bumpers\`, it is placed first. Otherwise the reel starts on the first clip. The watermark text is `VIDROT` plus the channel name.

A failed Veo submit is retried three times. The error stays on that clip's card. One bad clip does not throw away the ones that succeeded.

## Scheduler (replaces the two tasks)

On **Schedule**:

- **Morning batch** defaults to 09:00. It pulls trends, renders, and brands. It does not post.
- **Midday post** defaults to 12:00. It posts the reel from the morning job if that reel is still waiting.
- Days default to Monday–Saturday. Sunday is off, matching the old habit.
- Each job fires once per day, and only if the app is open within 10 minutes after the chosen time.

Both toggles start **off**. Turn them on after a dry run looks right, then turn Dry run off when you want real Veo clips and a real upload.

The app has to be running. Windows does not start it at logon unless you add the Start shortcut to the Startup folder yourself (`shell:startup`). That shortcut is still windowless.

## Leave the old scheduled tasks

Both tasks were already disabled on 2026-06-17 because they flashed a console ("blue box"). Confirm they stay gone:

1. Open **Task Scheduler**.
2. Find `\vidrot_pipeline` (daily 09:00, `run_daily.ps1`) and `\vidrot_12pm_post` (one-shot 12:00, `auto_poster.py` pointed at `C:\Users\dejes\.openclaw\media\vidrot_trending_v1.mp4`, which no longer exists).
3. Disable them if they are enabled, or delete them.

Do not re-enable `run_daily.ps1` or `auto_poster.py`. The console is the replacement. The 12:00 task could not succeed anyway: it posted one hardcoded file that is gone.

## What was dropped

Kept, because it was the working loop: trend text, the channel word banks, the Gemini Veo REST call, ffmpeg branding, instagrapi with a saved session.

Not carried over:

- Money Mitch / Blender experiments
- `vypr_*` audio experiments
- `tiktok_upload.py`
- `check_veo_auth.py` and `fix_veo.py` (node_modules repairs)
- Buffer, getimg, and Upload-Post keys from the old `.env`
- The hardcoded 12:00 mp4 path

`pipeline.py` and `post_instagram.py` are still in the repo if you want a terminal batch. The console does not need them.

## Data on disk

| Path | Contents |
| --- | --- |
| `%LOCALAPPDATA%\vidrot\settings.json` | Key, password, schedule, dry-run flag |
| `%LOCALAPPDATA%\vidrot\session.json` | Instagram session after a successful login |
| `%LOCALAPPDATA%\vidrot\clips\` | Per-prompt mp4s |
| `%LOCALAPPDATA%\vidrot\reels\` | Stitched reels |
| `%LOCALAPPDATA%\vidrot\posters\` | Preview frames |
| `%LOCALAPPDATA%\vidrot\history.json` | What was posted |
| `%LOCALAPPDATA%\vidrot\logs\console.log` | Readable log |
| `%LOCALAPPDATA%\vidrot\bumpers\` | Optional intro mp4 |

On Linux or macOS the same tree is `~/.vidrot`, or whatever `VIDROT_DATA` points at.

## Tests and dry run

```bat
python -m unittest discover -s tests -v
```

The tests mock Veo and Instagram. They do not need a key. Dry run in the app is the same idea with real ffmpeg title cards, so you can watch the whole loop before spending quota.

## GitHub Actions

`.github/workflows/daily-pipeline.yml` runs the unit tests on pull requests and on pushes to `main`. It has no schedule and it does not commit prompts. A hosted runner is the wrong place for the Veo key, ffmpeg bumpers, and the Instagram session.

### Why the old daily job died

Every Actions run failed from the first one on 2026-06-17 (`27689212533`) through the last one on 2026-08-17 (`32036055230`). Prompt generation succeeded. The next step, "Commit generated prompts", exited 1.

`prompts/` and `output/` were in `.gitignore`, and the workflow ran `git add` on those paths. Git exits 1 when you add an ignored path. Nothing was committed, so the last real push stayed 2026-06-17.

Two more problems were behind that one. The workflow token was `contents: read`, so a push would have failed next. The push trigger included `config/**` while the job rewrote `config/trending_cache.json`, which would have started another run forever.

On 2026-08-17 GitHub set the workflow to `disabled_inactivity`. Scheduled runs do not count as activity, and this public repo had gone 60 days without a commit. The Instagram step did not cause the failures: it was hardcoded off. The poster also treated `clip_upload`'s Media object like a dict, and it invented a new device id on every launch. Both of those are fixed in `post_instagram.py` for the terminal tool, and the console uses the same session-file approach.

Do not re-enable that cron. The console is the daily driver. Merging this pull request does not turn the old schedule back on, and it should stay off.

## What only the owner can do

1. Install Python 3.11 (with the py launcher) and ffmpeg on the Windows PC, then `pip install -r requirements.txt` in this repo.
2. Put a **shortcut** to `windows\Start Vidrot.vbs` on the desktop, and optionally in the Startup folder if the scheduler should survive a reboot.
3. In Task Scheduler, confirm `\vidrot_pipeline` and `\vidrot_12pm_post` are disabled or deleted.
4. Paste the Gemini API key (the old `GEMINI_API_KEY`, from [aistudio.google.com](https://aistudio.google.com/apikey)) into Settings, then use Health → Test Veo key.
5. Instagram: copy the old `session.json` into `%LOCALAPPDATA%\vidrot\session.json`, or enter the password once and approve whatever checkpoint the phone shows. This app cannot finish that prompt for you.
6. Run one dry-run batch and watch the reel. Then turn Dry run off, render one real clip so you know the key still works, and only then turn the two schedule toggles on.
7. Merge the pull request when the console is the one you want on the machine. The GitHub cron should stay disabled.
