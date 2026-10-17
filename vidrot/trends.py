"""Live Google Trends, then the saved list, then built-in topics."""
import os

from vidrot.store import now_iso, read_json, write_json


def collect_trends(folder, geo="US"):
    os.environ["TRENDS_GEO"] = (geo or "US").strip() or "US"
    from trending import DEFAULT_TRENDS, fetch_rss, parse_trend_titles, trends_url

    cache = folder / "trending_cache.json"
    note = ""
    topics = []
    try:
        topics = parse_trend_titles(fetch_rss(trends_url()))
    except Exception as exc:
        note = f"Live trends failed ({exc}). Using the saved list."
    if topics:
        write_json(cache, {"fetched_at": now_iso(), "trending": topics})
        return topics, ""
    saved = read_json(cache, {}).get("trending") or []
    if saved:
        return saved, note or "Using the saved trend list."
    return list(DEFAULT_TRENDS), note or "Using the built-in topic list."
