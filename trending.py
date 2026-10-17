#!/usr/bin/env python3
"""Trending topics scraper — Google Trends RSS → clean keyword list."""
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

from paths import base_dir

DEFAULT_TRENDS = [
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


def trends_url():
    geo = os.environ.get("TRENDS_GEO", "US").strip() or "US"
    return f"https://trends.google.com/trending/rss?geo={geo}"


def cache_path():
    return base_dir() / "config" / "trending_cache.json"


def fetch_rss(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; vidrot-pipeline/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_trend_titles(xml_text, max_results=10):
    """Return trend titles only.

    News headlines live in <ht:news_item_title> and are not trends.
    A broken feed returns an empty list instead of raising.
    """
    titles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        titles = re.findall(r"<title>(.*?)</title>", xml_text)[1:]
    else:
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text)

    topics = []
    for title in titles:
        cleaned = unescape(str(title)).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)[:80]
        if len(cleaned) > 3:
            topics.append(cleaned)
        if len(topics) >= max_results:
            break
    return topics


def _write_cache(topics):
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "google_trends_rss",
        "trending": topics,
        "count": len(topics),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def scrape_trends(max_results=10, write_cache=True):
    """Fetch current trending topics. Returns [] on failure and does not wipe the cache."""
    try:
        xml_text = fetch_rss(trends_url())
        topics = parse_trend_titles(xml_text, max_results=max_results)
    except Exception as exc:
        print(f"⚠️ Trend scrape failed: {exc}")
        return []

    if topics and write_cache:
        _write_cache(topics)
    elif not topics:
        print("⚠️ Trend scrape returned no titles; keeping the previous cache")
    return topics


def get_cached_trends():
    """Last good cache, or the built-in defaults when the cache is missing or empty."""
    path = cache_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"⚠️ Trend cache unreadable: {exc}")
        else:
            topics = data.get("trending") or []
            if topics:
                return topics
    return list(DEFAULT_TRENDS)


def get_trends(force_fresh=False, write_cache=True):
    """Live trends, then the last good cache, then built-in defaults.

    force_fresh is accepted so older callers keep working. A failed live
    fetch always falls back; it never erases a good cache. write_cache=False
    is for a dry run that must not touch the checkout.
    """
    del force_fresh  # live fetch is always attempted; failure falls back
    topics = scrape_trends(write_cache=write_cache)
    if topics:
        return topics
    return get_cached_trends()


if __name__ == "__main__":
    topics = get_trends(force_fresh=True)
    print(f"✅ {len(topics)} trending topics:")
    for topic in topics:
        print(f"  • {topic}")
