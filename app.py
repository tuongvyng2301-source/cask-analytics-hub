"""
CASK Analytics Hub — Streamlit app.

Flow:
1. Pick BU (BU1 / BU2 / BU3) → filters analysis to khoá thuộc BU
2. Upload up to 3 files: Ads CSV, Organic posts CSV, Lead tracking
3. Pre-categorize → review ambiguous posts (manual classify)
4. Generate final report (HTML, save 30 days, shareable)
"""
from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from skills.bu_config import BU_CONFIG, ALL_KHOA, filter_khoa_by_bu
from skills.ads_analysis import analyze_ads, render_ads_report
from skills.organic_analysis import analyze_organic, find_ambiguous_posts, categorize_dataframe, list_all_posts_with_category
from skills.lead_quality import analyze_leads
from skills.meta_api import fetch_ad_creative, verify_token, fetch_ads_insights, insights_to_dataframe_dict, MetaAPIError
from skills.settings_store import (
    set_setting, get_setting, cache_creative, get_cached_creative, clear_creative_cache,
    password_is_set, set_password, verify_password, mask_secret,
)


APP_TITLE = "CASK Analytics Hub"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "reports.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"
REPORT_TTL_DAYS = 30

st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")


# ---------- DB ----------
def db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            skill TEXT NOT NULL,
            title TEXT,
            html TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    return conn


def save_report(skill: str, title: str, html: str) -> str:
    rid = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=REPORT_TTL_DAYS)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO reports (id, skill, title, html, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (rid, skill, title, html, now.isoformat(), expires.isoformat()),
        )
    return rid


def get_report(rid: str):
    with db_conn() as conn:
        row = conn.execute("SELECT id, skill, title, html, created_at, expires_at FROM reports WHERE id = ?", (rid,)).fetchone()
    if not row:
        return None
    if datetime.now(timezone.utc) > datetime.fromisoformat(row[5]):
        return None
    return {"id": row[0], "skill": row[1], "title": row[2], "html": row[3], "created_at": row[4], "expires_at": row[5]}


def cleanup_expired():
    with db_conn() as conn:
        conn.execute("DELETE FROM reports WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))


def list_recent_reports(limit: int = 20):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, skill, title, created_at FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"id": r[0], "skill": r[1], "title": r[2], "created_at": r[3]} for r in rows]


# ---------- Views ----------
def view_shared_report(rid: str):
    rep = get_report(rid)
    if not rep:
        st.error("Báo cáo không tồn tại hoặc đã hết hạn (giữ 30 ngày).")
        st.link_button("← Về trang chính", "/")
        return
    st.title(rep["title"])
    st.caption(f"Generated: {datetime.fromisoformat(rep['created_at']).strftime('%d/%m/%Y %H:%M UTC')} | ID: {rep['id']}")
    st.components.v1.html(rep["html"], height=2500, scrolling=True)
    st.download_button("⬇️ Download HTML", data=rep["html"], file_name=f"{rep['skill']}_{rep['id']}.html", mime="text/html")


def page_settings():
    st.title("⚙️ Settings — Meta API + Password")

    # ---- Section 1: Meta API ----
    st.subheader("🔐 Meta API")

    current_token = get_setting(DB_PATH, "meta_access_token", "")
    current_account = get_setting(DB_PATH, "meta_ad_account_id", "")
    masked_token = mask_secret(current_token, keep_last=4) if current_token else "(chưa setup)"

    st.markdown(f"**Token hiện tại:** `{masked_token}`")

    if "show_token_editor" not in st.session_state:
        st.session_state["show_token_editor"] = not current_token

    if not st.session_state["show_token_editor"]:
        if st.button("✏️ Replace Token"):
            st.session_state["show_token_editor"] = True
            st.rerun()

    if st.session_state["show_token_editor"]:
        token = st.text_input(
            "Paste Meta Access Token mới",
            value="",
            type="password",
            placeholder="EAAxxxxxxxx...",
            help="Token cũ sẽ bị overwrite. Lấy từ Graph API Explorer.",
        )
        ad_account = st.text_input(
            "Ad Account ID",
            value=current_account,
            placeholder="act_3022619417793545",
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Save", type="primary"):
                if token.strip():
                    set_setting(DB_PATH, "meta_access_token", token.strip())
                if ad_account.strip():
                    set_setting(DB_PATH, "meta_ad_account_id", ad_account.strip())
                st.session_state["show_token_editor"] = False
                st.success("Saved — token đã ẩn cho an toàn.")
                st.rerun()
        with c2:
            if st.button("✕ Cancel"):
                st.session_state["show_token_editor"] = False
                st.rerun()
    else:
        st.caption(f"Ad Account ID: `{current_account or '(chưa setup)'}`")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔍 Test Token đã lưu"):
            with st.spinner("Đang ping Meta..."):
                result = verify_token(current_token, current_account or None)
            if result.get("ok"):
                msg = f"✅ Token OK — user: **{result.get('user_name')}**"
                if result.get("ad_account_name"):
                    msg += f"\n\n✅ Ad Account: **{result['ad_account_name']}** (status: {result.get('ad_account_status')})"
                st.success(msg)
            else:
                st.error(f"❌ Token không hợp lệ: {result.get('error')}")
    with col_b:
        if st.button("🗑️ Xoá Creative Cache"):
            n = clear_creative_cache(DB_PATH)
            st.info(f"Đã xoá {n} creative cached.")

    st.markdown("---")

    # ---- Section 2: Hub Password ----
    st.subheader("🔑 Password truy cập hub")
    st.caption("Mọi người vào hub phải gõ password này. Đổi password tại đây.")

    if password_is_set(DB_PATH):
        st.markdown("**Status:** ✅ Password đã set")
    else:
        st.markdown("**Status:** ⚠️ Chưa có password — hub đang **mở** cho mọi người!")

    new_pw = st.text_input("Password mới", type="password", placeholder="Tối thiểu 6 ký tự")
    new_pw_confirm = st.text_input("Xác nhận password", type="password")

    if st.button("🔐 Lưu password mới", type="primary"):
        if len(new_pw) < 6:
            st.error("Password tối thiểu 6 ký tự.")
        elif new_pw != new_pw_confirm:
            st.error("Hai ô password không khớp.")
        else:
            set_password(DB_PATH, new_pw)
            st.success("Đã đổi password. Các session đang mở sẽ vẫn dùng được; session mới phải gõ password mới.")

    st.markdown("---")
    st.markdown("### Hướng dẫn lấy token (lần sau khi expire)")
    st.markdown("""
1. [Graph API Explorer](https://developers.facebook.com/tools/explorer) → Meta App = `CASK Report Analytics Hub`
2. Get Token → User Access Token → permissions `ads_read`, `ads_management`, `business_management`
3. Generate → copy → paste vào ô "Replace Token" ở trên
""")


def page_home():
    st.title(f"📊 {APP_TITLE}")
    st.markdown("Hub phân tích Marketing CASK — Ads + Organic + Lead Quality. Báo cáo lưu 30 ngày + share link.")
    cleanup_expired()

    # ---------- Step 1: BU picker ----------
    st.subheader("Bước 1 — Chọn BU làm báo cáo")
    bu_choice = st.radio(
        "BU phụ trách",
        options=list(BU_CONFIG.keys()),
        format_func=lambda b: BU_CONFIG[b]["label"],
        horizontal=True,
        key="bu_choice",
    )
    focus_khoa = filter_khoa_by_bu(bu_choice)
    st.caption(f"Khoá phân tích: **{' / '.join(focus_khoa)}**")

    period_label = st.text_input(
        "Tên kỳ báo cáo",
        value=f"W{datetime.now().isocalendar().week} ({datetime.now().strftime('%d/%m/%Y')})",
    )

    # ---------- Step 2: Source for ads + uploads ----------
    st.subheader("Bước 2 — Nguồn data")

    # Ads data source picker
    has_api = bool(get_setting(DB_PATH, "meta_access_token") and get_setting(DB_PATH, "meta_ad_account_id"))
    ads_source = st.radio(
        "📊 Ads data source",
        options=["📡 Fetch tự động từ Meta API (recommended)", "📊 Upload CSV thủ công"],
        index=0 if has_api else 1,
        horizontal=True,
        disabled=not has_api,
        help="Cần setup Meta API token + Ad Account ID trong Settings để dùng auto-fetch." if not has_api else None,
    )
    use_api = ads_source.startswith("📡") and has_api

    today = datetime.now().date()
    default_start = today - timedelta(days=7)

    ads_file = None
    api_start_date = None
    api_end_date = None
    if use_api:
        c_d1, c_d2 = st.columns(2)
        with c_d1:
            api_start_date = st.date_input("Từ ngày", value=default_start, max_value=today)
        with c_d2:
            api_end_date = st.date_input("Đến ngày", value=today, max_value=today)
    else:
        ads_file = st.file_uploader("📊 Ads CSV (Meta Ads Manager)", type=["csv"], key="ads_csv")

    c2, c3 = st.columns(2)
    with c2:
        organic_file = st.file_uploader("📱 Facebook Posts CSV", type=["csv"], key="organic_csv")
    with c3:
        leads_file = st.file_uploader("🎯 Lead Tracking (CSV/Excel)", type=["csv", "xlsx", "xls"], key="leads_csv")

    # Actuals input (collapsed)
    with st.expander("Nhập actuals tuần (Hot/Web/Content + Won) cho từng khoá — optional", expanded=False):
        actuals = {}
        cols = st.columns(len(focus_khoa))
        for i, k in enumerate(focus_khoa):
            with cols[i]:
                st.markdown(f"**{k}**")
                st.caption("Leads")
                hs = st.number_input("Hot Social", min_value=0, value=0, key=f"{k}_hs")
                hw = st.number_input("Hot Web", min_value=0, value=0, key=f"{k}_hw")
                cl = st.number_input("Content lead", min_value=0, value=0, key=f"{k}_cl")
                st.caption("Won")
                wh = st.number_input("Won Hot", min_value=0, value=0, key=f"{k}_wh")
                wc = st.number_input("Won Cold", min_value=0, value=0, key=f"{k}_wc")
                we = st.number_input("Won Event", min_value=0, value=0, key=f"{k}_we")
                actuals[k] = {
                    "hot_social": hs, "hot_web": hw, "content": cl,
                    "won_hot": wh, "won_cold": wc, "won_event": we,
                }

    # ---------- Step 3: Pre-categorize + REVIEW ALL posts ----------
    st.subheader("Bước 3 — Pre-categorize + Review phân loại")
    st.caption("Click để hub auto-classify. Sau đó CHECK lại tất cả bài, đổi khoá nếu sai.")

    if "all_posts" not in st.session_state:
        st.session_state["all_posts"] = []
    if "manual_labels" not in st.session_state:
        st.session_state["manual_labels"] = {}

    if st.button("📋 Pre-categorize Posts", disabled=not organic_file):
        try:
            organic_file.seek(0)
            df_organic = pd.read_csv(organic_file)
            all_posts = list_all_posts_with_category(df_organic, focus_khoa=focus_khoa)
            st.session_state["organic_df"] = df_organic
            st.session_state["all_posts"] = all_posts
            # Reset manual labels khi pre-categorize lại
            st.session_state["manual_labels"] = {}

            n_uncat = sum(1 for p in all_posts if p["is_uncategorized"])
            n_out_focus = sum(1 for p in all_posts if not p["is_uncategorized"] and not p["is_in_focus"])
            n_in_focus = sum(1 for p in all_posts if p["is_in_focus"])

            st.success(
                f"✅ Đã categorize {len(all_posts)} posts: "
                f"**{n_in_focus} in-scope BU** · {n_out_focus} ngoài BU · {n_uncat} chưa phân loại"
            )
            if n_uncat or n_out_focus:
                st.info("👇 Review bảng bên dưới — đổi cột 'Khoá' nếu phân loại sai, rồi click '💾 Lưu phân loại'.")
        except Exception as e:
            st.error(f"Lỗi pre-categorize: {e}")

    # Full review table
    if st.session_state["all_posts"]:
        st.markdown("---")
        st.markdown("### 🔎 Review tất cả posts — đổi khoá nếu cần")
        st.caption(
            "**(Auto)** = hub phân loại đúng → giữ nguyên · "
            "**(❓ Chưa)** = không match keyword → user pick · "
            "**(Out of scope)** = bài ngoài BU đang chọn → bỏ"
        )

        # Filter option
        filter_mode = st.radio(
            "Hiển thị",
            options=["Tất cả", "Chỉ in-scope BU", "Chỉ ngoài BU / chưa phân loại"],
            horizontal=True,
            key="post_filter_mode",
        )

        posts_show = st.session_state["all_posts"]
        if filter_mode == "Chỉ in-scope BU":
            posts_show = [p for p in posts_show if p["is_in_focus"]]
        elif filter_mode == "Chỉ ngoài BU / chưa phân loại":
            posts_show = [p for p in posts_show if not p["is_in_focus"]]

        khoa_options = ["(Out of scope)"] + focus_khoa

        rows = []
        for p in posts_show:
            # Default for the dropdown
            existing_manual = st.session_state["manual_labels"].get(p["row_index"])
            if existing_manual:
                current_khoa = existing_manual
                status = "✏️ Manual"
            elif p["is_in_focus"]:
                current_khoa = p["auto_khoa"]
                status = "✓ Auto"
            elif p["auto_khoa"]:
                current_khoa = "(Out of scope)"
                status = f"⚪ Out (auto: {p['auto_khoa']})"
            else:
                current_khoa = "(Out of scope)"
                status = "❓ Chưa"
            rows.append({
                "Status": status,
                "Ngày": p["date"],
                "Type": p["post_type"],
                "Reach": p["reach"],
                "Tiêu đề": p["title_short"],
                "Khoá": current_khoa,
                "FB Link": p["permalink"],
                "__row_index": p["row_index"],
            })

        review_df = pd.DataFrame(rows)
        edited = st.data_editor(
            review_df,
            column_config={
                "Status": st.column_config.TextColumn(disabled=True, width="small"),
                "Ngày": st.column_config.TextColumn(disabled=True, width="small"),
                "Type": st.column_config.TextColumn(disabled=True, width="small"),
                "Reach": st.column_config.NumberColumn(disabled=True, width="small"),
                "Tiêu đề": st.column_config.TextColumn(disabled=True, width="large"),
                "Khoá": st.column_config.SelectboxColumn(options=khoa_options, required=True, width="small"),
                "FB Link": st.column_config.LinkColumn("FB", width="small", display_text="Xem ↗"),
                "__row_index": None,
            },
            hide_index=True,
            use_container_width=True,
            height=500,
            key="review_editor",
        )

        c_save, c_reset = st.columns([3, 1])
        with c_save:
            if st.button("💾 Lưu phân loại (manual override sẽ áp vào Generate Report)"):
                # Build manual_labels = only rows where user changed khoá from "Out of scope" to an actual khoá,
                # OR changed from auto-khoá to a different khoá
                manual = {}
                posts_lookup = {p["row_index"]: p for p in st.session_state["all_posts"]}
                for _, row in edited.iterrows():
                    ri = int(row["__row_index"])
                    auto = posts_lookup[ri]["auto_khoa"]
                    chosen = row["Khoá"]
                    if chosen == "(Out of scope)":
                        # User said skip this post → set to None (will not be analyzed)
                        if auto is not None:
                            manual[ri] = "__SKIP__"
                    else:
                        # User picked a specific khoá → record only if differs from auto
                        if chosen != auto:
                            manual[ri] = chosen
                st.session_state["manual_labels"] = manual
                st.success(f"Đã lưu {len(manual)} thay đổi (override + skip). Click Generate Report bên dưới.")
        with c_reset:
            if st.button("↺ Reset"):
                st.session_state["manual_labels"] = {}
                st.success("Reset xong.")
                st.rerun()

    # ---------- Step 4: Generate ----------
    st.markdown("---")
    st.subheader("Bước 4 — Generate báo cáo")

    can_generate = use_api or ads_file is not None or organic_file is not None or leads_file is not None
    if st.button("🚀 Generate Report", type="primary", disabled=not can_generate):
        analysis = None
        organic_data = None
        lead_data = None
        df_ads = None

        # Ads — fetch from API or read CSV
        if use_api:
            token = get_setting(DB_PATH, "meta_access_token", "")
            ad_account = get_setting(DB_PATH, "meta_ad_account_id", "")
            try:
                with st.spinner(f"📡 Fetching ads insights từ Meta API ({api_start_date} → {api_end_date})..."):
                    rows = fetch_ads_insights(
                        ad_account, token,
                        str(api_start_date), str(api_end_date),
                    )
                    df_ads = pd.DataFrame(insights_to_dataframe_dict(rows))
                st.success(f"📡 Fetched {len(df_ads)} ad rows từ Meta API.")
            except MetaAPIError as e:
                st.error(f"❌ Meta API lỗi: {e}")
                return
            except Exception as e:
                st.error(f"❌ Lỗi fetch API: {e}")
                return
        elif ads_file:
            try:
                ads_file.seek(0)
                df_ads = pd.read_csv(ads_file)
                if "Campaign name" not in df_ads.columns:
                    st.error("❌ File Ads CSV thiếu cột `Campaign name`. Kiểm tra xem có phải upload nhầm file Facebook posts không?")
                    return
            except Exception as e:
                st.error(f"Lỗi parse Ads CSV: {e}")
                return

        if df_ads is not None:
            try:
                # Fetch creatives via Meta API if token + Ad ID column available
                creatives = {}
                ad_id_col = next((c for c in df_ads.columns if c.lower().strip().replace("_", " ") in ("ad id", "adid")), None)
                token = get_setting(DB_PATH, "meta_access_token", "")
                if token and ad_id_col:
                    ad_ids = [str(x).strip() for x in df_ads[ad_id_col].dropna().unique() if str(x).strip() and str(x).strip().lower() != "nan"]
                    fetch_status = st.empty()
                    progress = st.progress(0)
                    n = len(ad_ids)
                    for i, ad_id in enumerate(ad_ids):
                        cached = get_cached_creative(DB_PATH, ad_id)
                        if cached:
                            creatives[ad_id] = cached
                        else:
                            res = fetch_ad_creative(ad_id, token)
                            creatives[ad_id] = res
                            cache_creative(DB_PATH, ad_id, res)
                        fetch_status.caption(f"Fetching creative {i+1}/{n}...")
                        progress.progress((i + 1) / n if n else 1.0)
                    progress.empty()
                    fetch_status.empty()
                    n_ok = sum(1 for c in creatives.values() if c.get("thumbnail_url") or c.get("image_url"))
                    st.info(f"📷 Đã fetch {n_ok}/{n} creative thumbnails từ Meta API.")
                elif token and not ad_id_col:
                    st.warning("⚠️ Có token Meta API nhưng CSV thiếu cột `Ad ID` → không fetch được thumbnails. Thêm cột Ad ID khi export CSV.")
                elif not token:
                    st.caption("ℹ️ Chưa setup Meta API token (xem ⚙️ Settings) → báo cáo không có thumbnail.")

                analysis = analyze_ads(df_ads, actuals, focus_khoa=focus_khoa, creatives=creatives)
            except Exception as e:
                st.error(f"Lỗi parse Ads CSV: {e}")
                return
        else:
            # Empty analysis stub so template can render organic + lead
            analysis = {
                "groups": {}, "khoa": {k: {
                    "name": k, "hot": {}, "cold": {},
                    "hot_social_actual": 0, "hot_web_actual": 0, "content_lead_actual": 0,
                    "total_spent": 0, "cold_conv": 0, "cold_cost_per_content": 0,
                    "hot_cpl_image": 0, "hot_click_to_lead": 0, "csv_leads_vs_image_diff": 0,
                    "won_hot": 0, "won_cold": 0, "won_event": 0, "won_total": 0, "won_paid": 0,
                    "win_rate_hot": 0, "win_rate_cold": 0,
                    "cost_per_won_hot": 0, "cost_per_won_cold": 0, "cost_per_won_paid": 0,
                    "bottlenecks": [],
                } for k in focus_khoa},
                "total_in_scope_ads": 0, "total_out_of_scope_ads": 0,
            }

        # Organic
        if organic_file:
            try:
                organic_file.seek(0)
                df_org = pd.read_csv(organic_file)
                manual_labels = st.session_state.get("manual_labels", {})
                organic_data = analyze_organic(df_org, focus_khoa=focus_khoa, manual_labels=manual_labels)
            except Exception as e:
                st.warning(f"Lỗi parse Facebook posts CSV (bỏ qua organic): {e}")
        analysis["organic"] = organic_data

        # Lead quality
        if leads_file:
            try:
                leads_file.seek(0)
                if leads_file.name.lower().endswith((".xlsx", ".xls")):
                    df_lead = pd.read_excel(leads_file)
                else:
                    df_lead = pd.read_csv(leads_file)
                lead_data = analyze_leads(df_lead, focus_khoa=focus_khoa)
            except Exception as e:
                st.warning(f"Lỗi parse Lead Tracking (bỏ qua lead quality): {e}")
        analysis["leads"] = lead_data
        analysis["bu"] = {"code": bu_choice, "label": BU_CONFIG[bu_choice]["label"], "khoa": focus_khoa}

        with st.spinner("Đang generate report..."):
            html = render_ads_report(analysis, period_label, template_dir=TEMPLATES_DIR)
            rid = save_report("weekly_report", f"{BU_CONFIG[bu_choice]['label']} — {period_label}", html)

        st.success(f"✅ Báo cáo đã tạo (ID: `{rid}`). Giữ 30 ngày.")
        st.code(f"?report={rid}", language="text")
        st.download_button(
            "⬇️ Download HTML", data=html,
            file_name=f"report_{rid}.html", mime="text/html",
        )
        st.markdown("---")
        st.subheader("Preview")
        st.components.v1.html(html, height=2500, scrolling=True)

    # ---------- Sidebar: recent reports ----------
    st.sidebar.subheader("Báo cáo gần đây")
    recent = list_recent_reports(limit=10)
    if not recent:
        st.sidebar.caption("Chưa có báo cáo nào.")
    else:
        for r in recent:
            created = datetime.fromisoformat(r["created_at"]).strftime("%d/%m %H:%M")
            st.sidebar.markdown(f"- [{r['title'] or r['skill']}](?report={r['id']}) — _{created}_")


def page_login():
    st.title(f"🔐 {APP_TITLE}")
    st.caption("Hub yêu cầu password để truy cập.")

    if not password_is_set(DB_PATH):
        st.warning("⚠️ Hub chưa có password. Setup lần đầu:")
        pw1 = st.text_input("Password mới", type="password", placeholder="Tối thiểu 6 ký tự")
        pw2 = st.text_input("Xác nhận", type="password")
        if st.button("🔐 Setup password", type="primary"):
            if len(pw1) < 6:
                st.error("Password tối thiểu 6 ký tự.")
            elif pw1 != pw2:
                st.error("Hai ô không khớp.")
            else:
                set_password(DB_PATH, pw1)
                st.session_state["authed"] = True
                st.success("Setup xong. Đang vào hub...")
                st.rerun()
        return

    pw = st.text_input("Password", type="password")
    if st.button("🔓 Vào hub", type="primary"):
        if verify_password(DB_PATH, pw):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("❌ Password sai.")


def main():
    params = st.query_params
    report_id = params.get("report")

    # Shared report (public link) — vẫn cần password để mở
    if report_id and not st.session_state.get("authed", False):
        page_login()
        return

    if report_id:
        view_shared_report(report_id)
        return

    # Password gate cho hub home
    if not st.session_state.get("authed", False):
        page_login()
        return

    # Sidebar nav
    with st.sidebar:
        st.caption(f"🔐 Đã login")
        if st.button("Log out", use_container_width=True):
            st.session_state["authed"] = False
            st.rerun()
        st.markdown("---")
    page = st.sidebar.radio("Trang", ["🏠 Báo cáo", "⚙️ Settings"], key="nav_page")
    if page == "⚙️ Settings":
        page_settings()
    else:
        page_home()


if __name__ == "__main__":
    main()
