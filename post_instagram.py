#!/usr/bin/env python3
"""
vidrot.ai Instagram Poster
Posts generated content to @vidrot.ai using instagrapi.

Environment variables:
  IG_USERNAME=vidrot.ai (default)
  IG_PASSWORD=your_password (required — stored in GitHub Secrets)
  IG_SESSION_FILE=path to session.json (for cookie-based login)

Usage:
  python post_instagram.py video.mp4 "Your caption here"
  python post_instagram.py --batch batch_dir --caption-file captions.json
"""
import json, os, sys, time, random, argparse
from pathlib import Path

INSTAGRAM_USERNAME = os.getenv("IG_USERNAME", "vidrot.ai")
INSTAGRAM_PASSWORD = os.getenv("IG_PASSWORD", "")

# Default session paths (GitHub Actions vs local)
SESSION_PATHS = [
    Path(os.getenv("IG_SESSION_FILE", "")),
    Path.home() / ".openclaw" / "instagram_sessions" / "session.json",
    Path(__file__).parent / "config" / "session.json",
]

HASHTAGS = [
    "#vidrot", "#aiart", "#surreal", "#shorts", "#aivideo",
    "#interdimensional", "#glitchart", "#analoghorror", "#foundfootage",
    "#liminalspace", "#weirdcore", "#synthwave", "#vaporwave"
]


def get_client():
    """Create an instagrapi client with randomized device fingerprint."""
    try:
        from instagrapi import Client
    except ImportError:
        print("❌ instagrapi not installed. Run: pip install instagrapi")
        sys.exit(1)

    cl = Client()
    cl.delay_range = [3, 8]

    # Randomize device to avoid fingerprint blocking
    import uuid
    devices = [
        {"manufacturer": "Google", "device": "Pixel 8 Pro", "model": "husky", "dpi": "480dpi", "resolution": "1344x2992"},
        {"manufacturer": "Samsung", "device": "SM-G998B", "model": "p3s", "dpi": "480dpi", "resolution": "1344x2992"},
        {"manufacturer": "OnePlus", "device": "LE2123", "model": "OnePlus9Pro", "dpi": "480dpi", "resolution": "1440x3216"},
    ]
    device = random.choice(devices)

    cl.set_user_agent(
        f"Instagram 428.0.0.47.67 Android (30/11.0; {device['dpi']}; "
        f"{device['resolution']}; {device['manufacturer']}; {device['device']}; "
        f"{device['model']}; en_US; 961145276)"
    )
    cl.set_device({
        "app_version": "428.0.0.47.67",
        "android_version": 30,
        "android_release": "11.0",
        "manufacturer": device["manufacturer"],
        "device": device["device"],
        "model": device["model"],
        "dpi": device["dpi"],
        "resolution": device["resolution"],
        "cpu": device["model"],
        "uuid": str(uuid.uuid4()),
        "phone_id": str(uuid.uuid4()),
    })

    return cl


def login(cl):
    """Login using session file or credentials."""
    # Try session file first
    for session_path in SESSION_PATHS:
        if session_path and session_path.exists():
            try:
                session_data = json.loads(session_path.read_text())
                cl.set_settings(session_data)
                cl.get_timeline_feed()  # Validate session
                print(f"✅ Logged in via session: {session_path}")
                return True
            except Exception as e:
                print(f"⚠️ Session login failed: {e}")

    # Fall back to password login
    if INSTAGRAM_PASSWORD:
        try:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print(f"✅ Logged in via password as {INSTAGRAM_USERNAME}")
            # Save session for next time
            session_file = SESSION_PATHS[1]
            session_file.parent.mkdir(parents=True, exist_ok=True)
            cl.dump_settings(str(session_file))
            print(f"   Session saved to {session_file}")
            return True
        except Exception as e:
            print(f"❌ Password login failed: {e}")
            return False

    print("❌ No valid session or password found.")
    print("   Set IG_PASSWORD env var or provide IG_SESSION_FILE path.")
    return False


def post_video(cl, video_path, caption):
    """Upload a video to Instagram."""
    if not Path(video_path).exists():
        print(f"❌ Video not found: {video_path}")
        return None

    file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    print(f"📤 Uploading: {Path(video_path).name} ({file_size_mb:.1f} MB)")
    print(f"   Caption: {caption[:80]}...")

    try:
        result = cl.clip_upload(str(video_path), caption)
        code = result.get("code", "")
        pk = result.get("pk", "")
        url = f"https://www.instagram.com/p/{code}/"
        print(f"✅ POSTED! → {url}")
        return {"code": code, "pk": pk, "url": url}
    except Exception as e:
        error_name = type(e).__name__
        error_msg = str(e)[:200]
        print(f"❌ Upload failed ({error_name}): {error_msg}")

        if "feedback_required" in error_msg.lower() or "challenge" in error_msg.lower():
            print("⚠️ Instagram is asking for verification — may need manual login")

        return None


def build_caption(prompt_data):
    """Build a caption from prompt data."""
    channel = prompt_data.get("channel", "UNKNOWN").replace("_", " ").title()
    bumper = prompt_data.get("bumper", "Now broadcasting:")
    hashtags = " ".join(random.sample(HASHTAGS, min(5, len(HASHTAGS))))
    return f"{bumper}\n\n📺 {channel}\n\n{hashtags}"


def main():
    parser = argparse.ArgumentParser(description="vidrot.ai Instagram Poster")
    parser.add_argument("video", nargs="?", help="Path to video file")
    parser.add_argument("caption", nargs="?", help="Caption text")
    parser.add_argument("--batch", help="Batch directory with videos")
    parser.add_argument("--caption-file", help="JSON file with captions")
    parser.add_argument("--dry-run", action="store_true", help="Test login only, don't post")
    args = parser.parse_args()

    cl = get_client()

    if not login(cl):
        sys.exit(1)

    if args.dry_run:
        print(f"✅ Login verified — User ID: {cl.user_id}")
        sys.exit(0)

    if args.batch:
        batch_dir = Path(args.batch)
        captions = {}
        if args.caption_file:
            with open(args.caption_file) as f:
                captions = json.load(f)

        videos = sorted(batch_dir.glob("*.mp4"))
        for i, video in enumerate(videos):
            caption = captions.get(video.stem, build_caption({"channel": video.stem}))
            post_video(cl, video, caption)
            if i < len(videos) - 1:
                delay = random.randint(300, 900)  # 5-15 min between posts
                print(f"⏳ Waiting {delay}s before next post...")
                time.sleep(delay)

    elif args.video:
        caption = args.caption or build_caption({"channel": Path(args.video).stem})
        post_video(cl, args.video, caption)

    else:
        print("Usage: post_instagram.py <video.mp4> [caption]")
        print("       post_instagram.py --batch <dir> --caption-file <captions.json>")


if __name__ == "__main__":
    main()
