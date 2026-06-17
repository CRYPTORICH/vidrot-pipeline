#!/usr/bin/env python3
"""Trending topics scraper — Google Trends RSS → clean keyword list."""
import json, re, urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
CACHE_FILE = BASE / "config" / "trending_cache.json"


def scrape_trends(max_results=10):
    """Fetch current trending topics from Google Trends RSS."""
    topics = []
    try:
        url = "https://trends.google.com/trending/rss?geo=US"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read().decode("utf-8")
        # Extract titles (skip the feed title itself)
        titles = re.findall(r"<title>(.*?)</title>", data)
        topics = [t.strip()[:50] for t in titles[1:max_results + 1]]
        topics = [t for t in topics if len(t) > 3]
    except Exception as e:
        print(f"⚠️ Trend scrape failed: {e}")

    # Cache results
    cache = {
        "fetched_at": datetime.now().isoformat(),
        "source": "google_trends_rss",
        "trending": topics,
        "count": len(topics),
    }
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    return topics


def get_cached_trends():
    """Get cached trends if available, otherwise return defaults."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            data = json.load(f)
            topics = data.get("trending", [])
            if topics:
                return topics
    # Fallback defaults
    return [
        "AI REVOLUTION",
        "DIGITAL DETOX",
        "CRYPTO MEME COINS",
        "VIRTUAL REALITY METAVERSE",
        "CLIMATE TECH",
        "QUIET QUITTING",
        "BIOHACKING",
        "FAST FASHION EXPOSED",
        "ALGORITHM MANIPULATION",
        "REMOTE WORK BURNOUT",
    ]


def get_trends(force_fresh=False):
    """Get trends — try fresh first, fall back to cache, then defaults."""
    if force_fresh:
        topics = scrape_trends()
        if topics:
            return topics

    topics = get_cached_trends()
    if not force_fresh:
        # Try live, but don't block on it
        try:
            fresh = scrape_trends()
            if fresh:
                return fresh
        except:
            pass

    return topics if topics else get_cached_trends()


if __name__ == "__main__":
    topics = get_trends(force_fresh=True)
    print(f"✅ {len(topics)} trending topics:")
    for t in topics:
        print(f"  • {t}")
