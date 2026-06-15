"""
Skill: Lead Quality Analysis (Sales hotlead tracking)
Input: CSV/Excel with columns: Tuần, Ngày, Thứ, STT, Data Huyền, Lead Status,
       Nguồn, Tên, Phone, Email, Product, Khung giờ.

Map Product -> khoá using bu_config.product_to_khoa, filter by BU, compute:
- Total leads per khoá
- Status breakdown (Won / Deal / Contacted / KNM2 / Junk / Đã Fail / ...)
- Source breakdown (Fb Form / Web - Organic / Fb Organic / Zalo OA / ...)
- Quality tier (HOT / WARM / COLD)
- Win rate (Won / Total)
"""
from __future__ import annotations
import pandas as pd

from .bu_config import product_to_khoa, ALL_KHOA


# Lead status -> quality tier
STATUS_TO_TIER = {
    # HOT — high quality
    "won": "HOT",
    "deal": "HOT",
    # WARM — in funnel
    "contacted": "WARM",
    "đã nhắn zalo chờ phản hồi": "WARM",
    "nhắn zalo": "WARM",
    "cần nhắc thời gian": "WARM",
    "tư vấn zalo": "WARM",
    # COLD — bad / lost
    "knm2": "COLD",
    "knm": "COLD",
    "junk": "COLD",
    "đã fail": "COLD",
    "fail": "COLD",
    "huỷ": "COLD",
}


def normalize(s) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()


def status_tier(status: str) -> str:
    n = normalize(status)
    if not n:
        return "UNKNOWN"
    return STATUS_TO_TIER.get(n, "OTHER")


def _safe_int(val):
    try:
        v = pd.to_numeric(val, errors="coerce")
        if pd.isna(v):
            return 0
        return int(v)
    except Exception:
        return 0


def find_col(df: pd.DataFrame, *names) -> str | None:
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for n in names:
        if n.lower() in cols_lower:
            return cols_lower[n.lower()]
    return None


def analyze_leads(df: pd.DataFrame, focus_khoa: list[str] | None = None) -> dict:
    """Analyze sales lead tracking dataframe.

    Args:
        df: raw DataFrame from Excel/CSV upload
        focus_khoa: list of khoá to include. None = all 8.

    Returns:
        {
          "khoa": {"Trade": {...}, ...},
          "unmapped_products": [{"product": str, "count": int}, ...],
          "total_in_scope": int,
          "total_unmapped": int,
        }
    """
    if focus_khoa is None:
        focus_khoa = ALL_KHOA

    df = df.copy()
    c_product = find_col(df, "Product", "Khoá", "Khoa", "Sản phẩm", "Course")
    c_status = find_col(df, "Lead Status", "Status", "Trạng thái")
    c_source = find_col(df, "Nguồn", "Source")
    c_phone = find_col(df, "Phone", "SĐT", "Số điện thoại")
    c_name = find_col(df, "Tên", "Name")
    c_date = find_col(df, "Ngày", "Date")

    if not c_product:
        raise ValueError("Thiếu cột 'Product' (hoặc 'Khoá') trong file lead tracking")
    if not c_status:
        raise ValueError("Thiếu cột 'Lead Status' trong file lead tracking")

    df["__khoa"] = df[c_product].apply(product_to_khoa)
    df["__tier"] = df[c_status].apply(status_tier)
    df["__status_norm"] = df[c_status].apply(normalize)

    in_scope = df[df["__khoa"].notna() & df["__khoa"].isin(focus_khoa)].copy()
    unmapped = df[df["__khoa"].isna()].copy()

    # Build per-khoa breakdown
    khoa_data = {}
    for k in focus_khoa:
        sub = in_scope[in_scope["__khoa"] == k]
        total = len(sub)
        if total == 0:
            khoa_data[k] = {
                "name": k,
                "total": 0,
                "won": 0,
                "deal": 0,
                "hot_count": 0,
                "warm_count": 0,
                "cold_count": 0,
                "unknown_count": 0,
                "win_rate": 0.0,
                "deal_rate": 0.0,
                "status_breakdown": [],
                "source_breakdown": [],
                "leads": [],
            }
            continue

        # Status breakdown
        status_counts = sub["__status_norm"].value_counts().to_dict()
        status_breakdown = [
            {"status": s, "count": int(c), "pct": float(c / total * 100)}
            for s, c in sorted(status_counts.items(), key=lambda x: -x[1])
        ]

        # Source breakdown
        source_breakdown = []
        if c_source:
            src_counts = sub[c_source].fillna("(không rõ)").value_counts().to_dict()
            source_breakdown = [
                {"source": str(s), "count": int(c), "pct": float(c / total * 100)}
                for s, c in sorted(src_counts.items(), key=lambda x: -x[1])
            ]

        # Tier counts
        tier_counts = sub["__tier"].value_counts().to_dict()
        won = int((sub["__status_norm"] == "won").sum())
        deal = int((sub["__status_norm"] == "deal").sum())

        # Leads detail
        leads = []
        for _, r in sub.iterrows():
            leads.append({
                "date": str(r.get(c_date, "") if c_date else ""),
                "name": str(r.get(c_name, "") if c_name else ""),
                "phone": str(r.get(c_phone, "") if c_phone else ""),
                "product": str(r.get(c_product, "")),
                "status": str(r.get(c_status, "")),
                "source": str(r.get(c_source, "") if c_source else ""),
                "tier": r["__tier"],
            })

        khoa_data[k] = {
            "name": k,
            "total": total,
            "won": won,
            "deal": deal,
            "hot_count": int(tier_counts.get("HOT", 0)),
            "warm_count": int(tier_counts.get("WARM", 0)),
            "cold_count": int(tier_counts.get("COLD", 0)),
            "unknown_count": int(tier_counts.get("OTHER", 0) + tier_counts.get("UNKNOWN", 0)),
            "win_rate": won / total * 100 if total else 0,
            "deal_rate": (won + deal) / total * 100 if total else 0,
            "status_breakdown": status_breakdown,
            "source_breakdown": source_breakdown,
            "leads": leads,
        }

    # Unmapped products (for user to clarify)
    unmapped_products = []
    if len(unmapped) > 0:
        unmapped_counts = unmapped[c_product].fillna("(empty)").value_counts().to_dict()
        unmapped_products = [
            {"product": str(p), "count": int(c)}
            for p, c in sorted(unmapped_counts.items(), key=lambda x: -x[1])
        ]

    return {
        "khoa": khoa_data,
        "unmapped_products": unmapped_products,
        "total_in_scope": len(in_scope),
        "total_unmapped": len(unmapped),
        "total_rows": len(df),
    }
