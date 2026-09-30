import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ================================
# إعدادات التلغرام والبيئة
# ================================
TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

RIYADH = ZoneInfo("Asia/Riyadh")
SEEN_FILE = "seen_stocks.json"
MAX_SHOWN = 20

# ================================
# إدارة ملف التكرارات والتحقق اليومي
# ================================
def load_seen():
    today = datetime.now(RIYADH).strftime("%Y-%m-%d")
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return today, data.get("counts", {})
    except Exception as e:
        print(f"⚠️ خطأ في قراءة ملف السجل: {e}")
    return today, {}

def save_seen(today, counts):
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "date": today,
                "counts": counts,
                "last_update": datetime.now(RIYADH).strftime("%H:%M:%S")
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ خطأ في حفظ ملف السجل: {e}")

# ================================
# تحديد نوع الجلسة
# ================================
def get_current_session():
    now = datetime.now(RIYADH)
    time_num = now.hour * 100 + now.minute

    if 1100 <= time_num < 1630:
        return "premarket", "🌅 Pre-Market (ما قبل الافتتاح)"
    elif 1630 <= time_num < 2300:
        return "market", "🔔 Main Session (السوق الرئيسي)"
    elif time_num >= 2300 or time_num < 300:
        return "postmarket", "🌙 Post-Market (ما بعد الإغلاق)"
    else:
        return "closed", "⏸️ المغلق (خارج أوقات التداول)"

# ================================
# جلب بيانات التقسيم العكسي والورنتس بدقة عالية
# ================================
def check_reverse_split_schedule(symbol):
    """
    فحص جدول التقسيم العكسي المجدول عبر Nasdaq API و Nasdaq Calendar و SEC EDGAR
    مع تضمين الترويسات (Origin & Referer) لتفادي حظر الطلبات (HTTP 403)
    """
    symbol = symbol.upper().strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }

    # 1. المصدر الأول: Nasdaq Quote Splits API
    try:
        url = f"https://api.nasdaq.com/api/quote/{symbol}/splits?market=stocks"
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json().get("data", {})
            if data and isinstance(data, dict):
                split_table = data.get("splitTable", {})
                if split_table and "rows" in split_table and split_table["rows"]:
                    rows = split_table["rows"]
                    today_str = datetime.now(RIYADH).strftime("%Y-%m-%d")
                    for r in rows:
                        exec_date = r.get("executionDate", "")
                        ratio = r.get("ratio", "")
                        if exec_date >= today_str:
                            return f"مجدول ({ratio}) بتاريخ {exec_date}"
                        elif ratio and ("1:" in ratio or "1/" in ratio or ":" in ratio):
                            return f"آخر تقسيم: {ratio} بتاريخ {exec_date}"
    except Exception as e:
        print(f"⚠️ خطأ Nasdaq Quote Splits لـ {symbol}: {e}")

    # 2. المصدر الثاني: Nasdaq Splits Calendar API (للتقسيمات المجدولة مستقبلاً)
    try:
        cal_url = "https://api.nasdaq.com/api/calendar/splits"
        res_cal = requests.get(cal_url, headers=headers, timeout=6)
        if res_cal.status_code == 200:
            cal_data = res_cal.json().get("data", {})
            rows = cal_data.get("rows", []) if cal_data else []
            for r in rows:
                if r.get("symbol", "").upper() == symbol:
                    ratio = r.get("ratio", "")
                    exec_date = r.get("executionDate", "")
                    return f"مجدول ({ratio}) بتاريخ {exec_date}"
    except Exception as e:
        print(f"⚠️ خطأ Nasdaq Calendar Splits لـ {symbol}: {e}")

    # 3. المصدر الثالث: SEC EDGAR Filings (للإفصاحات الرسمية للشركات)
    try:
        sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
        tickers_res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers, timeout=5)
        if tickers_res.status_code == 200:
            tickers_data = tickers_res.json()
            cik = None
            for idx, val in tickers_data.items():
                if val.get("ticker", "").upper() == symbol:
                    cik = str(val.get("cik_str")).zfill(10)
                    break
            if cik:
                sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                sub_res = requests.get(sub_url, headers=sec_headers, timeout=5)
                if sub_res.status_code == 200:
                    recent = sub_res.json().get("filings", {}).get("recent", {})
                    forms = recent.get("form", [])
                    doc_descs = recent.get("primaryDocDescription", [])
                    filing_dates = recent.get("filingDate", [])
                    for i in range(min(10, len(forms))):
                        form = forms[i]
                        desc = doc_descs[i] if i < len(doc_descs) else ""
                        f_date = filing_dates[i] if i < len(filing_dates) else ""
                        if form in ["8-K", "6-K"] and ("reverse split" in desc.lower() or "split" in desc.lower()):
                            return f"مذكور بإفصاح رسمى ({form}) بتاريخ {f_date}"
    except Exception as e:
        print(f"⚠️ خطأ SEC EDGAR Splits لـ {symbol}: {e}")

    return "لا توجد جدولة معلنة"

def check_warrants_and_issuances(symbol):
    """
    فحص وجود ورنتس متداولة أو إصدارات وطروحات قابلة للتنفيذ عبر TradingView و SEC EDGAR
    """
    symbol = symbol.upper().strip()
    
    # 1. البحث عن الورنتس في TradingView
    try:
        tv_url = "https://scanner.tradingview.com/america/scan"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
        warrant_candidates = [
            f"{symbol}W", f"{symbol}.WS", f"{symbol}-WT", f"{symbol}WS",
            f"{symbol}.W", f"{symbol}/WS", f"{symbol}+"
        ]
        payload = {
            "filter": [
                {"left": "name", "operation": "in_range", "right": warrant_candidates}
            ],
            "columns": ["name", "close", "description"],
            "range": [0, 5]
        }
        res = requests.post(tv_url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            w_data = res.json().get("data", [])
            if w_data:
                found_warrants = []
                for w in w_data:
                    item = w.get("d", [])
                    if item:
                        w_name = item[0]
                        w_price = item[1] if len(item) > 1 and item[1] is not None else 0.0
                        found_warrants.append(f"{w_name} (${w_price:.2f})")
                if found_warrants:
                    return f"ورنتس متداولة: {', '.join(found_warrants)}"
    except Exception as e:
        print(f"⚠️️ خطأ فحص ورنتس TradingView لـ {symbol}: {e}")

    # 2. فحص إفصاحات الطروحات والإصدارات في SEC EDGAR
    try:
        sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
        tickers_res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers, timeout=5)
        if tickers_res.status_code == 200:
            tickers_data = tickers_res.json()
            cik = None
            for idx, val in tickers_data.items():
                if val.get("ticker", "").upper() == symbol:
                    cik = str(val.get("cik_str")).zfill(10)
                    break
            if cik:
                sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                sub_res = requests.get(sub_url, headers=sec_headers, timeout=5)
                if sub_res.status_code == 200:
                    recent = sub_res.json().get("filings", {}).get("recent", {})
                    forms = recent.get("form", [])
                    doc_descs = recent.get("primaryDocDescription", [])
                    filing_dates = recent.get("filingDate", [])
                    for i in range(min(12, len(forms))):
                        form = forms[i]
                        desc = doc_descs[i] if i < len(doc_descs) else ""
                        f_date = filing_dates[i] if i < len(filing_dates) else ""
                        if form in ["424B5", "S-1", "F-1", "S-3", "F-3"]:
                            return f"طرح/إصدار معلن ({form} بتاريخ {f_date})"
                        elif form in ["8-K", "6-K"]:
                            desc_l = desc.lower()
                            if "warrant" in desc_l or "offering" in desc_l:
                                return f"إفصاح إصدار/ورنتس ({form} بتاريخ {f_date})"
    except Exception as e:
        print(f"⚠️ خطأ فحص SEC EDGAR لـ {symbol}: {e}")

    return "لا توجد ورنتس/إصدارات معلنة مؤخراً"

# ================================
# جلب بيانات الأسهم (TradingView API)
# ================================
def fetch_filtered_stocks(session_type):
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }

    price_field = "close"
    change_field = "change"
    volume_field = "volume"
    
    if session_type == "premarket":
        price_field = "premarket_close"
        change_field = "premarket_change"
        volume_field = "premarket_volume"
    elif session_type == "postmarket":
        price_field = "postmarket_close"
        change_field = "postmarket_change"
        volume_field = "postmarket_volume"

    filters = [
        {"left": "float_shares_outstanding_current", "operation": "less", "right": 500_000_000},
        {"left": volume_field, "operation": "greater", "right": 30_000},
        {"left": change_field, "operation": "greater", "right": 2.0},
        {"left": "average_volume_10d_calc", "operation": "greater", "right": 50_000},
        {"left": "close", "operation": "less", "right": 50.0},
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]}
    ]

    if session_type == "market":
        filters.append({"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.2})

    payload = {
        "filter": filters,
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": [
            "name",          # Index 0
            "description",   # Index 1
            price_field,     # Index 2: السعر المباشر للجلسة الحالية
            change_field,    # Index 3: نسبة التغير للجلسة الحالية
            volume_field,    # Index 4: الحجم للجلسة الحالية
            "sector",        # Index 5
            "industry",      # Index 6
            "country",       # Index 7
            "exchange",      # Index 8
            "close"          # Index 9: سعر إغلاق السوق الرئيسي للتحوط
        ],
        "sort": {"sortBy": change_field, "sortOrder": "desc"},
        "range": [0, MAX_SHOWN]
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json().get("data", [])
        print(f"📊 عدد الأسهم المسترجعة من API: {len(data)}")
        return data
    except Exception as e:
        print(f"❌ خطأ أثناء جلب البيانات: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f" تفاصيل رد السيرفر: {e.response.text}")
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
        print("⚠️ BOT_TOKEN أو CHAT_ID غير محدد في متغيرات البيئة.")
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
        if hasattr(e, 'response') and e.response is not None:
            print(f" تفاصيل رد تليجرام: {e.response.text}")
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
# التنفيذ لمرة واحدة (Single Run)
# ================================
def main():
    today, counts = load_seen()
    now_str = datetime.now(RIYADH).strftime("%H:%M:%S")
    session_key, session_name = get_current_session()

    if session_key == "closed":
        print(f"⏸️ [{now_str}] السوق مغلق حالياً.")
        return

    print(f"⏰ [{now_str}] جاري الفحص | الجلسة: {session_name}")
    stocks = fetch_filtered_stocks(session_key)

    if stocks:
        header = (
            f"🇺🇸 <b>رادار الأسهم الأمريكية</b>\n"
            f"⏱️ <b>الجلسة:</b> {session_name}\n"
            f"📅 <b>الوقت:</b> <code>{now_str} KSA</code>\n"
            f"-----------------------------------"
        )
        
        blocks = []
        for item in stocks:
            d = item.get("d", [])
            if len(d) < 9:
                continue

            symbol = escape_html(d[0])
            price_val = d[2] if d[2] is not None else d[9]
            price = float(price_val or 0)
            
            change_pct = float(d[3] or 0)
            volume = float(d[4] or 0)
            sector = escape_html(d[5])
            industry = escape_html(d[6])
            country = escape_html(d[7])
            exchange = escape_html(d[8])

            curr_count = counts.get(symbol, 0) + 1
            counts[symbol] = curr_count

            alert_title = "🚨 Alert" if curr_count == 1 else f"🚨 Alert {curr_count}"
            tv_url = f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"

            lines = [
                f"{alert_title}",
                f"<b>رمز السهم:</b> {symbol}",
                f"<b>القطاع:</b> {sector}",
                f"<b>الصناعة:</b> {industry}",
                f"<b>الدوله:</b> {country}",
                f"<b>السعر الحالي:</b> ${price:.2f}",
                f"<b>التغير للجلسة الحالية +-٪:</b> {change_pct:+.2f}%",
                f"<b>Vol:</b> {format_number(volume)}"
            ]

            # فحص التقسيم العكسي المجدول للأسهم التي يقل سعرها عن $1.0
            if price < 1.0:
                split_sched = check_reverse_split_schedule(symbol)
                lines.append(f"<b>SCHEDULE to splitting:</b> {split_sched}")

            # فحص الورنتس والإصدارات المعلنة
            warrants_info = check_warrants_and_issuances(symbol)
            lines.append(f"<b>ورنتس / إصدارات قابلة للتنفيذ:</b> {warrants_info}")

            lines.extend([
                f"<b>الشارت TradingView:</b> <a href='{tv_url}'>فتح الشارت</a>",
                "-----------------------------------"
            ])
            blocks.append("\n".join(lines))

        save_seen(today, counts)
        send_in_chunks(header, blocks)
        print(f"✅ تم إرسال {len(blocks)} سهم بنجاح.")
    else:
        print(f"ℹ [{now_str}] لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    main()
