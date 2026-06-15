"""
Meta Marketing API client — fetch ad creative thumbnails by Ad ID.

Endpoint: https://graph.facebook.com/v19.0/<ad_id>?fields=creative{...}
Auth: User Access Token (60 days) or System User Token (no expire)
"""
from __future__ import annotations
import time
from typing import Iterable

import requests


GRAPH_API_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class MetaAPIError(Exception):
    pass


def _safe_get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def fetch_ad_creative(ad_id: str, access_token: str, timeout: float = 10) -> dict:
    """
    Fetch creative thumbnail + metadata for one ad.

    Returns:
        {
            "ad_id": str,
            "thumbnail_url": str | None,
            "image_url": str | None,
            "video_id": str | None,
            "video_url": str | None,   # if applicable
            "title": str | None,
            "body": str | None,
            "object_story_id": str | None,  # for permalink construction
            "error": str | None,
        }
    """
    if not ad_id:
        return {"ad_id": ad_id, "error": "empty ad_id"}

    url = f"{GRAPH_BASE}/{ad_id}"
    params = {
        "fields": (
            "creative{thumbnail_url,image_url,video_id,title,body,"
            "object_story_id,effective_object_story_id,"
            "asset_feed_spec{images,videos,titles,bodies}}"
        ),
        "access_token": access_token,
    }
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            err = r.json().get("error", {}) if r.text else {}
            return {
                "ad_id": ad_id,
                "error": err.get("message") or f"HTTP {r.status_code}",
                "error_code": err.get("code"),
            }
        data = r.json()
        creative = data.get("creative", {}) or {}

        # Fallback: try multiple image sources
        thumbnail = creative.get("thumbnail_url")
        image_url = creative.get("image_url")
        if not thumbnail and not image_url:
            # Try asset_feed_spec.images[0]
            images = _safe_get(creative, "asset_feed_spec", "images") or []
            if images and isinstance(images, list):
                first = images[0]
                if isinstance(first, dict):
                    image_url = first.get("url") or first.get("hash")

        video_id = creative.get("video_id")
        if not video_id:
            videos = _safe_get(creative, "asset_feed_spec", "videos") or []
            if videos and isinstance(videos, list):
                first_v = videos[0]
                if isinstance(first_v, dict):
                    video_id = first_v.get("video_id")

        return {
            "ad_id": ad_id,
            "thumbnail_url": thumbnail,
            "image_url": image_url or thumbnail,
            "video_id": video_id,
            "title": creative.get("title"),
            "body": (creative.get("body") or "")[:200] if creative.get("body") else None,
            "object_story_id": creative.get("object_story_id") or creative.get("effective_object_story_id"),
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {"ad_id": ad_id, "error": "timeout"}
    except requests.exceptions.RequestException as e:
        return {"ad_id": ad_id, "error": str(e)}


def fetch_creatives_bulk(ad_ids: Iterable[str], access_token: str, sleep_between: float = 0.05) -> dict[str, dict]:
    """Fetch creatives for many ads. Returns {ad_id: creative_dict}."""
    out = {}
    for ad_id in ad_ids:
        ad_id = str(ad_id).strip()
        if not ad_id or ad_id.lower() == "nan":
            continue
        out[ad_id] = fetch_ad_creative(ad_id, access_token)
        if sleep_between:
            time.sleep(sleep_between)
    return out


def fetch_ads_insights(ad_account_id: str, access_token: str,
                       start_date: str, end_date: str,
                       timeout: float = 30) -> list[dict]:
    """
    Fetch ad-level insights for date range. Returns list of ad rows.

    Args:
        ad_account_id: e.g. 'act_3022619417793545'
        start_date / end_date: 'YYYY-MM-DD'
    """
    if not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    url = f"{GRAPH_BASE}/{ad_account_id}/insights"
    fields = ",".join([
        "campaign_id", "campaign_name", "adset_id", "adset_name",
        "ad_id", "ad_name",
        "spend", "impressions", "reach", "clicks",
        "ctr", "cpc", "cpm", "frequency",
        "actions", "cost_per_action_type",
    ])
    params = {
        "fields": fields,
        "level": "ad",
        "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        "limit": 500,
        "access_token": access_token,
    }

    all_rows = []
    next_url = url
    next_params = params
    safety_loop = 20  # max 10K rows

    while next_url and safety_loop > 0:
        safety_loop -= 1
        try:
            r = requests.get(next_url, params=next_params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise MetaAPIError(f"Network error: {e}")
        if r.status_code != 200:
            err = r.json().get("error", {})
            raise MetaAPIError(err.get("message") or f"HTTP {r.status_code}")
        data = r.json()
        all_rows.extend(data.get("data", []))
        paging = data.get("paging", {})
        next_url = paging.get("next")
        next_params = None  # next URL already has params encoded

    return all_rows


def insights_to_dataframe_dict(rows: list[dict]) -> list[dict]:
    """Convert API insights rows to flat dicts compatible with analyze_ads()."""
    out = []
    for r in rows:
        spend = float(r.get("spend") or 0)
        impressions = int(float(r.get("impressions") or 0))
        clicks = int(float(r.get("clicks") or 0))
        ctr = float(r.get("ctr") or 0)
        reach = int(float(r.get("reach") or 0))

        # Extract leads/form fills from actions
        results = 0
        cost_per_result = 0.0
        result_type = "Link clicks"
        actions = r.get("actions") or []
        cost_actions = r.get("cost_per_action_type") or []
        # Priority: lead form > link clicks
        action_priorities = ["lead", "leadgen.other", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"]
        for ap in action_priorities:
            for a in actions:
                if a.get("action_type") == ap:
                    results = int(float(a.get("value") or 0))
                    result_type = "Leads (form)"
                    break
            if results:
                break
        if not results:
            # Fallback: link_click
            for a in actions:
                if a.get("action_type") == "link_click":
                    results = int(float(a.get("value") or 0))
                    result_type = "Link clicks"
                    break

        # Cost per result
        if results and spend:
            cost_per_result = spend / results

        out.append({
            "Campaign name": r.get("campaign_name", ""),
            "Ad set name": r.get("adset_name", ""),
            "Ad name": r.get("ad_name", ""),
            "Ad ID": r.get("ad_id", ""),
            "Result type": result_type,
            "Results": results,
            "Cost per result": cost_per_result,
            "Amount spent (VND)": spend,
            "Link clicks": clicks,
            "CTR (all)": ctr,
            "Impressions": impressions,
            "Reach": reach,
        })
    return out


def exchange_for_long_lived_token(app_id: str, app_secret: str, short_token: str, timeout: float = 10) -> dict:
    """Exchange short-lived user token (~1h) for long-lived (~60 days).

    Returns:
        {"ok": bool, "access_token": str, "expires_in": int, "error": str | None}
    """
    if not all([app_id, app_secret, short_token]):
        return {"ok": False, "error": "Thiếu App ID, App Secret hoặc token"}

    url = f"{GRAPH_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id.strip(),
        "client_secret": app_secret.strip(),
        "fb_exchange_token": short_token.strip(),
    }
    try:
        r = requests.get(url, params=params, timeout=timeout)
        data = r.json()
        if r.status_code != 200:
            err = data.get("error", {})
            return {"ok": False, "error": err.get("message") or f"HTTP {r.status_code}"}
        return {
            "ok": True,
            "access_token": data.get("access_token"),
            "expires_in": data.get("expires_in", 0),  # seconds
            "token_type": data.get("token_type"),
        }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": str(e)}


def verify_token(access_token: str, ad_account_id: str | None = None, timeout: float = 8) -> dict:
    """Quick health check: does token work + can it access ad account?"""
    # 1. Token basic check
    try:
        r = requests.get(
            f"{GRAPH_BASE}/me",
            params={"fields": "id,name", "access_token": access_token},
            timeout=timeout,
        )
        if r.status_code != 200:
            err = r.json().get("error", {})
            return {"ok": False, "error": err.get("message") or "Token invalid"}
        me = r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    result = {"ok": True, "user_id": me.get("id"), "user_name": me.get("name")}

    # 2. Ad account check (optional)
    if ad_account_id:
        try:
            r2 = requests.get(
                f"{GRAPH_BASE}/{ad_account_id}",
                params={"fields": "id,name,account_status", "access_token": access_token},
                timeout=timeout,
            )
            if r2.status_code == 200:
                acc = r2.json()
                result["ad_account_name"] = acc.get("name")
                result["ad_account_status"] = acc.get("account_status")
            else:
                err = r2.json().get("error", {})
                result["ad_account_error"] = err.get("message") or f"HTTP {r2.status_code}"
        except Exception as e:
            result["ad_account_error"] = str(e)

    return result
