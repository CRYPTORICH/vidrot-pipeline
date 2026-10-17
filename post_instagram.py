#!/usr/bin/env python3
"""
vidrot.ai Instagram poster.

Uploads vertical clips to @vidrot.ai with instagrapi. Login prefers a saved
session (same phone fingerprint) and falls back to a password login.

  python post_instagram.py --check
  python post_instagram.py --dry-run
  python post_instagram.py output/000_channel.mp4 "Your caption"
  python post_instagram.py --batch output/ --caption-file output/captions_batch.json

See RUNBOOK.md for every variable and where the session file comes from.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

from paths import ROOT

HASHTAGS = [
    "#vidrot", "#aiart", "#surreal", "#shorts", "#aivideo",
    "#interdimensional", "#glitchart", "#analoghorror", "#foundfootage",
    "#liminalspace", "#weirdcore", "#synthwave", "#vaporwave",
]

CHALLENGE_ERRORS = {
    "ChallengeRequired",
    "ChallengeError",
    "CaptchaChallengeRequired",
    "FeedbackRequired",
    "SentryBlock",
    "PleaseWaitFewMinutes",
}


def username():
    return os.getenv("IG_USERNAME", "vidrot.ai").strip() or "vidrot.ai"


def password():
    return os.getenv("IG_PASSWORD", "")


def session_candidates():
    """Places a previous login may have stored session.json."""
    paths = []
    explicit = os.getenv("IG_SESSION_FILE", "").strip()
    if explicit:
        paths.append(Path(explicit))
    paths.append(Path.home() / ".openclaw" / "instagram_sessions" / "session.json")
    paths.append(ROOT / "config" / "session.json")
    return paths


def session_save_path(loaded_from):
    explicit = os.getenv("IG_SESSION_FILE", "").strip()
    if explicit:
        return Path(explicit)
    if loaded_from and loaded_from != "IG_SESSION_JSON":
        return Path(loaded_from)
    if password() or os.getenv("IG_SESSIONID", "").strip():
        return ROOT / "config" / "session.json"
    return None


def describe_auth():
    """Which login methods are configured. Never includes secret values."""
    files = [str(path) for path in session_candidates() if path.exists()]
    return {
        "username": username(),
        "password": bool(password()),
        "session_files": files,
        "session_json": bool(os.getenv("IG_SESSION_JSON", "").strip()),
        "sessionid": bool(os.getenv("IG_SESSIONID", "").strip()),
        "verification_code": bool(os.getenv("IG_VERIFICATION_CODE", "").strip()),
    }


def auth_configured(info=None):
    info = info or describe_auth()
    return bool(
        info["password"]
        or info["session_files"]
        or info["session_json"]
        or info["sessionid"]
    )


def apply_saved_session(cl):
    """Load a session blob before login so the device fingerprint stays stable."""
    raw = os.getenv("IG_SESSION_JSON", "").strip()
    if raw:
        cl.set_settings(json.loads(raw))
        return "IG_SESSION_JSON"
    for path in session_candidates():
        if path.exists():
            cl.load_settings(path)
            return str(path)
    return None


def _persist_session(cl, loaded_from):
    dest = session_save_path(loaded_from)
    if dest is None:
        if loaded_from == "IG_SESSION_JSON":
            print("   Session was refreshed in memory only. Set IG_SESSION_FILE to save it.")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(dest)
    print(f"   Session saved to {dest}")


def login(cl):
    """Log in with a saved session, a session id, or a password. Returns True/False."""
    try:
        loaded_from = apply_saved_session(cl)
    except json.JSONDecodeError:
        print("❌ IG_SESSION_JSON is not valid JSON.")
        return False
    except Exception as exc:
        print(f"⚠️ Could not read the saved session: {exc}")
        loaded_from = None

    pwd = password()
    sessionid = os.getenv("IG_SESSIONID", "").strip()
    verification = os.getenv("IG_VERIFICATION_CODE", "").strip()

    if not pwd and not sessionid and not loaded_from:
        print("❌ No Instagram login configured.")
        print("   Set IG_PASSWORD, IG_SESSIONID, or IG_SESSION_FILE. Details: RUNBOOK.md")
        return False

    try:
        if pwd:
            cl.login(username(), pwd, verification_code=verification)
            print(f"✅ Logged in via password as {username()}")
        elif sessionid:
            cl.login_by_sessionid(sessionid)
            print("✅ Logged in via IG_SESSIONID")
        else:
            cl.get_timeline_feed()
            print(f"✅ Logged in via saved session ({loaded_from})")
    except Exception as exc:
        kind = type(exc).__name__
        if kind == "TwoFactorRequired":
            print("❌ Instagram is asking for a 2FA code.")
            print("   Set IG_VERIFICATION_CODE to the current 6-digit code and run again,")
            print("   or log in once on your own machine and reuse that session file.")
        elif kind in CHALLENGE_ERRORS or kind == "BadPassword":
            print(f"❌ Instagram refused the login ({kind}).")
            if kind == "BadPassword":
                print("   Check IG_USERNAME and IG_PASSWORD.")
            else:
                print("   Log in once in a normal browser as this account, approve the prompt,")
                print("   then create a session file locally: python post_instagram.py --dry-run")
                print("   GitHub-hosted runners often cannot finish that challenge.")
        else:
            print(f"❌ Login failed ({kind}): {str(exc)[:200]}")
        return False

    try:
        _persist_session(cl, loaded_from)
    except Exception as exc:
        print(f"⚠️ Logged in, but could not save the session: {exc}")
    return True


def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        print("❌ instagrapi is not installed. Run: pip install -r requirements.txt")
        return None

    cl = Client()
    cl.delay_range = [3, 8]
    return cl


def media_permalink(result):
    """clip_upload returns an instagrapi Media object, not a dict."""
    if result is None:
        return None
    if isinstance(result, dict):
        code = result.get("code") or ""
        pk = result.get("pk") or ""
    else:
        code = getattr(result, "code", "") or ""
        pk = getattr(result, "pk", "") or ""
    code = str(code)
    url = f"https://www.instagram.com/reel/{code}/" if code else ""
    return {"code": code, "pk": str(pk), "url": url}


def post_video(cl, video_path, caption):
    path = Path(video_path)
    if not path.exists():
        print(f"❌ Video not found: {path}")
        return None

    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"📤 Uploading: {path.name} ({file_size_mb:.1f} MB)")
    print(f"   Caption: {caption[:80]}...")

    try:
        result = cl.clip_upload(path, caption)
    except Exception as exc:
        kind = type(exc).__name__
        print(f"❌ Upload failed ({kind}): {str(exc)[:200]}")
        if kind in CHALLENGE_ERRORS:
            print("⚠️ Instagram is asking for verification. Approve it on the account, then retry.")
        return None

    posted = media_permalink(result)
    if not posted or not posted["code"]:
        print("❌ Upload returned no shortcode. The clip may not have published.")
        return None
    print(f"✅ POSTED! → {posted['url']}")
    return posted


def build_caption(prompt_data):
    channel = prompt_data.get("channel", "UNKNOWN").replace("_", " ").title()
    bumper = prompt_data.get("bumper", "Now broadcasting:")
    hashtags = " ".join(random.sample(HASHTAGS, min(5, len(HASHTAGS))))
    return f"{bumper}\n\n📺 {channel}\n\n{hashtags}"


def resolve_caption(video_path, captions):
    stem = Path(video_path).stem
    if stem in captions:
        return captions[stem]
    stripped = re.sub(r"^\d+_", "", stem)
    if stripped in captions:
        return captions[stripped]
    return build_caption({"channel": stripped or stem})


def post_delay_seconds():
    lo = int(os.getenv("IG_POST_DELAY_MIN", "300"))
    hi = int(os.getenv("IG_POST_DELAY_MAX", "900"))
    if hi < lo:
        lo, hi = hi, lo
    return random.randint(lo, hi)


def post_batch(batch_dir, caption_file=None, dry_run=False):
    """Upload every mp4 in batch_dir. Returns a process exit code."""
    batch_dir = Path(batch_dir)
    videos = sorted(batch_dir.glob("*.mp4"))
    if not videos and not dry_run:
        print(f"No mp4 clips in {batch_dir}. Nothing to post.")
        print("Generate the clips named in output/generate_instructions.txt, then rerun.")
        return 0

    info = describe_auth()
    if not auth_configured(info):
        print("❌ No Instagram login configured, and there are clips waiting.")
        print("   Set IG_PASSWORD or IG_SESSION_FILE. Details: RUNBOOK.md")
        return 1

    cl = get_client()
    if cl is None:
        return 1
    if not login(cl):
        return 1
    if dry_run:
        print(f"✅ Login verified. User id: {getattr(cl, 'user_id', '')}")
        return 0

    captions = {}
    if caption_file:
        captions = json.loads(Path(caption_file).read_text())

    failures = 0
    for i, video in enumerate(videos):
        caption = resolve_caption(video, captions)
        if post_video(cl, video, caption) is None:
            failures += 1
        if i < len(videos) - 1:
            delay = post_delay_seconds()
            print(f"⏳ Waiting {delay}s before the next post...")
            time.sleep(delay)

    if failures:
        print(f"❌ {failures} of {len(videos)} uploads failed.")
        return 1
    return 0


def print_auth_report():
    info = describe_auth()
    print("Instagram auth check (no network call):")
    print(f"  username:          {info['username']}")
    print(f"  password set:      {'yes' if info['password'] else 'no'}")
    print(f"  session JSON set:  {'yes' if info['session_json'] else 'no'}")
    print(f"  session id set:    {'yes' if info['sessionid'] else 'no'}")
    print(f"  2FA code set:      {'yes' if info['verification_code'] else 'no'}")
    if info["session_files"]:
        print("  session files:")
        for path in info["session_files"]:
            print(f"    {path}")
    else:
        print("  session files:     none found")
    if auth_configured(info):
        print("Ready to attempt a login (python post_instagram.py --dry-run).")
    else:
        print("Not ready. Add a password or a session file. See RUNBOOK.md.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="vidrot.ai Instagram Poster")
    parser.add_argument("video", nargs="?", help="Path to video file")
    parser.add_argument("caption", nargs="?", help="Caption text")
    parser.add_argument("--batch", help="Directory of mp4 clips")
    parser.add_argument("--caption-file", help="JSON file with captions")
    parser.add_argument("--dry-run", action="store_true", help="Test login only, don't post")
    parser.add_argument("--check", action="store_true", help="Show which auth is configured, no network")
    parser.add_argument("--verification-code", default="", help="Current 2FA code (or set IG_VERIFICATION_CODE)")
    args = parser.parse_args()

    if args.verification_code:
        os.environ["IG_VERIFICATION_CODE"] = args.verification_code

    if args.check:
        return print_auth_report()

    if args.batch:
        return post_batch(args.batch, args.caption_file, dry_run=args.dry_run)

    if args.dry_run or args.video:
        cl = get_client()
        if cl is None:
            return 1
        if not login(cl):
            return 1
        if args.dry_run and not args.video:
            print(f"✅ Login verified. User id: {getattr(cl, 'user_id', '')}")
            return 0
        caption = args.caption or build_caption({"channel": Path(args.video).stem})
        return 0 if post_video(cl, args.video, caption) else 1

    print("Usage: post_instagram.py --check")
    print("       post_instagram.py --dry-run")
    print("       post_instagram.py <video.mp4> [caption]")
    print("       post_instagram.py --batch <dir> --caption-file <captions.json>")
    return 1


if __name__ == "__main__":
    sys.exit(main())
