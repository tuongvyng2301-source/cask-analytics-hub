"""Smoke test: build sample CSV inline, run analyze + render, save output HTML."""
from io import StringIO
from pathlib import Path

import pandas as pd

from skills.ads_analysis import analyze_ads, render_ads_report

SAMPLE_CSV = """Campaign name,Ad set name,Ad name,Result type,Results,Cost per result,Amount spent (VND),Link clicks,CTR (all),Impressions,Video plays at 50%,Reporting starts,Reporting ends,Results (initial)
BU 2 | COLD LEAD | 190526,RTM,Cheatsheet,Link clicks,403,598,241159,403,4.75,12786,694,2026-06-01,2026-06-07,
BU 2 | COLD LEAD | 190526,RTM,Tu dien RTM ver 2.0,Link clicks,82,1325,108670,82,2.55,5912,451,2026-06-01,2026-06-07,
BU 2 | COLD LEAD | 190526,Trade,Ebook Trade CAT,Link clicks,250,1681,420374,250,2.38,22719,,2026-06-01,2026-06-07,
BU 2 | COLD LEAD | 190526,Data,Sell-out tu dien thuat ngu,Link clicks,519,680,352940,519,5.38,12624,64,2026-06-01,2026-06-07,
BU 2 | COLD LEAD | 190526,Data,Trade Data Analytics ver 2.0,,,,1226,,1.06,94,,2026-06-01,2026-06-07,
Trade 32 | Video Lead Form | 220426,TRADE M04 -> 1505,"MS thap, SOS cao | Anh Khoa",Leads (form),4,211469,845878,113,2.19,9262,361,2026-06-01,2026-06-07,
Trade 32 | Video Lead Form | 220426,TRADE M04 -> 1505,Promotion trade-in | Anh Khoa,,,,133656,12,1.52,1582,20,2026-06-01,2026-06-07,
Trade 32 | Video Lead Form | 220426,TRADE M04 -> 1505,POSM | Anh Nhan,,,,41537,3,0.67,451,1,2026-06-01,2026-06-07,
Trade 30 | Lead Form | 081025 (Video + testi),Trade Sales,Shelfzone: Anh Nhan,Leads (form),3,175682,527046,97,1.50,12391,186,2026-06-01,2026-06-07,
Trade 30 | Lead Form | 081025 (Video + testi),Trade Sales,Sales chuyen qua Trade,Leads (form),1,103316,103316,6,0.96,2805,,2026-06-01,2026-06-07,
TRADE 32 | Lead Form | 150526 (Photo),LEAD FORM,Exec to Manager | 14 nang luc,Leads (form),1,136202,136202,16,1.47,2588,,2026-06-01,2026-06-07,
TRADE 32 | Lead Form | 150526 (Photo),LEAD FORM,Sales chuyen qua Trade,Leads (form),3,256791,770374,65,0.84,13180,,2026-06-01,2026-06-07,
RTM 09 | Lead Form | 220426,Trade Sales,Sales sup -> ASM,Leads (form),6,111262,667575,94,1.61,14007,,2026-06-01,2026-06-07,
RTM 09 | Lead Form | 220426,Trade Sales,Banner khoa hoc,,,,4297,,1.59,63,,2026-06-01,2026-06-07,
RTM 09 | Lead Form | 220426,Trade Sales,Agenda khoa hoc,,,,39635,5,1.38,869,,2026-06-01,2026-06-07,
Brand - Form - 2705,Brand,PR & Adv,,,,223984,24,1.54,2665,103,2026-06-01,2026-06-07,
AOP - Form - Video,Manager,Xac dinh phan khuc dau tu,,,,556929,58,2.28,4163,94,2026-06-01,2026-06-07,
KAM - Lead Form - 06052026,Trade Sale MKT,2 loi khi lam JBP,Leads (form),1,671960,671960,71,1.36,8631,84,2026-06-01,2026-06-07,
"""


def main():
    df = pd.read_csv(StringIO(SAMPLE_CSV))
    print(f"Loaded {len(df)} rows from sample CSV")

    actuals = {
        "Trade": {"hot_social": 22, "hot_web": 4, "content": 21},
        "RTM":   {"hot_social": 16, "hot_web": 0, "content": 2},
        "Data":  {"hot_social": 0,  "hot_web": 1, "content": 6},
    }

    analysis = analyze_ads(df, actuals)
    print(f"\n--- Analysis result ---")
    print(f"In-scope ads: {analysis['total_in_scope_ads']}")
    print(f"Out-of-scope ads: {analysis['total_out_of_scope_ads']}")
    print(f"\nKhoa summary:")
    for k_name, k in analysis["khoa"].items():
        print(f"  {k_name}:")
        print(f"    Hot: {k['hot']['n_ads']} ads, spent {k['hot']['total_spent']:,.0f}, results {k['hot']['total_results']}")
        print(f"    Cold: {k['cold']['n_ads']} ads, spent {k['cold']['total_spent']:,.0f}, clicks {k['cold']['total_clicks']}")
        print(f"    Cold conv: {k['cold_conv']:.2f}%, Cost/content: {k['cold_cost_per_content']:,.0f}")
        print(f"    CPL hot (image): {k['hot_cpl_image']:,.0f}")

    templates_dir = Path(__file__).parent / "templates"
    html = render_ads_report(analysis, period_label="W1 (1-7/6/2026) — smoke test", template_dir=templates_dir)

    out = Path(__file__).parent / "test_output.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML written to: {out}")
    print(f"HTML size: {len(html):,} chars")


if __name__ == "__main__":
    main()
