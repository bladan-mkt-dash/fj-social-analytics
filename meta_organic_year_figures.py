"""
Organic Facebook and Instagram results for 2024, 2025, and 2026 year to date.

Meta's Reach total includes ad activity, and unique organic reach is no longer
returned. Organic views are displays that did not come from ads.

Facebook: page_media_view where is_from_ads is 0.
Instagram: account views minus Instagram ad impressions for the same dates.
Follower growth: change in follower count.
Organic posts: feed posts, reels, and carousels that were never used as an ad.
Stories are not included.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_EOM = _ROOT / "EOM Updates"
for path in (_HERE, _ROOT, _EOM):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Bound on first build. The published page only reads the JSON snapshot, so
# the public copy can import this module without the private fetch code.
epoch = graph = resolve_fj = token = None
BASE = _ad_account_id = _fetch_paid_markers = _normalize_permalink = None


def _bind_live() -> None:
    global epoch, graph, resolve_fj, token
    global BASE, _ad_account_id, _fetch_paid_markers, _normalize_permalink
    from _fetch_may_meta_tracker import epoch as epoch_
    from _fetch_may_meta_tracker import graph as graph_
    from _fetch_may_meta_tracker import resolve_fj as resolve_fj_
    from _fetch_may_meta_tracker import token as token_
    from meta_organic_top_views import BASE as base_
    from meta_organic_top_views import _ad_account_id as ad_account_id_
    from meta_organic_top_views import _fetch_paid_markers as fetch_paid_markers_
    from meta_organic_top_views import _normalize_permalink as normalize_permalink_

    epoch = epoch_
    graph = graph_
    resolve_fj = resolve_fj_
    token = token_
    BASE = base_
    _ad_account_id = ad_account_id_
    _fetch_paid_markers = fetch_paid_markers_
    _normalize_permalink = normalize_permalink_

LA = ZoneInfo("America/Los_Angeles")
THROUGH = date(2026, 11, 17)
YEARS = (2024, 2025, 2026)
SNAPSHOT_PATH = _HERE / "data" / "meta_organic_year_figures.json"


def _local_day(end_time: str) -> date:
    text = str(end_time).replace("Z", "+00:00")
    if text.endswith("+0000"):
        text = text[:-5] + "+00:00"
    ts = datetime.fromisoformat(text)
    return (ts - timedelta(seconds=1)).astimezone(LA).date()


def _year_of(day: date) -> int | None:
    if day.year not in YEARS or day > THROUGH:
        return None
    if day < date(day.year, 1, 1):
        return None
    return day.year


def _windows(start: datetime, end: datetime, days: int = 28):
    cur = start
    while cur < end:
        nxt = min(end, cur + timedelta(days=days))
        yield cur, nxt
        cur = nxt


def _blank() -> dict[int, int]:
    return {year: 0 for year in YEARS}


def _facebook_views(page_id: str, page_token: str) -> tuple[dict[int, int], dict[int, int], dict[str, int]]:
    organic = _blank()
    ads = _blank()
    months: dict[str, int] = {}
    start = datetime(2024, 1, 1, tzinfo=LA).astimezone(timezone.utc)
    end = datetime(2026, 11, 18, tzinfo=LA).astimezone(timezone.utc)
    for chunk_start, chunk_end in _windows(start, end):
        data = graph(
            f"{page_id}/insights",
            {
                "metric": "page_media_view",
                "period": "day",
                "breakdown": "is_from_ads",
                "since": epoch(chunk_start),
                "until": epoch(chunk_end) - 1,
                "access_token": page_token,
            },
        )
        for item in (data.get("data") or [{}])[0].get("values") or []:
            day = _local_day(str(item.get("end_time") or ""))
            year = _year_of(day)
            if year is None:
                continue
            value = int(item.get("value") or 0)
            key = f"{day.year}-{day.month:02d}"
            months[key] = months.get(key, 0) + value
            if str(item.get("is_from_ads")) == "1":
                ads[year] += value
            else:
                organic[year] += value
    return organic, ads, months


def _facebook_follower_stock(page_id: str, page_token: str, day: date) -> int | None:
    start = datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=LA)
    end = datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=LA)
    try:
        data = graph(
            f"{page_id}/insights",
            {
                "metric": "page_follows",
                "period": "day",
                "since": epoch(start.astimezone(timezone.utc)),
                "until": epoch(end.astimezone(timezone.utc)) - 1,
                "access_token": page_token,
            },
        )
    except RuntimeError as exc:
        print(f"FB follower stock {day} unavailable: {str(exc)[:160]}")
        return None
    for item in (data.get("data") or [{}])[0].get("values") or []:
        if _local_day(str(item.get("end_time") or "")) == day and item.get("value") is not None:
            return int(item["value"])
    return None


def _ig_total(ig_id: str, page_token: str, metric: str, start: datetime, end: datetime, *, breakdown: str | None = None) -> dict:
    params = {
        "metric": metric,
        "period": "day",
        "metric_type": "total_value",
        "since": epoch(start),
        "until": epoch(end) - 1,
        "access_token": page_token,
    }
    if breakdown:
        params["breakdown"] = breakdown
    return graph(f"{ig_id}/insights", params)


def _ig_views_by_year(ig_id: str, page_token: str) -> tuple[dict[int, int], dict[int, bool]]:
    """Sum account views inside each year so a chunk never crosses January 1."""
    totals = _blank()
    complete = {year: True for year in YEARS}
    ranges = {
        2024: (date(2024, 1, 1), date(2025, 1, 1)),
        2025: (date(2025, 1, 1), date(2026, 1, 1)),
        2026: (date(2026, 1, 1), date(2026, 11, 18)),
    }
    for year, (start_day, end_day) in ranges.items():
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=LA).astimezone(timezone.utc)
        end = datetime.combine(end_day, datetime.min.time(), tzinfo=LA).astimezone(timezone.utc)
        for chunk_start, chunk_end in _windows(start, end, days=28):
            try:
                data = _ig_total(ig_id, page_token, "views", chunk_start, chunk_end)
            except RuntimeError as exc:
                complete[year] = False
                print(f"IG views {year} {chunk_start.date()} skipped: {str(exc)[:160]}")
                continue
            value = ((data.get("data") or [{}])[0].get("total_value") or {}).get("value")
            if value is None:
                complete[year] = False
                continue
            totals[year] += int(value)
    return totals, complete


def _ig_follow_parts(
    ig_id: str, page_token: str
) -> tuple[dict[int, int], dict[int, int], dict[int, bool]]:
    follows = _blank()
    unfollows = _blank()
    complete = {year: True for year in YEARS}
    ranges = {
        2024: (date(2024, 1, 1), date(2025, 1, 1)),
        2025: (date(2025, 1, 1), date(2026, 1, 1)),
        2026: (date(2026, 1, 1), date(2026, 11, 18)),
    }
    for year, (start_day, end_day) in ranges.items():
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=LA).astimezone(timezone.utc)
        end = datetime.combine(end_day, datetime.min.time(), tzinfo=LA).astimezone(timezone.utc)
        for chunk_start, chunk_end in _windows(start, end, days=28):
            try:
                data = _ig_total(
                    ig_id,
                    page_token,
                    "follows_and_unfollows",
                    chunk_start,
                    chunk_end,
                    breakdown="follow_type",
                )
            except RuntimeError as exc:
                complete[year] = False
                print(f"IG follows {year} {chunk_start.date()} skipped: {str(exc)[:160]}")
                continue
            blocks = ((data.get("data") or [{}])[0].get("total_value") or {}).get("breakdowns") or []
            for block in blocks:
                for result in block.get("results") or []:
                    dims = [str(x).upper() for x in (result.get("dimension_values") or [])]
                    value = int(float(result.get("value") or 0))
                    if "NON_FOLLOWER" in dims:
                        unfollows[year] += value
                    elif "FOLLOWER" in dims:
                        follows[year] += value
    return follows, unfollows, complete


def _ad_impressions(user_token: str) -> dict[str, dict[int, int]]:
    acct = _ad_account_id()
    out = {"facebook": _blank(), "instagram": _blank()}
    if not acct:
        return out
    ranges = {
        2024: ("2024-01-01", "2024-12-31"),
        2025: ("2025-01-01", "2025-12-31"),
        2026: ("2026-01-01", "2026-11-17"),
    }
    for year, (since, until) in ranges.items():
        data = graph(
            f"{acct}/insights",
            {
                "fields": "impressions",
                "level": "account",
                "breakdowns": "publisher_platform",
                "time_range": json.dumps({"since": since, "until": until}),
                "access_token": user_token,
            },
        )
        for row in data.get("data") or []:
            platform = str(row.get("publisher_platform") or "")
            if platform not in out:
                continue
            out[platform][year] += int(float(row.get("impressions") or 0))
    return out


def _tracker_frame() -> pd.DataFrame:
    from meta_organic_trends_data import load_meta_organic_trends_from_sheets

    return load_meta_organic_trends_from_sheets(years=(2023, 2024, 2025, 2026))


def _sheet_followers(frame: pd.DataFrame) -> dict[str, dict[date, int]]:
    out: dict[str, dict[date, int]] = {"Facebook": {}, "Instagram": {}}
    for rec in frame.to_dict("records"):
        platform = str(rec.get("platform") or "")
        followers = rec.get("followers")
        if platform not in out or followers is None or pd.isna(followers):
            continue
        month = pd.Timestamp(rec["month"])
        end = (month + pd.offsets.MonthEnd(0)).date()
        out[platform][end] = int(followers)
    return out


def _growth_from_stock(stock: dict[date, int], start: date, end: date) -> int | None:
    if start not in stock or end not in stock:
        return None
    return stock[end] - stock[start]


def _count_organic_posts(page_id: str, page_token: str, ig_id: str) -> dict[str, dict[int, int]]:
    paid = _fetch_paid_markers(token() or page_token)
    counts = {"Facebook": _blank(), "Instagram": _blank()}
    cutoff = datetime(2024, 1, 1, tzinfo=LA)

    url = f"{BASE}/{page_id}/posts"
    params: dict = {
        "fields": "id,created_time",
        "limit": 100,
        "access_token": page_token,
    }
    while url:
        response = requests.get(url, params=params, timeout=120)
        data = response.json()
        if not response.ok or data.get("error"):
            raise RuntimeError(json.dumps(data)[:500])
        oldest = None
        for post in data.get("data") or []:
            raw = post.get("created_time")
            if not raw:
                continue
            ts = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
            if oldest is None or ts < oldest:
                oldest = ts
            local = ts.astimezone(LA).date()
            year = _year_of(local)
            if year is None:
                continue
            pid = str(post.get("id") or "")
            leaf = pid.split("_")[-1] if "_" in pid else ""
            if pid in paid["fb_post_ids"] or (leaf and leaf in paid["fb_post_ids"]):
                continue
            counts["Facebook"][year] += 1
        url = (data.get("paging") or {}).get("next") or ""
        params = {}
        if oldest and oldest < cutoff:
            break

    url = f"{BASE}/{ig_id}/media"
    params = {
        "fields": "id,timestamp,permalink",
        "limit": 100,
        "access_token": page_token,
    }
    while url:
        response = requests.get(url, params=params, timeout=120)
        data = response.json()
        if not response.ok or data.get("error"):
            raise RuntimeError(json.dumps(data)[:500])
        oldest = None
        for media in data.get("data") or []:
            raw = media.get("timestamp")
            if not raw:
                continue
            ts = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
            if oldest is None or ts < oldest:
                oldest = ts
            local = ts.astimezone(LA).date()
            year = _year_of(local)
            if year is None:
                continue
            mid = str(media.get("id") or "")
            link = _normalize_permalink(str(media.get("permalink") or ""))
            if mid in paid["ig_media_ids"] or (link and link in paid["ig_permalinks"]):
                continue
            counts["Instagram"][year] += 1
        url = (data.get("paging") or {}).get("next") or ""
        params = {}
        if oldest and oldest < cutoff:
            break
    return counts


def _missing_months(month_totals: dict[str, int], year: int) -> list[str]:
    last_month = 12 if year < 2026 else 11
    missing = []
    for month in range(1, last_month + 1):
        key = f"{year}-{month:02d}"
        if month_totals.get(key, 0) <= 0:
            missing.append(key)
    return missing


def build_year_figures() -> dict:
    _bind_live()
    page_id, page_token, ig_id = resolve_fj()
    user_token = token()
    print("Fetching Facebook organic and ad views…")
    fb_organic, fb_ads, fb_months = _facebook_views(page_id, page_token)
    print("Fetching Facebook follower counts…")
    fb_stock_days = {
        "2023-12-31": _facebook_follower_stock(page_id, page_token, date(2023, 12, 31)),
        "2024-12-31": _facebook_follower_stock(page_id, page_token, date(2024, 12, 31)),
        "2025-12-31": _facebook_follower_stock(page_id, page_token, date(2025, 12, 31)),
        "2026-11-17": _facebook_follower_stock(page_id, page_token, date(2026, 11, 17)),
    }
    print("Fetching Instagram views and follows…")
    ig_views, ig_views_complete = _ig_views_by_year(ig_id, page_token)
    ig_follows, ig_unfollows, ig_follows_complete = _ig_follow_parts(ig_id, page_token)
    print("Fetching ad impressions…")
    ad_impressions = _ad_impressions(user_token)
    print("Reading follower history from the tracker…")
    tracker = _tracker_frame()
    sheet = _sheet_followers(tracker)
    print("Counting organic posts…")
    posts = _count_organic_posts(page_id, page_token, ig_id)

    fb_growth = {
        2024: None
        if fb_stock_days["2023-12-31"] is None or fb_stock_days["2024-12-31"] is None
        else fb_stock_days["2024-12-31"] - fb_stock_days["2023-12-31"],
        2025: None
        if fb_stock_days["2024-12-31"] is None or fb_stock_days["2025-12-31"] is None
        else fb_stock_days["2025-12-31"] - fb_stock_days["2024-12-31"],
        2026: None
        if fb_stock_days["2025-12-31"] is None or fb_stock_days["2026-11-17"] is None
        else fb_stock_days["2026-11-17"] - fb_stock_days["2025-12-31"],
    }
    # Sheet end-of-month counts are the backup when a Page follows point is missing.
    sheet_fb = sheet["Facebook"]
    sheet_ig = sheet["Instagram"]
    if fb_growth[2024] is None:
        fb_growth[2024] = _growth_from_stock(sheet_fb, date(2023, 12, 31), date(2024, 12, 31))
    if fb_growth[2025] is None:
        fb_growth[2025] = _growth_from_stock(sheet_fb, date(2024, 12, 31), date(2025, 12, 31))
    if fb_growth[2026] is None and date(2025, 12, 31) in sheet_fb and fb_stock_days["2026-11-17"] is not None:
        fb_growth[2026] = fb_stock_days["2026-11-17"] - sheet_fb[date(2025, 12, 31)]

    ig_growth = {
        2024: _growth_from_stock(sheet_ig, date(2023, 12, 31), date(2024, 12, 31)),
        2025: _growth_from_stock(sheet_ig, date(2024, 12, 31), date(2025, 12, 31)),
        2026: (ig_follows[2026] - ig_unfollows[2026]) if ig_follows_complete[2026] else None,
    }

    fb_organic_out: dict[int, int | None] = {}
    fb_missing: dict[int, list[str]] = {}
    for year in YEARS:
        missing = _missing_months(fb_months, year)
        fb_missing[year] = missing
        # Zero months add nothing, so the sum is only the months Meta recorded.
        fb_organic_out[year] = fb_organic[year]

    ig_organic: dict[int, int | None] = {}
    ig_view_source: dict[int, str] = {}
    for year in YEARS:
        paid = ad_impressions["instagram"][year]
        if ig_views_complete[year] and ig_views[year] > 0:
            net = ig_views[year] - paid
            ig_organic[year] = net if net >= 0 else None
            ig_view_source[year] = "api" if net >= 0 else "ads_exceed_views"
            continue
        # Tracker "views" for older years are not the same series as current
        # account views, so they are not subtracted from ad impressions.
        ig_organic[year] = None
        ig_view_source[year] = "unavailable"

    footnotes = [
        "Organic views count displays, not unique people. Meta no longer returns a unique organic reach number, and the Reach total in Meta includes ads.",
        "Facebook organic views are page views that were not from an ad. Months Meta did not record are left out of that year.",
        "Instagram does not split account views into organic and ads. Organic views are account views minus Instagram ad impressions for the same dates.",
        "Follower growth is the change in follower count. Facebook uses the Page follows total. Instagram 2024 and 2025 use the tracker’s December counts. Instagram 2026 is follows minus unfollows from January 1 through November 17.",
        "Organic posts are feed posts, reels, and carousels published in the year that were never used as an ad. Stories are not included.",
        "2026 is January 1 through November 17. Today is left out.",
    ]
    for year, missing in fb_missing.items():
        if missing:
            footnotes.append(
                f"Facebook view history has no data for {', '.join(missing)}. "
                f"The {year} organic-views figure is the other months only."
            )
    for year, source in ig_view_source.items():
        if source == "unavailable":
            footnotes.append(f"Instagram organic views are not available for {year}.")
        elif source == "ads_exceed_views":
            footnotes.append(
                f"Instagram ad impressions were higher than account views in {year}, so organic views are not shown."
            )

    def row(platform: str, metric: str, values: dict[int, int | None]) -> dict:
        return {
            "platform": platform,
            "metric": metric,
            "2024": values.get(2024),
            "2025": values.get(2025),
            "2026": values.get(2026),
        }

    rows = [
        row("Facebook", "Organic views", fb_organic_out),
        row("Facebook", "Follower growth", fb_growth),
        row("Facebook", "Organic posts published", posts["Facebook"]),
        row("Instagram", "Organic views", {year: ig_organic[year] for year in YEARS}),
        row("Instagram", "Follower growth", ig_growth),
        row("Instagram", "Organic posts published", posts["Instagram"]),
    ]
    combined = []
    for metric in ("Organic views", "Follower growth", "Organic posts published"):
        values = {}
        for year_key in ("2024", "2025", "2026"):
            parts = [item[year_key] for item in rows if item["metric"] == metric]
            values[year_key] = None if any(part is None for part in parts) else sum(parts)
        combined.append(
            {
                "platform": "Facebook + Instagram",
                "metric": metric,
                "2024": values["2024"],
                "2025": values["2025"],
                "2026": values["2026"],
            }
        )
    rows.extend(combined)

    payload = {
        "through": THROUGH.isoformat(),
        "timezone": "America/Los_Angeles",
        "generated_at": datetime.now(LA).isoformat(timespec="seconds"),
        "rows": rows,
        "footnotes": footnotes,
        "debug": {
            "facebook_ad_views": fb_ads,
            "facebook_follower_stock": {k: v for k, v in fb_stock_days.items()},
            "facebook_month_views_organic_plus_ads": fb_months,
            "instagram_account_views": ig_views,
            "instagram_views_complete": ig_views_complete,
            "instagram_view_source": ig_view_source,
            "instagram_ad_impressions": ad_impressions["instagram"],
            "instagram_follows": ig_follows,
            "instagram_unfollows": ig_unfollows,
            "instagram_follows_complete": ig_follows_complete,
        },
    }
    return payload


def write_snapshot(payload: dict) -> Path:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stored = {key: payload[key] for key in ("through", "timezone", "generated_at", "rows", "footnotes")}
    SNAPSHOT_PATH.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    return SNAPSHOT_PATH


def load_year_figures() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def main() -> int:
    payload = build_year_figures()
    path = write_snapshot(payload)
    print(f"Wrote {path}")
    for item in payload["rows"]:
        print(
            f"{item['platform']:24} {item['metric']:28} "
            f"{item['2024']}  {item['2025']}  {item['2026']}"
        )
    print("--- debug ---")
    debug = payload["debug"]
    print("fb ad views", debug["facebook_ad_views"])
    print("fb stock", debug["facebook_follower_stock"])
    print("ig account views", debug["instagram_account_views"])
    print("ig ad impressions", debug["instagram_ad_impressions"])
    print("ig follows", debug["instagram_follows"], "unfollows", debug["instagram_unfollows"])
    missing = [note for note in payload["footnotes"] if note.startswith("Facebook views history")]
    for note in missing:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
