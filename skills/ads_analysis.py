"""
Skill: Ads Analysis (Meta paid ads)
Input: Meta Ads Manager CSV export + optional W1 actuals dict
Output: HTML report (string)

Categorization rules:
- BU 2 | COLD LEAD campaign + ad set RTM/Trade/Data -> Cold lead per khoa
- Trade 30/Trade 32/TRADE 32 campaigns -> Trade Hot
- RTM 09 campaign -> RTM Hot
- (Data Hot: no campaign in MVP scope)
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape


CATEGORIES_HOT = ["Trade Hot", "RTM Hot", "Data Hot", "AOP Hot", "Finance Hot", "Brand Hot", "KAM Hot", "Ecom Hot"]
CATEGORIES_COLD = ["Trade Cold", "RTM Cold", "Data Cold", "AOP Cold", "Finance Cold", "Brand Cold", "KAM Cold", "Ecom Cold"]
CATEGORIES = CATEGORIES_HOT + CATEGORIES_COLD


def categorize_ad(campaign: str, adset: str) -> str | None:
    """Return category label or None if out of scope."""
    campaign = str(campaign or "")
    adset = str(adset or "").strip()
    adset_low = adset.lower()
    campaign_up = campaign.upper()
    campaign_low = campaign.lower()

    # Cold lead: BU X | COLD LEAD or "cold lead" patterns
    if ("COLD LEAD" in campaign_up) or ("BU1 - COLD LEAD" in campaign_up) or campaign_low.startswith("bu1 - cold"):
        # Map ad set name to khoá
        if adset_low in ("rtm",):
            return "RTM Cold"
        if adset_low == "trade":
            return "Trade Cold"
        if adset_low == "data":
            return "Data Cold"
        if adset_low in ("aop", "aop - mkter", "aop - chủ dn", "aop - chu dn"):
            return "AOP Cold"
        if "brand" in adset_low:
            return "Brand Cold"
        if "finance" in adset_low or "fin" in adset_low:
            return "Finance Cold"
        if "kam" in adset_low:
            return "KAM Cold"
        if "ecom" in adset_low:
            return "Ecom Cold"
        return None

    # Hotlead — match campaign name to khoá
    if re.search(r"\bTRADE\s+\d", campaign_up):
        return "Trade Hot"
    if re.search(r"\bRTM\s+\d", campaign_up):
        return "RTM Hot"
    if "KAM" in campaign_up and ("LEAD" in campaign_up or "FORM" in campaign_up):
        return "KAM Hot"
    if "ECOM" in campaign_up and ("LEAD" in campaign_up or "FORM" in campaign_up or "KHTN" in campaign_up):
        return "Ecom Hot"
    if re.search(r"\bAOP\b", campaign_up):
        return "AOP Hot"
    if re.search(r"\bFINANCE\b|\bFIN\s+\d", campaign_up):
        return "Finance Hot"
    if re.search(r"\bBRAND\b", campaign_up):
        return "Brand Hot"

    return None  # Out of scope


def _safe_num(val) -> float:
    try:
        v = pd.to_numeric(val, errors="coerce")
        if pd.isna(v):
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _safe_int(val) -> int:
    return int(_safe_num(val))


def analyze_ads(df: pd.DataFrame, actuals: dict | None = None, focus_khoa: list[str] | None = None, creatives: dict | None = None) -> dict:
    """
    Analyze Meta Ads CSV.

    Args:
        df: DataFrame from CSV
        actuals: dict with actuals per khoa
        focus_khoa: list of khoá to include (filter by BU). None = all 8.
        creatives: optional {ad_id: {thumbnail_url, image_url, ...}} from Meta API.

    Returns:
        dict with structure for Jinja template
    """
    if focus_khoa is None:
        from .bu_config import ALL_KHOA
        focus_khoa = ALL_KHOA
    actuals = actuals or {}
    creatives = creatives or {}
    df = df.copy()

    required_cols = ["Campaign name", "Ad set name", "Ad name"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"Thiếu cột bắt buộc: {c}")

    df["Category"] = df.apply(
        lambda r: categorize_ad(r.get("Campaign name"), r.get("Ad set name")),
        axis=1,
    )
    in_scope = df[df["Category"].notna()].copy()

    # Group ads by category
    groups: dict[str, dict] = {}
    for cat in CATEGORIES:
        sub = in_scope[in_scope["Category"] == cat]
        ads = []
        for _, r in sub.iterrows():
            spent = _safe_num(r.get("Amount spent (VND)"))
            clicks = _safe_int(r.get("Link clicks"))
            results = _safe_int(r.get("Results"))
            impressions = _safe_int(r.get("Impressions"))
            ctr = _safe_num(r.get("CTR (all)"))
            cpr = _safe_num(r.get("Cost per result"))
            video_50 = _safe_int(r.get("Video plays at 50%"))
            reach = _safe_int(r.get("Reach"))
            ad_name = str(r.get("Ad name", "")).strip() or "(no name)"

            # Derived per-ad KPIs
            cpm = (spent / impressions * 1000) if impressions else 0.0
            cpc = (spent / clicks) if clicks else 0.0
            click_to_result_cr = (results / clicks * 100) if clicks else 0.0
            frequency = (impressions / reach) if reach else 0.0
            video_50_rate = (video_50 / impressions * 100) if impressions else 0.0

            # Optimization signal — diagnose what's wrong
            opt_signal = []
            if spent >= 50000 and results == 0:
                opt_signal.append("burn-no-result")
            if ctr < 1.0 and impressions >= 1000:
                opt_signal.append("low-ctr")
            if click_to_result_cr > 0 and click_to_result_cr < 1.5 and clicks >= 50:
                opt_signal.append("low-conv-after-click")
            if cpm > 100000 and impressions >= 500:
                opt_signal.append("high-cpm")
            if ctr >= 3.0 and click_to_result_cr < 2.0 and clicks >= 50:
                opt_signal.append("ctr-good-conv-bad")

            # Ad ID (if present in CSV) → lookup creative
            ad_id_raw = r.get("Ad ID") or r.get("Ad id") or r.get("ad_id") or r.get("Ad_ID")
            ad_id = str(ad_id_raw).strip() if ad_id_raw is not None and str(ad_id_raw).strip().lower() not in ("nan", "") else None
            creative = creatives.get(ad_id, {}) if ad_id else {}
            thumbnail_url = creative.get("thumbnail_url") or creative.get("image_url")
            object_story_id = creative.get("object_story_id")
            permalink = None
            if object_story_id and "_" in object_story_id:
                permalink = f"https://www.facebook.com/{object_story_id.split('_')[0]}/posts/{object_story_id.split('_')[1]}"

            ads.append({
                "campaign": str(r.get("Campaign name", "")),
                "adset": str(r.get("Ad set name", "")),
                "ad_name": ad_name,
                "ad_id": ad_id,
                "thumbnail_url": thumbnail_url,
                "permalink": permalink,
                "result_type": str(r.get("Result type", "") or ""),
                "results": results,
                "cpr": cpr,
                "spent": spent,
                "clicks": clicks,
                "ctr": ctr,
                "impressions": impressions,
                "reach": reach,
                "frequency": frequency,
                "cpm": cpm,
                "cpc": cpc,
                "click_to_result_cr": click_to_result_cr,
                "video_50_rate": video_50_rate,
                "opt_signal": opt_signal,
            })
        # Sort: by results desc for Hot groups, by clicks desc for Cold
        if "Hot" in cat:
            ads.sort(key=lambda a: (-a["results"], -a["clicks"]))
        else:
            ads.sort(key=lambda a: -a["clicks"])

        total_spent = sum(a["spent"] for a in ads)
        total_clicks = sum(a["clicks"] for a in ads)
        total_results = sum(a["results"] for a in ads)
        total_impressions = sum(a["impressions"] for a in ads)
        total_reach = sum(a["reach"] for a in ads)
        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0.0
        avg_cpc = (total_spent / total_clicks) if total_clicks else 0.0
        avg_cpm = (total_spent / total_impressions * 1000) if total_impressions else 0.0
        cpl = (total_spent / total_results) if total_results else 0.0
        click_to_result_cr = (total_results / total_clicks * 100) if total_clicks else 0.0
        avg_frequency = (total_impressions / total_reach) if total_reach else 0.0

        # Count ads needing attention
        n_burn = sum(1 for a in ads if "burn-no-result" in a["opt_signal"])
        n_low_ctr = sum(1 for a in ads if "low-ctr" in a["opt_signal"])
        n_low_conv = sum(1 for a in ads if "low-conv-after-click" in a["opt_signal"])

        groups[cat] = {
            "ads": ads,
            "n_ads": len(ads),
            "total_spent": total_spent,
            "total_clicks": total_clicks,
            "total_results": total_results,
            "total_impressions": total_impressions,
            "total_reach": total_reach,
            "avg_ctr": avg_ctr,
            "avg_cpc": avg_cpc,
            "avg_cpm": avg_cpm,
            "avg_frequency": avg_frequency,
            "click_to_result_cr": click_to_result_cr,
            "cpl_csv": cpl,
            "n_burn": n_burn,
            "n_low_ctr": n_low_ctr,
            "n_low_conv": n_low_conv,
        }

    # Per khoa summary
    def empty_group():
        return {
            "ads": [], "n_ads": 0, "total_spent": 0.0, "total_clicks": 0,
            "total_results": 0, "total_impressions": 0, "total_reach": 0,
            "avg_ctr": 0.0, "avg_cpc": 0.0, "avg_cpm": 0.0, "avg_frequency": 0.0,
            "click_to_result_cr": 0.0, "cpl_csv": 0.0,
            "n_burn": 0, "n_low_ctr": 0, "n_low_conv": 0,
        }

    khoa_data = {}
    for k in focus_khoa:
        hot = groups.get(f"{k} Hot", empty_group())
        cold = groups.get(f"{k} Cold", empty_group())
        act = actuals.get(k, {})
        hot_social = int(act.get("hot_social", 0) or 0)
        hot_web = int(act.get("hot_web", 0) or 0)
        content_lead = int(act.get("content", 0) or 0)

        total_spent = hot.get("total_spent", 0) + cold.get("total_spent", 0)
        cold_conv = (content_lead / cold.get("total_clicks", 0) * 100) if cold.get("total_clicks") else 0
        cold_cost_per_content = (cold.get("total_spent", 0) / content_lead) if content_lead else 0
        hot_cpl_image = (hot.get("total_spent", 0) / hot_social) if hot_social else 0
        hot_click_to_lead = (hot_social / hot.get("total_clicks", 0) * 100) if hot.get("total_clicks") else 0

        # Won / closed deals
        won_hot = int(act.get("won_hot", 0) or 0)
        won_cold = int(act.get("won_cold", 0) or 0)
        won_event = int(act.get("won_event", 0) or 0)
        won_total = won_hot + won_cold + won_event
        won_paid = won_hot + won_cold  # exclude event (organic/offline)

        win_rate_hot = (won_hot / hot_social * 100) if hot_social else 0
        win_rate_cold = (won_cold / content_lead * 100) if content_lead else 0
        cost_per_won_hot = (hot.get("total_spent", 0) / won_hot) if won_hot else 0
        cost_per_won_cold = (cold.get("total_spent", 0) / won_cold) if won_cold else 0
        cost_per_won_paid = (total_spent / won_paid) if won_paid else 0

        # Bottleneck diagnosis — find the worst stage
        bottlenecks = []
        # Hot funnel: CTR, Click->Lead, Win rate
        if hot.get("avg_ctr", 0) < 1.0 and hot.get("total_impressions", 0) >= 1000:
            bottlenecks.append({"stage": "Hot CTR", "value": hot.get("avg_ctr", 0), "benchmark": "1.5-2.5%", "action": "Đổi creative/thumbnail"})
        if hot.get("click_to_result_cr", 0) < 3.0 and hot.get("total_clicks", 0) >= 50:
            bottlenecks.append({"stage": "Hot Click→Lead", "value": hot.get("click_to_result_cr", 0), "benchmark": "5-10%", "action": "Audit Lead Form (số trường, mobile UX)"})
        if hot_social and win_rate_hot < 5.0:
            bottlenecks.append({"stage": "Hot Lead→Won", "value": win_rate_hot, "benchmark": "5-15%", "action": "Sales follow-up speed / lead quality scoring"})
        # Cold funnel: CTR, Click->Content
        if cold.get("avg_ctr", 0) < 1.0 and cold.get("total_impressions", 0) >= 1000:
            bottlenecks.append({"stage": "Cold CTR", "value": cold.get("avg_ctr", 0), "benchmark": "1.5-2.5%", "action": "Đổi creative/thumbnail"})
        if cold_conv < 3.0 and cold.get("total_clicks", 0) >= 100:
            bottlenecks.append({"stage": "Cold Click→Form", "value": cold_conv, "benchmark": "8-12%", "action": "Audit landing page + GG Form (rút gọn trường, headline match ad)"})
        if content_lead and win_rate_cold < 3.0:
            bottlenecks.append({"stage": "Content→Won", "value": win_rate_cold, "benchmark": "2-5%", "action": "Nurture email/Zalo sequence cho content lead"})

        khoa_data[k] = {
            "name": k,
            "hot": hot,
            "cold": cold,
            "hot_social_actual": hot_social,
            "hot_web_actual": hot_web,
            "content_lead_actual": content_lead,
            "total_spent": total_spent,
            "cold_conv": cold_conv,
            "cold_cost_per_content": cold_cost_per_content,
            "hot_cpl_image": hot_cpl_image,
            "hot_click_to_lead": hot_click_to_lead,
            "csv_leads_vs_image_diff": hot_social - hot.get("total_results", 0) if hot_social else 0,
            # Won / closed deals
            "won_hot": won_hot,
            "won_cold": won_cold,
            "won_event": won_event,
            "won_total": won_total,
            "won_paid": won_paid,
            "win_rate_hot": win_rate_hot,
            "win_rate_cold": win_rate_cold,
            "cost_per_won_hot": cost_per_won_hot,
            "cost_per_won_cold": cost_per_won_cold,
            "cost_per_won_paid": cost_per_won_paid,
            # Bottlenecks
            "bottlenecks": bottlenecks,
        }

    return {
        "groups": groups,
        "khoa": khoa_data,
        "total_in_scope_ads": len(in_scope),
        "total_out_of_scope_ads": len(df) - len(in_scope),
    }


def render_ads_report(analysis: dict, period_label: str = "", template_dir: str | Path = "templates") -> str:
    """Render Jinja2 template -> HTML string."""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    # Custom filters
    def fmt_int(v): return f"{int(v):,}".replace(",", ",")
    def fmt_money(v):
        v = float(v or 0)
        if v >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"{v/1_000:.0f}K"
        return f"{v:,.0f}"
    def fmt_pct(v, decimals=2): return f"{float(v or 0):.{decimals}f}%"
    def fmt_num(v, decimals=0): return f"{float(v or 0):,.{decimals}f}"

    env.filters["fmt_int"] = fmt_int
    env.filters["fmt_money"] = fmt_money
    env.filters["fmt_pct"] = fmt_pct
    env.filters["fmt_num"] = fmt_num

    template = env.get_template("ads_report.html")
    return template.render(analysis=analysis, period=period_label or "Báo cáo Ads")
