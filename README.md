# vidrot.ai

A private phone app for the daily loop: live trends, editable prompts, Google Veo clips, a branded reel, and an Instagram post. It runs on a small always-on server, so the PC can stay off.

Open it in the phone browser, sign in, and add it to the home screen. Setup, env vars, and the Fly.io deploy are in [RUNBOOK.md](RUNBOOK.md).

The scheduler runs inside the server. Dry run is on until you turn it off, so the first batch does not call Veo or Instagram. Clips use the Gemini `predictLongRunning` call. ffmpeg in the container stitches them. Settings and the Instagram session are encrypted on a persistent disk.

Expected hosting cost on Fly.io in Ashburn, as of October 2026: about **$8 to $10 a month** (a 1 GB shared CPU kept running, plus a 10 GB volume). Details are in the runbook.

```bash
python -m unittest discover -s tests -v
```

`windows/Start Vidrot.vbs` still starts a local copy with no console window. The cloud app is the one that posts while you are away from the desk.
