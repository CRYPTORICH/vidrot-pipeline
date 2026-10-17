# vidrot.ai console

A local Windows app for the daily loop: live trends, editable interdimensional-cable prompts, Google Veo clips, a branded reel, and an Instagram post. The scheduler lives inside the app, so Task Scheduler does not flash a console window.

Open it with a double-click of `windows/Start Vidrot.vbs` (make a desktop shortcut to that file). It listens on `http://127.0.0.1:8765/` and does not open a terminal. Install steps, first-time Veo and Instagram setup, and how to retire the old scheduled tasks are in [RUNBOOK.md](RUNBOOK.md).

## What you do in the app

1. **Today** pulls trends and writes a batch you can still edit.
2. **Render clips** sends each prompt to Veo the same way the old `generate_veo_batch.py` script did: a Gemini `predictLongRunning` request. Dry run (on by default) makes local title cards instead, so nothing is billed.
3. **Stitch and brand** normalizes every clip to 1080×1920 and joins them.
4. **Post** uploads the reel with a saved Instagram session. A challenge or 2FA code is shown in the page instead of hanging a hidden window.
5. **Schedule** turns the 9:00 batch and 12:00 post on or off. Both run only while the app is open.
6. **Health** shows the Veo key, the Instagram session, ffmpeg, disk, the last run, and whether the OpenClaw gateway on port 18790 answers. The gateway is monitored. Clip generation does not go through it.

Settings and the Instagram session stay in `%LOCALAPPDATA%\vidrot` on Windows (or `~/.vidrot`). They are not committed.

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs that same suite on pull requests and on pushes to `main`. The old cron that wrote prompts from a hosted runner is retired: a runner cannot reach the Veo key, ffmpeg, or the Instagram session, and GitHub had already disabled that schedule for inactivity. The story of that failure is at the bottom of [RUNBOOK.md](RUNBOOK.md).

## Layout

```
Vidrot.pyw                  double-click entry (pythonw, no console)
windows/Start Vidrot.vbs   the shortcut the owner should pin
windows/Stop Vidrot.vbs    asks the app to exit, also with no console
console/                   local page and the HTTP server
vidrot/                    trends, prompts, Veo, branding, Instagram, scheduler
pipeline.py                the older prompt-only script, still usable from a terminal
post_instagram.py          the older poster, still usable from a terminal
```
