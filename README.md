# CASK Analytics Hub

Hub phân tích raw data → báo cáo HTML trực quan. Cho team CASK Marketing.

## Skills hiện có

- **Ads Analysis**: Phân tích Meta paid ads (Trade / RTM / Trade Data) — hotlead + cold lead funnel + benchmark Education.

## Chạy local (test trên máy)

```bash
cd cask-analytics-hub
pip install -r requirements.txt
streamlit run app.py
```

Mở trình duyệt: `http://localhost:8501`

## Deploy lên Streamlit Cloud (share link cho team)

### Bước 1: Push code lên GitHub

```bash
cd cask-analytics-hub
git init
git add .
git commit -m "Initial CASK Analytics Hub"
# Tạo repo private trên github.com -> copy URL
git remote add origin https://github.com/USERNAME/cask-analytics-hub.git
git branch -M main
git push -u origin main
```

### Bước 2: Deploy Streamlit Cloud

1. Vào [share.streamlit.io](https://share.streamlit.io) → login bằng GitHub
2. Click "New app" → chọn repo `cask-analytics-hub`
3. Main file: `app.py`
4. Click Deploy → ~2 phút có link kiểu `https://cask-analytics-hub-xxx.streamlit.app`
5. Share link đó cho 3 người trong team

### Bước 3 (optional): Custom domain

Streamlit Cloud free không support custom domain. Nếu muốn `analytics.cask.vn`:
- Upgrade Streamlit Cloud Team plan ($250/tháng) HOẶC
- Tự host trên VPS (DigitalOcean $6/tháng + nginx reverse proxy)

## Cách dùng

1. Vào link Streamlit app
2. Sidebar chọn skill "Ads Analysis"
3. Upload file CSV xuất từ Meta Ads Manager
4. (Optional) Mở "W1 actuals" expander, nhập số leads/content từ bảng báo cáo
5. Click "Generate Report"
6. Báo cáo hiện ngay + link share (giữ 30 ngày)

## Format CSV Meta Ads Manager

Cần các cột:
- `Campaign name`, `Ad set name`, `Ad name`
- `Results`, `Cost per result`, `Amount spent (VND)`
- `Link clicks`, `CTR (all)`, `Impressions`

Xuất từ Ads Manager: Reports → Export → CSV.

## Categorization rules

| Campaign / Ad set | Category |
|---|---|
| `BU 2 \| COLD LEAD ...` + ad set = `RTM` | RTM Cold |
| `BU 2 \| COLD LEAD ...` + ad set = `Trade` | Trade Cold |
| `BU 2 \| COLD LEAD ...` + ad set = `Data` | Data Cold |
| `Trade 30/32/...`, `TRADE 32/...` | Trade Hot |
| `RTM 09/...` | RTM Hot |
| Khác (Brand, AOP, KAM, Ecom, Finance) | Bỏ (out-of-scope) |

## Thêm skill mới

1. Tạo file `skills/your_skill.py` với 2 hàm: `analyze_xxx(df, ...)` + `render_xxx_report(analysis, ...)`
2. Tạo template `templates/your_skill.html` (Jinja2)
3. Trong `app.py`, thêm vào dict `SKILLS`:
   ```python
   SKILLS = {
       "Ads Analysis (Meta paid ads)": skill_ads_analysis,
       "Your Skill Name": skill_your_skill,
   }
   ```

## Storage

- SQLite at `data/reports.db`
- Báo cáo lưu 30 ngày, auto-cleanup khi load app
- Streamlit Cloud free tier: ephemeral storage — DB sẽ reset khi app restart (vài tuần 1 lần)
- Nếu muốn persistent: connect Supabase free DB thay SQLite (sửa `db_conn()` function)

## Limitations MVP

- ❌ Không có login → ai có link đều dùng được
- ❌ DB SQLite không persist trên Streamlit Cloud free tier
- ❌ FB post embed trong template chưa có (chỉ data tables)
- ✅ Bù lại: download HTML giữ vĩnh viễn

## Roadmap

- [ ] Skill: Organic Content Analysis (port từ phan_tich_organic_w1.html)
- [ ] Skill: Lead Reconciliation (đối chiếu ads leads vs tracking sheet sales)
- [ ] FB post embed trong report (iframe)
- [ ] Persistent DB (Supabase)
- [ ] Optional password gate
