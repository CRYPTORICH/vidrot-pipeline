# vidrot.ai on your phone

The console runs in the cloud. Your phone is the screen. The PC does not need to be on, and the morning job does not flash a window.

Clips are the same Gemini Veo call the old scripts used (`veo-3.1-fast-generate-preview`, vertical, 8 seconds). ffmpeg in the container stitches them. Instagram uses a session you import. OpenClaw is off unless you turn the check on.

## What it costs

Host: **Fly.io**, one always-on machine in Ashburn (`iad`), plus a disk that survives deploys.

Prices below are from Fly's pricing page as of October 2026 ([fly.io/docs/about/pricing](https://fly.io/docs/about/pricing/)):

| Piece | Why | About |
| --- | --- | --- |
| `shared-cpu-1x` with 1 GB RAM, running all month | ffmpeg needs more than the 256 MB size | $6.70 |
| 10 GB volume | SQLite database, clips, reels | $1.50 |
| Shared IPv4 and HTTPS | Included with the app | $0 |
| Egress | A phone checking status and playing a few previews | usually under $1 |

**About $8 to $10 a month.** A 256 MB machine is cheaper ($2.19) and too small for 1080×1920 ffmpeg. Do not turn on auto-stop: a stopped machine does not run the scheduler. Veo itself is billed by Google, separate from this.

## Deploy

You do this once, from a terminal with the [flyctl](https://fly.io/docs/flyctl/install/) installed and `fly auth login` already done. This repo does not deploy itself.

```bash
git clone https://github.com/CRYPTORICH/vidrot-pipeline.git
cd vidrot-pipeline

# Pick another name if "vidrot" is taken, and put that name in fly.toml.
fly apps create vidrot
fly volumes create vidrot_data --region iad --size 10 --app vidrot

python -c "import secrets; print(secrets.token_urlsafe(32))"
fly secrets set \
  VIDROT_PASSWORD='a long password you will type on the phone' \
  VIDROT_SECRET_KEY='the token from the python command' \
  GEMINI_API_KEY='the Gemini key from aistudio.google.com' \
  IG_USERNAME='vidrot.ai' \
  VIDROT_TZ='America/New_York' \
  --app vidrot

fly deploy --app vidrot
```

`fly deploy` builds the Dockerfile (Python 3.12 and ffmpeg), starts one machine, and mounts the volume at `/data`. HTTPS is the `*.fly.dev` address Fly prints. Open that URL on the phone.

Changing `VIDROT_SECRET_KEY` later makes saved secrets unreadable. Set it once and leave it.

## Self-hosted on EC2 behind nginx/Cloudflare under a subpath

The live app is already on the owner's AWS EC2 box, not on Fly. Open it at `https://racksrewards.com/vidrot/` (the trailing slash matters). Cloudflare terminates HTTPS. nginx listens on port 80 and proxies `/vidrot/` to the app with that prefix stripped, so Python still sees `/`, `/api`, and `/static`.

| Piece | Value |
| --- | --- |
| pm2 process | `VIDROT` |
| Env file | `/home/ubuntu/.config/vidrot/vidrot.env` |
| Data directory | `/home/ubuntu/vidrot-data` |
| Listen address | `127.0.0.1:8765` |

The env file should set `VIDROT_HOST=127.0.0.1`, `VIDROT_PORT=8765`, `VIDROT_DATA=/home/ubuntu/vidrot-data`, `VIDROT_COOKIE_PATH=/vidrot`, plus `VIDROT_PASSWORD` and `VIDROT_SECRET_KEY`. The bind is loopback, so the process will start without a password and nginx would then expose an open console. `VIDROT_SECURE=1` and `VIDROT_TRUST_PROXY=1` keep the session cookie Secure and the lockout on the visitor IP. `VIDROT_COOKIE_PATH=/vidrot` stops that cookie from being sent to the rest of racksrewards.com.

Front-end URLs are relative to the page. At `https://racksrewards.com/vidrot/` they stay under `/vidrot/`. At `http://127.0.0.1:8765/` they stay at the root. Opening `https://racksrewards.com/vidrot` with no slash makes the browser request `/static/...` on the bare domain, which nginx does not send to this app.

Update the box from the repo checkout:

```bash
git pull
pip install -r requirements.txt
pm2 restart VIDROT --update-env
```

## Environment variables

Set these as Fly secrets. None of them belong in git.

| Name | Required | What it is |
| --- | --- | --- |
| `VIDROT_PASSWORD` | Yes, on a public URL | The single owner password. |
| `VIDROT_SECRET_KEY` | Yes, on a public URL | Encrypts the Gemini key, Instagram password, proxy, and session in the database. |
| `GEMINI_API_KEY` | For real clips | The old `GEMINI_API_KEY` / `GOOGLE_API_KEY`, from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| `IG_USERNAME` | No | Defaults to `vidrot.ai`. |
| `IG_PASSWORD` | Only if you do not import a session | Instagram password. The first successful login stores a session. |
| `IG_PROXY` | No | `http://user:pass@host:port` for a proxy you control. See the Instagram note below. |
| `VIDROT_TZ` | No | Clock for 09:00 and 12:00. Default in the app is `America/New_York`. |
| `VIDROT_COOKIE_PATH` | On a subpath | Cookie `Path`. Default `/`. On the EC2 host set `/vidrot`. |
| `VIDROT_VAPID_PUBLIC` / `VIDROT_VAPID_PRIVATE` | No | Closed-app alerts. Without them, the status bar in the app is the alert. |
| `VIDROT_VAPID_SUBJECT` | With the VAPID keys | `mailto:richybeats1@gmail.com` is a fine subject. |

Generate VAPID keys with `vapid --gen` after `pip install pywebpush`, then `fly secrets set` the two values. On the phone, Health → Allow alerts.

The app also reads `PORT` (Fly sets it) and stores data in `VIDROT_DATA` (`/data` in the image).

## Connect Instagram

Open the app, then the Instagram tab.

1. Type the Instagram username and password and tap **Connect**. The server logs in with instagrapi. The password is not written to git. A successful login stores an encrypted session.
2. If Instagram asks for a 6-digit code, type it on that same screen and tap **Submit code**.
3. If Instagram asks you to approve the login in the Instagram app, approve it there, then tap **I approved it**. A texted or emailed code can be submitted on that screen too.
4. The tab then shows the connected account and **Disconnect**.

Importing `session.json` is under that page as an advanced option. The old PC file is `C:\Users\dejes\.openclaw\instagram_sessions\session.json`.

Instagram often blocks a datacenter IP. If the connect step turns into a checkpoint or a refusal, put a proxy you control in the proxy field on that page and try again.

## First login

1. Open `https://<your-app>.fly.dev` on the phone.
2. Type `VIDROT_PASSWORD`.
3. Leave **Dry run** on.
4. Today → New batch. That pulls trends and writes prompts. Render clips makes title cards, not Veo videos. Stitch, then Post. History should say the post was saved and nothing was uploaded.

The status bar under the title stays visible on every page: working, failed, or the phase name. It updates every couple of seconds. A failed job stays on that bar instead of disappearing into a traceback.

## Add it to the home screen

The app is a PWA (manifest, icons, service worker).

- **iPhone:** Safari → Share → Add to Home Screen. Use Safari. Chrome on iOS will not install it.
- **Android:** Chrome → menu → Install app, or Add to Home screen.

Open it from the icon after that. It is a standalone window, still the same login.

## Veo key and Instagram session

If `GEMINI_API_KEY` is set on the host, Health shows the Veo key as saved. You can also paste a key under More → Settings. A blank field does not erase a saved key. Health → Test Veo key is the button that actually talks to Google.

Instagram, pick one:

1. **Import the session you already have.** On the PC, the old file is `C:\Users\dejes\.openclaw\instagram_sessions\session.json` (or `config\session.json`). Send that file to the phone (AirDrop, a private note, Files). Settings → Import session.json. The server encrypts it and does not keep a plaintext copy.
2. **Or** type the Instagram password in Settings and use Health → Test Instagram login.

A checkpoint comes back to the phone. The red notice says what Instagram asked for. Approve the prompt in the Instagram app, or type the code, then tap **I approved it — try again** on the Post page. The server does not hang waiting for a keyboard.

### Datacenter IPs

Google's API is used to being called from servers. Instagram is not. A login or upload from a Fly IP is a common reason for a checkpoint, a "we restricted this", or a forced password reset. Importing an old session reduces how often you send the password, and it does not make the IP look like a home connection.

Mitigation, if you want it: run a proxy you control (a small machine at home, or a Tailscale exit node) and put its URL in Settings as the Instagram proxy, or set `IG_PROXY`. Traffic to Instagram then leaves from that address. Leave it blank to post directly and deal with the checkpoint on the phone when it happens. This app cannot make a datacenter IP look like a phone.

## Schedule

Schedule times are in `VIDROT_TZ` (or the timezone saved in Settings). Morning batch defaults to 09:00 and does trends, render, and brand. Midday post defaults to 12:00 and posts the reel if it is still waiting. Both toggles start off. Days default to Monday–Saturday. Each job runs once per day, in a 10-minute window, and only while the Fly machine is up.

Turn them on after a dry run looks right. Then turn Dry run off when you want real Veo clips and a real upload.

## What is stored

On the volume (`/data`, which is `vidrot_data`):

| Path | Contents |
| --- | --- |
| `vidrot.db` | Encrypted settings, encrypted Instagram session, login sessions, the current run, history, schedule state |
| `clips/`, `reels/`, `posters/` | Video and preview frames |
| `logs/console.log` | The log shown in the app |
| `bumpers/` | Optional intro mp4, played first |

A redeploy keeps the volume. Deleting the volume deletes the session and the clips.

## Tests and dry run

```bash
pip install cryptography
python -m unittest discover -s tests -v
```

The tests mock Veo and Instagram. Dry run in the app is the same idea with real ffmpeg title cards.

## The Windows launcher

`windows/Start Vidrot.vbs` still starts a local server with no console window, for a dry run at the desk. It is not the daily driver. Do not turn the old Task Scheduler jobs back on (`\vidrot_pipeline` and `\vidrot_12pm_post`). They were disabled on 2026-06-17 because they flashed a console, and the noon job posted a file that is gone.

## GitHub Actions

`.github/workflows/daily-pipeline.yml` runs the unit tests. It has no schedule. The old cron died because `git add` hit gitignored `prompts/` and `output/`, then GitHub disabled the workflow for inactivity (last real run `32036055230` on 2026-08-17). Leave it disabled.

## What only you can do

1. `fly auth login`, create the app and the 10 GB volume, set the secrets, and `fly deploy`.
2. Choose a long `VIDROT_PASSWORD` and a `VIDROT_SECRET_KEY`, and keep the secret key. Rotating it locks you out of saved settings.
3. Put the Gemini key in Fly secrets or in Settings, then use Health → Test Veo key.
4. Import `session.json` from the PC, or enter the Instagram password and approve whatever the phone prompts.
5. Optionally point `IG_PROXY` at a proxy you control if Instagram keeps checkpointing the Fly IP.
6. Add the page to the home screen from the phone.
7. Run one dry run, turn Dry run off, then enable the two schedule toggles.
8. Confirm the old Windows tasks stay disabled.
