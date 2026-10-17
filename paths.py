"""Shared locations for the vidrot.ai pipeline."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def base_dir():
    """Directory that receives prompts, captions, and the trend cache.

    Defaults to the repo root. Set VIDROT_BASE to write somewhere else
    (useful for a local dry run that should not touch the checkout).
    """
    override = os.environ.get("VIDROT_BASE", "").strip()
    if override:
        return Path(override)
    return ROOT
