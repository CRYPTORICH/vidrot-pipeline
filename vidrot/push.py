"""Web Push when VAPID keys are set. In-app status works without them."""
import json
import os

from vidrot.db import get_json, put_json


def configured():
    return bool(os.environ.get("VIDROT_VAPID_PUBLIC", "").strip() and os.environ.get("VIDROT_VAPID_PRIVATE", "").strip())


def public_key():
    return os.environ.get("VIDROT_VAPID_PUBLIC", "").strip()


def add_subscription(folder, subscription):
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return False
    subs = get_json(folder, "push_subs", [])
    if not isinstance(subs, list):
        subs = []
    endpoint = subscription["endpoint"]
    subs = [item for item in subs if isinstance(item, dict) and item.get("endpoint") != endpoint]
    subs.append(subscription)
    put_json(folder, "push_subs", subs[-20:])
    return True


def notify(folder, title, body):
    if not configured():
        return {"ok": False, "skipped": True}
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return {"ok": False, "skipped": True, "error": "pywebpush is not installed"}
    subs = get_json(folder, "push_subs", [])
    if not isinstance(subs, list) or not subs:
        return {"ok": False, "skipped": True}
    subject = os.environ.get("VIDROT_VAPID_SUBJECT", "mailto:richybeats1@gmail.com")
    private = os.environ["VIDROT_VAPID_PRIVATE"].strip()
    payload = json.dumps({"title": title, "body": body})
    sent = 0
    kept = []
    for sub in subs:
        if not isinstance(sub, dict) or not sub.get("endpoint"):
            continue
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=private,
                vapid_claims={"sub": subject},
            )
            sent += 1
            kept.append(sub)
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                continue
            kept.append(sub)
        except Exception:
            kept.append(sub)
    put_json(folder, "push_subs", kept)
    return {"ok": sent > 0, "sent": sent}
