"""
Load Five Journeys Facebook / Instagram organic monthly history from
Digital Cross-Channel Tracker Google Sheets (2023–2026).

Metrics:
  reach group — views, reach, total followers
  engagement group — interactions, link_clicks, visits, new_followers
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_PATH = Path.home() / ".config" / "mcp-google-sheets" / "token.json"
SHEET_TAB = "Monthly Tracker"
# Column H = January in every tracker layout used here.
JAN_COL_INDEX = 7  # 0-based within the values grid when reading A:…

TRACKER_SHEETS: dict[int, str] = {
    2023: "1vwj-ckQauOn22pxlXdt6kh63OVvkFjQeFBqdJ0k2QZg",
    2024: "1T95rA_WCjY2RH-hu8uReMiLflvkQsXOI13Iev0csKtg",
    2025: "1oPIba48QuaDhfUP0l6JvoIAQYHQDPgU2JanerfsmYJM",
    2026: "1F7Lq0IBrOWolov5vEx5ztcBsZTbZCKfalQ1bwHuqakc",
}

METRIC_COLUMNS = [
    "views",
    "reach",
    "followers",
    "interactions",
    "link_clicks",
    "visits",
    "new_followers",
]


@dataclass(frozen=True)
class PlatformRows:
    """1-based sheet row numbers for Five Journeys organic metrics."""

    views: int | None = None
    reach: int | None = None
    followers: int | None = None
    interactions: int | None = None
    link_clicks: int | None = None
    visits: int | None = None
    new_followers: int | None = None


# Row maps differ by year as the Monthly Tracker evolved.
FB_ROWS: dict[int, PlatformRows] = {
    2023: PlatformRows(
        views=None,
        reach=12,
        followers=11,
        interactions=14,
        link_clicks=None,
        visits=10,
        new_followers=13,
    ),
    2024: PlatformRows(
        views=None,
        reach=12,
        followers=11,
        interactions=14,
        link_clicks=None,
        visits=10,
        new_followers=13,
    ),
    2025: PlatformRows(
        views=9,
        reach=13,
        followers=12,
        interactions=15,
        link_clicks=11,
        visits=10,
        new_followers=14,
    ),
    2026: PlatformRows(
        views=11,
        reach=12,
        followers=17,
        interactions=13,
        link_clicks=14,
        visits=15,
        new_followers=16,
    ),
}
IG_ROWS: dict[int, PlatformRows] = {
    2023: PlatformRows(
        views=37,
        reach=34,
        followers=36,
        interactions=39,
        link_clicks=None,
        visits=35,
        new_followers=38,
    ),
    2024: PlatformRows(
        views=30,
        reach=27,
        followers=29,
        interactions=32,
        link_clicks=None,
        visits=28,
        new_followers=31,
    ),
    2025: PlatformRows(
        views=31,
        reach=28,
        followers=30,
        interactions=33,
        link_clicks=34,
        visits=29,
        new_followers=32,
    ),
    2026: PlatformRows(
        views=35,
        reach=36,
        followers=41,
        interactions=37,
        link_clicks=38,
        visits=39,
        new_followers=40,
    ),
}


def _sheets_service():
    info = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(info, info["scopes"])
    return build("sheets", "v4", credentials=creds)


def _parse_number(raw: object) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"-", "--", "n/a", "N/A", "#N/A"}:
        return None
    text = text.replace(",", "").replace("%", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {".", "-", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _months_from_cells(
    cells: list[object], year: int
) -> dict[pd.Timestamp, float]:
    out: dict[pd.Timestamp, float] = {}
    for month in range(1, 13):
        idx = month - 1
        raw = cells[idx] if idx < len(cells) else None
        num = _parse_number(raw)
        if num is None:
            continue
        out[pd.Timestamp(year=year, month=month, day=1)] = num
    return out


def _fetch_year_grid(sheets, spreadsheet_id: str) -> list[list[object]]:
    """One Sheets read per workbook: Jan–Dec (H–S) for Meta block rows."""
    col_end = chr(ord("A") + JAN_COL_INDEX + 11)  # S
    col_start = chr(ord("A") + JAN_COL_INDEX)  # H
    # Cover FB + IG Five Journeys rows across all tracker layouts.
    rng = f"'{SHEET_TAB}'!{col_start}7:{col_end}45"
    return (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=rng)
        .execute()
        .get("values", [])
    )


def _row_cells(grid: list[list[object]], row: int) -> list[object]:
    """Map 1-based sheet row to cells inside the H7:S45 grid."""
    idx = row - 7
    if idx < 0 or idx >= len(grid):
        return []
    return list(grid[idx])


def _load_platform_year(
    *,
    year: int,
    grid: list[list[object]],
    rows: PlatformRows,
    platform: str,
) -> list[dict]:
    series: dict[str, dict[pd.Timestamp, float]] = {}
    for metric in METRIC_COLUMNS:
        row_num = getattr(rows, metric)
        if row_num is None:
            series[metric] = {}
        else:
            series[metric] = _months_from_cells(_row_cells(grid, row_num), year)

    months: set[pd.Timestamp] = set()
    for mapping in series.values():
        months |= set(mapping)
    records: list[dict] = []
    for month in sorted(months):
        rec: dict = {"month": month, "platform": platform}
        for metric in METRIC_COLUMNS:
            rec[metric] = series[metric].get(month)
        records.append(rec)
    return records


def load_meta_organic_trends(
    *,
    years: tuple[int, ...] = (2023, 2024, 2025, 2026),
) -> pd.DataFrame:
    """
    Monthly frame with columns:
    month, platform, views, reach, followers, interactions, link_clicks,
    visits, new_followers.
    """
    sheets = _sheets_service()
    rows_out: list[dict] = []
    for year in years:
        sid = TRACKER_SHEETS.get(year)
        if not sid:
            continue
        grid = _fetch_year_grid(sheets, sid)
        fb = FB_ROWS.get(year)
        ig = IG_ROWS.get(year)
        if fb:
            rows_out.extend(
                _load_platform_year(
                    year=year,
                    grid=grid,
                    rows=fb,
                    platform="Facebook",
                )
            )
        if ig:
            rows_out.extend(
                _load_platform_year(
                    year=year,
                    grid=grid,
                    rows=ig,
                    platform="Instagram",
                )
            )
    empty_cols = ["month", "platform", *METRIC_COLUMNS]
    if not rows_out:
        return pd.DataFrame(columns=empty_cols)
    df = pd.DataFrame(rows_out)
    df["month"] = pd.to_datetime(df["month"])
    today = pd.Timestamp.today().normalize().replace(day=1)
    df = df[df["month"] <= today].copy()
    return df.sort_values(["platform", "month"]).reset_index(drop=True)


def platform_frame(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.loc[df["platform"] == platform].copy()
