"""
All-time top organic Facebook / Instagram posts by views (excludes boosted/ads).
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent if (_HERE.parent / ".env").exists() and not (_HERE / ".env").exists() else _HERE
load_dotenv(_ROOT / ".env")

GRAPH = "v21.0"
BASE = f"https://graph.facebook.com/{GRAPH}"
TOP_N = 5
DEFAULT_MAX_SCAN = 500
_VIEW_WORKERS = 12


def _token() -> str:
    return (
        os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("META_USER_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("FB_ACCESS_TOKEN")
        or ""
    ).strip()


def _ad_account_id() -> str:
    raw = (os.getenv("META_AD_ACCOUNT_ID") or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def _graph(path: str, params: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=params, timeout=timeout)
    data = r.json()
    if not r.ok or data.get("error"):
        raise RuntimeError(json.dumps(data.get("error") or r.text)[:800])
    return data


def _normalize_permalink(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    parsed = urlparse(u)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _preview(text: str, max_len: int = 120) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return "(no text)"
    if len(s) > max_len:
        return s[: max_len - 1].rstrip() + "…"
    return s


def _resolve_fj() -> tuple[str, str, str]:
    tok = _token()
    if not tok:
        raise RuntimeError(
            "Set META_SYSTEM_USER_TOKEN or META_USER_ACCESS_TOKEN in .env."
        )
    pages = _graph(
        "me/accounts",
        {"fields": "id,name,access_token", "limit": 200, "access_token": tok},
    )
    for p in pages.get("data") or []:
        name = (p.get("name") or "").lower()
        if "five journeys" in name or "fivejourneys" in name:
            page_id = str(p["id"])
            page_token = str(p.get("access_token") or "")
            ig = _graph(
                page_id,
                {"fields": "instagram_business_account", "access_token": page_token},
            )
            ig_id = str((ig.get("instagram_business_account") or {}).get("id") or "")
            if not ig_id:
                raise RuntimeError("Five Journeys Page has no linked Instagram account.")
            return page_id, page_token, ig_id
    raise RuntimeError("Five Journeys Facebook Page not found for this token.")


def _extract_fb_post_ids_from_story_id(story_id: str) -> tuple[str, str]:
    sid = (story_id or "").strip()
    if not sid:
        return "", ""
    if "_" not in sid:
        return sid, ""
    head, tail = sid.split("_", 1)
    return sid, tail if head and tail else ""


def _fetch_paid_markers(token: str) -> dict[str, set[str]]:
    markers = {
        "fb_post_ids": set(),
        "ig_media_ids": set(),
        "ig_permalinks": set(),
    }
    acct = _ad_account_id()
    if not acct:
        return markers

    url = f"{BASE}/{acct}/adcreatives"
    params: dict[str, Any] = {
        "fields": (
            "id,object_story_id,effective_object_story_id,"
            "source_instagram_media_id,instagram_permalink_url"
        ),
        "limit": 200,
        "access_token": token,
    }
    pages = 0
    while url and pages < 100:
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if not r.ok or data.get("error"):
            break
        for c in data.get("data") or []:
            for key in ("object_story_id", "effective_object_story_id"):
                sid = str(c.get(key) or "").strip()
                full_id, leaf_id = _extract_fb_post_ids_from_story_id(sid)
                if full_id:
                    markers["fb_post_ids"].add(full_id)
                if leaf_id:
                    markers["fb_post_ids"].add(leaf_id)
            ig_mid = str(c.get("source_instagram_media_id") or "").strip()
            if ig_mid:
                markers["ig_media_ids"].add(ig_mid)
            ig_link = _normalize_permalink(str(c.get("instagram_permalink_url") or ""))
            if ig_link:
                markers["ig_permalinks"].add(ig_link)
        nxt = (data.get("paging") or {}).get("next")
        url = str(nxt) if nxt else ""
        params = {}
        pages += 1
    return markers


def _fb_post_views(post_id: str, token: str) -> int | None:
    for metric in ("post_media_view", "post_video_views", "post_impressions"):
        try:
            data = _graph(
                f"{post_id}/insights",
                {"metric": metric, "access_token": token},
                timeout=30,
            )
        except RuntimeError:
            continue
        for row in data.get("data") or []:
            if row.get("name") != metric:
                continue
            vals = row.get("values") or []
            if not vals:
                continue
            v = vals[0].get("value")
            if isinstance(v, dict):
                try:
                    return int(sum(float(x) for x in v.values() if x is not None))
                except (TypeError, ValueError):
                    continue
            if v is not None:
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    continue
    return None


def _ig_media_views(media_id: str, token: str) -> int | None:
    # Prefer total_value views (current Insights shape), then legacy names.
    try:
        data = _graph(
            f"{media_id}/insights",
            {
                "metric": "views",
                "metric_type": "total_value",
                "access_token": token,
            },
            timeout=30,
        )
        for row in data.get("data") or []:
            if row.get("name") != "views":
                continue
            tv = row.get("total_value") or {}
            if tv.get("value") is not None:
                return int(float(tv["value"]))
            vals = row.get("values") or []
            if vals and vals[0].get("value") is not None:
                return int(float(vals[0]["value"]))
    except RuntimeError:
        pass

    for metric in ("views", "plays", "video_views", "impressions"):
        try:
            data = _graph(
                f"{media_id}/insights",
                {"metric": metric, "access_token": token},
                timeout=30,
            )
        except RuntimeError:
            continue
        for row in data.get("data") or []:
            if row.get("name") != metric:
                continue
            vals = row.get("values") or []
            if vals and vals[0].get("value") is not None:
                try:
                    return int(float(vals[0]["value"]))
                except (TypeError, ValueError):
                    continue
    return None


def _list_facebook_posts(
    page_id: str, page_token: str, *, max_posts: int
) -> list[dict[str, Any]]:
    url = f"{BASE}/{page_id}/posts"
    params: dict[str, Any] = {
        "fields": "id,created_time,message,permalink_url,status_type",
        "limit": 100,
        "access_token": page_token,
    }
    acc: list[dict[str, Any]] = []
    while url and len(acc) < max_posts:
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if not r.ok or data.get("error"):
            raise RuntimeError(json.dumps(data.get("error") or r.text)[:500])
        for post in data.get("data") or []:
            acc.append(post)
            if len(acc) >= max_posts:
                break
        nxt = (data.get("paging") or {}).get("next")
        url = str(nxt) if nxt else ""
        params = {}
    return acc


def _list_instagram_media(
    ig_id: str, page_token: str, *, max_posts: int
) -> list[dict[str, Any]]:
    url = f"{BASE}/{ig_id}/media"
    params: dict[str, Any] = {
        "fields": (
            "id,caption,timestamp,permalink,media_type,media_product_type"
        ),
        "limit": 100,
        "access_token": page_token,
    }
    acc: list[dict[str, Any]] = []
    while url and len(acc) < max_posts:
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if not r.ok or data.get("error"):
            raise RuntimeError(json.dumps(data.get("error") or r.text)[:500])
        for m in data.get("data") or []:
            acc.append(m)
            if len(acc) >= max_posts:
                break
        nxt = (data.get("paging") or {}).get("next")
        url = str(nxt) if nxt else ""
        params = {}
    return acc


def _ig_type_label(media: dict[str, Any]) -> str:
    mpt = (media.get("media_product_type") or "").upper()
    mt = (media.get("media_type") or "").upper()
    if mpt == "REELS" or mt == "VIDEO" and "/reel/" in (media.get("permalink") or "").lower():
        return "Reel"
    if mt == "CAROUSEL_ALBUM":
        return "Carousel"
    if mt == "IMAGE":
        return "Image"
    if mt == "VIDEO":
        return "Video"
    return mpt or mt or "Post"


def fetch_top_organic_by_views(
    *,
    top_n: int = TOP_N,
    max_scan: int = DEFAULT_MAX_SCAN,
) -> dict[str, Any]:
    """
    Return top organic posts by lifetime views for Facebook and Instagram.

    Boosted/paid creatives linked in META_AD_ACCOUNT_ID are excluded.
    """
    user_tok = _token()
    page_id, page_token, ig_id = _resolve_fj()
    paid = _fetch_paid_markers(user_tok or page_token)

    fb_posts = _list_facebook_posts(page_id, page_token, max_posts=max_scan)
    ig_media = _list_instagram_media(ig_id, page_token, max_posts=max_scan)

    fb_paid = paid.get("fb_post_ids", set())
    ig_paid_ids = paid.get("ig_media_ids", set())
    ig_paid_links = paid.get("ig_permalinks", set())

    fb_rows: list[dict[str, Any]] = []
    fb_excluded = 0
    fb_candidates: list[dict[str, Any]] = []
    for post in fb_posts:
        pid = str(post.get("id") or "")
        leaf = pid.split("_")[-1] if pid else ""
        if pid in fb_paid or leaf in fb_paid:
            fb_excluded += 1
            continue
        created = pd.to_datetime(post.get("created_time"), utc=True, errors="coerce")
        fb_candidates.append(
            {
                "post_id": pid,
                "date": created,
                "preview": _preview(str(post.get("message") or "")),
                "type": str(post.get("status_type") or "post").replace("_", " "),
                "url": str(post.get("permalink_url") or ""),
            }
        )

    def _fb_job(item: dict[str, Any]) -> dict[str, Any] | None:
        views = _fb_post_views(item["post_id"], page_token)
        if views is None:
            return None
        return {**item, "views": views}

    with ThreadPoolExecutor(max_workers=_VIEW_WORKERS) as pool:
        futures = [pool.submit(_fb_job, item) for item in fb_candidates]
        for fut in as_completed(futures):
            row = fut.result()
            if row is not None:
                fb_rows.append(row)

    ig_rows: list[dict[str, Any]] = []
    ig_excluded = 0
    ig_candidates: list[dict[str, Any]] = []
    for media in ig_media:
        mid = str(media.get("id") or "")
        link = _normalize_permalink(str(media.get("permalink") or ""))
        if mid in ig_paid_ids or link in ig_paid_links:
            ig_excluded += 1
            continue
        created = pd.to_datetime(media.get("timestamp"), utc=True, errors="coerce")
        ig_candidates.append(
            {
                "post_id": mid,
                "date": created,
                "preview": _preview(str(media.get("caption") or "")),
                "type": _ig_type_label(media),
                "url": str(media.get("permalink") or ""),
            }
        )

    def _ig_job(item: dict[str, Any]) -> dict[str, Any] | None:
        views = _ig_media_views(item["post_id"], page_token)
        if views is None:
            return None
        return {**item, "views": views}

    with ThreadPoolExecutor(max_workers=_VIEW_WORKERS) as pool:
        futures = [pool.submit(_ig_job, item) for item in ig_candidates]
        for fut in as_completed(futures):
            row = fut.result()
            if row is not None:
                ig_rows.append(row)

    def _rank(rows: list[dict[str, Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(
                columns=["Rank", "Date", "Type", "Views", "Preview", "URL"]
            )
        frame = pd.DataFrame(rows).sort_values(
            ["views", "date"], ascending=[False, True]
        )
        top = frame.head(top_n).reset_index(drop=True)
        top.insert(0, "Rank", range(1, len(top) + 1))
        top["Date"] = top["date"].dt.strftime("%Y-%m-%d")
        top = top.rename(
            columns={
                "type": "Type",
                "views": "Views",
                "preview": "Preview",
                "url": "URL",
            }
        )
        return top[["Rank", "Date", "Type", "Views", "Preview", "URL"]]

    return {
        "facebook": _rank(fb_rows),
        "instagram": _rank(ig_rows),
        "meta": {
            "fb_scanned": len(fb_posts),
            "ig_scanned": len(ig_media),
            "fb_with_views": len(fb_rows),
            "ig_with_views": len(ig_rows),
            "fb_paid_excluded": fb_excluded,
            "ig_paid_excluded": ig_excluded,
            "max_scan": max_scan,
            "top_n": top_n,
        },
    }
