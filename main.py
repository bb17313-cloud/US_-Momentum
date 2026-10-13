import os
import json
import re
import html
import time
import requests
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

# ================================
# إعدادات التلغرام والبيئة
# ================================
TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

RIYADH = ZoneInfo("Asia/Riyadh")
NEW_YORK = ZoneInfo("America/New_York")
SEEN_FILE = "seen_stocks.json"
MAX_SHOWN = 20

# ================================
# إدارة جلسات السوق الثلاث
# ================================
def get_current_session():
    now_ny = datetime.now(NEW_YORK)
    
    if now_ny.weekday() in [5, 6]:
        return "closed", "⏸️ المغلق (عطلة نهاية الأسبوع)"

    time_num_ny = now_ny.hour * 100 + now_ny.minute

    if 400 <= time_num_ny < 930:
        return "premarket", "🌅 Pre-Market (ما قبل الافتتاح)"
    elif 930 <= time_num_ny < 1600:
        return "market", "🔔 Main Session (السوق الرئيسي)"
    elif 1600 <= time_num_ny < 2000:
        return "postmarket", "🌙 Post-Market (ما بعد الإغلاق)"
    else:
        return "closed", "⏸️ المغلق (خارج أوقات التداول)"

def load_seen():
    today = datetime.now(RIYADH).strftime("%Y-%m-%d")
    session_key, _ = get_current_session()
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today and data.get("session") == session_key:
                return data.get("stocks", {})
    except Exception as e:
        print(f"⚠️ خطأ في قراءة ملف السجل: {e}")
    return {}

def save_seen(stocks_data):
    today = datetime.now(RIYADH).strftime("%Y-%m-%d")
    session_key, _ = get_current_session()
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "date": today,
                "session": session_key,
                "stocks": stocks_data,
                "last_update": datetime.now(RIYADH).strftime("%H:%M:%S")
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ خطأ في حفظ ملف السجل: {e}")

# ================================
# تحليل ووصف إفصاحات SEC
# ================================
def get_sec_description(f_form, item_val="", doc_text=""):
    f_upper = f_form.upper()
    item_str = str(item_val)
    text_lower = doc_text.lower() if doc_text else ""

    if f_upper == "10-K":
        if "item 1a" in text_lower or "risk factors" in text_lower:
            return "عوامل المخاطرة"
        elif "item 7" in text_lower:
            return "تحليل الإدارة للوضع المالي"
        elif "item 8" in text_lower:
            return "القوائم المالية"
        elif "item 3" in text_lower:
            return "القضايا والإجراءات القانونية"
        elif "item 9a" in text_lower:
            return "الضوابط والإجراءات الرقابية"
        return "التقرير المالي السنوي"

    if f_upper == "10-Q":
        if "item 2" in text_lower or "md&a" in text_lower:
            return "تحليل الإدارة الفصلي"
        elif "item 1a" in text_lower:
            return "عوامل المخاطرة الجديدة"
        return "القوائم المالية الفصلية"

    if f_upper == "8-K":
        if "1.01" in item_str:
            return "اتفاقية جوهرية جديدة"
        elif "2.01" in item_str:
            return "استحواذ أو بيع أصول"
        elif "2.02" in item_str:
            return "نتائج الأرباح الأولية"
        elif "5.02" in item_str:
            return "تغييرات الإدارة التنفيذية"
        elif "3.02" in item_str:
            return "مبيعات أسهم غير مسجلة"
        elif "8.01" in item_str:
            return "أحداث جوهرية أخرى"
        return "إفصاح جوهري طارئ"

    if "14A" in f_upper:
        if "compensation" in text_lower:
            return "مكافآت التنفيذيين"
        elif "ownership" in text_lower:
            return "ملكية كبار الملاك"
        return "حوكمة الشركات"

    if f_upper == "6-K":
        return "تقرير شركة أجنبية"

    if f_upper.startswith("424B") or any(f_upper.startswith(p) for p in ["S-1", "S-3", "F-1", "F-3"]):
        if "warrant" in text_lower or "exhibit" in text_lower:
            return "اتفاقيات ومرفقات الإصدار"
        return "نشرة طرح واكتتاب أسهم"

    return "إفصاح رسمي معتمد"

# ================================
# جلب إفصاحات SEC فقط
# ================================
def fetch_sec_filings_only(symbol):
    symbol = symbol.upper().strip()
    sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
    filings = []
    cik_str_val = None

    try:
        tickers_res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers, timeout=5)
        if tickers_res.status_code == 200:
            tickers_data = tickers_res.json()
            cik = None
            cik_raw = None
            for idx, val in tickers_data.items():
                if val.get("ticker", "").upper() == symbol:
                    cik = str(val.get("cik_str")).zfill(10)
                    cik_raw = str(val.get("cik_str"))
                    cik_str_val = cik_raw
                    break

            if cik:
                sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                sub_res = requests.get(sub_url, headers=sec_headers, timeout=5)
                if sub_res.status_code == 200:
                    recent = sub_res.json().get("filings", {}).get("recent", {})
                    forms = recent.get("form", [])
                    accession_numbers = recent.get("accessionNumber", [])
                    primary_docs = recent.get("primaryDocument", [])
                    filing_dates = recent.get("filingDate", [])
                    items_list = recent.get("items", [])

                    for i in range(min(10, len(forms))):
                        f_form = forms[i]
                        f_date = filing_dates[i]
                        acc_num = accession_numbers[i]
                        acc_clean = acc_num.replace("-", "")
                        p_doc = primary_docs[i]
                        item_val = items_list[i] if i < len(items_list) else ""

                        if p_doc:
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{p_doc}"
                        else:
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{acc_num}-index.htm"

                        doc_text = ""
                        if f_form.upper() in ["10-K", "10-Q", "8-K", "6-K"] or f_form.upper().startswith("424B"):
                            try:
                                doc_res = requests.get(filing_url, headers=sec_headers, timeout=3)
                                if doc_res.status_code == 200:
                                    doc_text = doc_res.text
                            except Exception:
                                pass

                        brief_desc = get_sec_description(f_form, item_val, doc_text)
                        filings.append({
                            "form": f_form, "date": f_date, "url": filing_url,
                            "accession": acc_num, "brief": brief_desc,
                        })
    except Exception as e:
        print(f"⚠️ خطأ في جلب إفصاحات SEC لـ {symbol}: {e}")

    sec_lines = []
    seen_accessions = set()
    for f in filings:
        if f["accession"] in seen_accessions:
            continue
        seen_accessions.add(f["accession"])
        sec_lines.append(f"• <b>{f['form']}</b> ({f['date']}): <a href='{f['url']}'>{f['brief']}</a>")
        if len(sec_lines) >= 5:
            break

    sec_summary = "\n".join(sec_lines) if sec_lines else "• لا توجد إفصاحات حديثة"
    latest_accession = filings[0]["accession"] if filings else ""

    return sec_summary, cik_str_val, latest_accession

# ================================
# جلب الأسهم من TradingView API
# ================================
def fetch_filtered_stocks(session_type):
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }

    columns = [
        "name",                          # 0
        "description",                   # 1
        "close",                         # 2
        "change",                        # 3
        "change_abs",                    # 4
        "volume",                        # 5
        "premarket_close",               # 6
        "premarket_change",              # 7
        "premarket_change_abs",          # 8
        "premarket_volume",              # 9
        "postmarket_close",              # 10
        "postmarket_change",             # 11
        "postmarket_change_abs",         # 12
        "postmarket_volume",             # 13
        "sector",                        # 14
        "industry",                      # 15
        "country",                       # 16
        "exchange",                      # 17
        "average_volume_10d_calc",       # 18
        "relative_volume_10d_calc",      # 19
        "float_shares_outstanding_current"  # 20
    ]

    filters = [
        {"left": "float_shares_outstanding_current", "operation": "less", "right": 500_000_000},
        {"left": "close", "operation": "less", "right": 50.0},
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]}
    ]

    if session_type == "premarket":
        filters.append({"left": "premarket_volume", "operation": "greater", "right": 15_000})
        filters.append({"left": "premarket_change", "operation": "greater", "right": 2.0})
        sort_by = "premarket_change"
    elif session_type == "postmarket":
        filters.append({"left": "postmarket_volume", "operation": "greater", "right": 15_000})
        filters.append({"left": "postmarket_change", "operation": "greater", "right": 2.0})
        sort_by = "postmarket_change"
    else:
        filters.append({"left": "volume", "operation": "greater", "right": 30_000})
        filters.append({"left": "change", "operation": "greater", "right": 2.0})
        filters.append({"left": "average_volume_10d_calc", "operation": "greater", "right": 50_000})
        filters.append({"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.2})
        sort_by = "change"

    payload = {
        "filter": filters,
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": {"sortBy": sort_by, "sortOrder": "desc"},
        "range": [0, MAX_SHOWN]
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json().get("data", [])
        return data
    except Exception as e:
        print(f"❌ خطأ أثناء جلب البيانات: {e}")
        return []

# ================================
# أدوات المساعدة والإرسال
# ================================
def escape_html(text):
    if not text:
        return "غير محدد"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def format_number(num):
    if not num:
        return "0"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return f"{num:.2f}"

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        return False
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ خطأ في إرسال التليجرام: {e}")
        return False

def send_in_chunks(header, blocks):
    current_message = header + "\n\n"
    for block in blocks:
        if len(current_message) + len(block) + 2 > 3900:
            send_telegram(current_message)
            current_message = block + "\n\n"
        else:
            current_message += block + "\n\n"
    if current_message.strip():
        send_telegram(current_message)

# ================================
# التنفيذ الرئيسي
# ================================
def main():
    now_str = datetime.now(RIYADH).strftime("%H:%M:%S")
    session_key, session_name = get_current_session()

    if session_key == "closed":
        print(f"⏸️ [{now_str}] السوق مغلق حالياً ({session_name}).")
        return

    print(f"⏰ [{now_str}] جاري الفحص | الجلسة: {session_name}")
    stocks = fetch_filtered_stocks(session_key)

    if stocks:
        session_stocks = load_seen()
        header = (
            f"🇺🇸 <b>رادار الإفصاحات والأسهم</b>\n"
            f"⏱️ <b>الجلسة:</b> {session_name} | <code>{now_str} KSA</code>\n"
            f"────────────────────────"
        )
        
        blocks = []
        for item in stocks:
            d = item.get("d", [])
            if len(d) < 18:
                continue

            symbol = escape_html(d[0])
            
            regular_close = d[2]
            regular_change = d[3]
            regular_change_abs = d[4]
            regular_volume = d[5]

            pre_close = d[6]
            pre_change = d[7]
            pre_change_abs = d[8]
            pre_volume = d[9]

            post_close = d[10]
            post_change = d[11]
            post_change_abs = d[12]
            post_volume = d[13]

            sector = escape_html(d[14] or "")
            industry = escape_html(d[15] or "")
            country = escape_html(d[16] or "")
            exchange = escape_html(d[17] or "")

            if session_key == "premarket" and pre_close is not None:
                price = float(pre_close)
                change_pct = float(pre_change) if pre_change is not None else 0.0
                volume = float(pre_volume or 0)
            elif session_key == "postmarket" and post_close is not None:
                price = float(post_close)
                change_pct = float(post_change) if post_change is not None else 0.0
                volume = float(post_volume or 0)
            else:
                price = float(regular_close or 0)
                change_pct = float(regular_change) if regular_change is not None else 0.0
                volume = float(regular_volume or 0)

            if abs(change_pct) < 0.001 and price > 0 and regular_change_abs is not None:
                try:
                    prev_close = price - float(regular_change_abs)
                    if prev_close > 0:
                        change_pct = (float(regular_change_abs) / prev_close) * 100
                except Exception:
                    pass

            sec_summary, cik_code, latest_acc = fetch_sec_filings_only(symbol)

            should_send = False
            alert_count = 1

            if symbol not in session_stocks:
                should_send = True
                alert_count = 1
            else:
                prev_data = session_stocks[symbol]
                prev_price = prev_data.get("price", 0)
                prev_acc = prev_data.get("latest_acc", "")
                prev_count = prev_data.get("count", 1)

                price_increased = price > prev_price
                new_filing = latest_acc != prev_acc

                if price_increased or new_filing:
                    should_send = True
                    alert_count = prev_count + 1
                else:
                    should_send = False

            if not should_send:
                continue

            session_stocks[symbol] = {
                "count": alert_count,
                "price": price,
                "latest_acc": latest_acc
            }

            alert_title = "🚨 Alert" if alert_count == 1 else f"🚨 Alert {alert_count}"
            tv_url = f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"
            sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={cik_code}" if cik_code else "https://www.sec.gov/edgar/searchedgar/companysearch"

            lines = [
                f"<b>{alert_title} | {symbol}</b>  {country}",
                f"🏷 {sector} • {industry}",
                f"💵 <b>${price:.4f}</b>  {change_pct:+.2f}%  |  Vol {format_number(volume)}",
                f"📄 {sec_summary}",
                f"🔗 <a href='{sec_browse_url}'>SEC</a>  •  <a href='{tv_url}'>TV</a>",
                "──────────────"
            ]
            blocks.append("\n".join(lines))

        save_seen(session_stocks)
        if blocks:
            send_in_chunks(header, blocks)
            print(f"✅ تم إرسال {len(blocks)} تنبيه إفصاحات جديد بنجاح.")
        else:
            print(f"ℹ [{now_str}] لا توجد تغيرات أو إفصاحات جديدة تستدعي الإرسال في هذه الدورة.")
    else:
        print(f"ℹ [{now_str}] لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    main()
