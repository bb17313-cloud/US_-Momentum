import os
import json
import re
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
# تحليل وتعميق جلب بيانات SEC للتقسيم العكسي، الورنتس، الإفصاحات، والمحفزات
# ================================
def fetch_sec_filings_and_catalysts(symbol, check_split=True):
    """
    تحليل نصوص وإفصاحات SEC + أخبار المحفزات الإيجابية (Forward Catalysts):
    1. التقسيم العكسي (للأسهم < $1.0).
    2. الورنتس والإصدارات القابلة للتنفيذ (الكمية + سعر التنفيذ).
    3. أحدث إفصاحات SEC الرسمية.
    4. أخبار المحفزات الإيجابية (Forward Catalysts) من SEC وأخبار Yahoo RSS.
    """
    symbol = symbol.upper().strip()
    sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
    
    split_info = None
    offering_info = None
    sec_filings_list = []
    catalysts = []

    try:
        # 1. الحصول على CIK للسهم
        tickers_res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers, timeout=5)
        if tickers_res.status_code != 200:
            return split_info, offering_info, "غير متاح", "لا توجد محفزات رصدت مؤخراً"

        tickers_data = tickers_res.json()
        cik = None
        cik_raw = None
        for idx, val in tickers_data.items():
            if val.get("ticker", "").upper() == symbol:
                cik = str(val.get("cik_str")).zfill(10)
                cik_raw = str(val.get("cik_str"))
                break

        if not cik:
            return split_info, offering_info, "غير متاح", "لا توجد محفزات رصدت مؤخراً"

        # 2. جلب قائمة الإفصاحات الحديثة
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        sub_res = requests.get(sub_url, headers=sec_headers, timeout=5)
        if sub_res.status_code == 200:
            recent = sub_res.json().get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accession_numbers = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            filing_dates = recent.get("filingDate", [])
            doc_descs = recent.get("primaryDocDescription", [])
            items_list = recent.get("items", [])

            # تجميع أحدث 4 إفصاحات للعرض
            seen_forms = []
            for i in range(min(12, len(forms))):
                f_form = forms[i]
                f_date = filing_dates[i]
                if len(seen_forms) < 4:
                    seen_forms.append(f"{f_form} ({f_date})")

                acc_num = accession_numbers[i]
                acc_clean = acc_num.replace("-", "")
                p_doc = primary_docs[i]
                desc = doc_descs[i] if i < len(doc_descs) else ""
                item_val = items_list[i] if i < len(items_list) else ""

                # أ) البحث عن التقسيم العكسي (للأسهم < 1.0$)
                if check_split and not split_info and f_form in ["6-K", "8-K", "DEF 14A", "424B5"]:
                    if "split" in desc.lower() or "consolidation" in desc.lower() or f_form in ["6-K", "8-K"]:
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{p_doc}"
                        try:
                            doc_res = requests.get(doc_url, headers=sec_headers, timeout=4)
                            if doc_res.status_code == 200:
                                text_clean = re.sub('<[^<]+?>', ' ', doc_res.text)
                                ratio_match = re.search(r'(?:ratio\s+of\s+|ratio\s*)?1\s*[-:\s]\s*for\s*[-:\s]*(\d+)|1\s*[:/]\s*(\d+)\s*reverse', text_clean, re.IGNORECASE)
                                date_match = re.search(r'(?:effective|scheduled|expected|execution)\s*(?:on|date)?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})', text_clean, re.IGNORECASE)

                                if ratio_match:
                                    r_val = ratio_match.group(1) or ratio_match.group(2)
                                    d_str = date_match.group(1) if date_match else f_date
                                    split_info = f"مجدول (1:{r_val}) بتاريخ {d_str} (إفصاح {f_form})"
                                elif "reverse split" in text_clean.lower():
                                    split_info = f"معلن بإفصاح {f_form} بتاريخ {f_date}"
                        except Exception:
                            pass

                # ب) الورنتس والإصدارات القابلة للتنفيذ
                if not offering_info and f_form in ["424B5", "S-1", "F-1", "S-3", "F-3", "8-K", "6-K"]:
                    if f_form in ["424B5", "S-1", "F-1"] or "warrant" in desc.lower() or "offering" in desc.lower() or "issuance" in desc.lower():
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{p_doc}"
                        try:
                            doc_res = requests.get(doc_url, headers=sec_headers, timeout=4)
                            if doc_res.status_code == 200:
                                text_clean = re.sub('<[^<]+?>', ' ', doc_res.text)
                                ex_price_match = re.search(r'(?:exercise\s+price|offering\s+price|purchase\s+price)\s+(?:of|is|equal\s+to)?\s*\$?\s*([0-9]+\.?[0-9]*)|\$([0-9]+\.?[0-9]*)\s+per\s+(?:warrant|share)', text_clean, re.IGNORECASE)
                                qty_match = re.search(r'(?:up\s+to\s+)?([0-9,]+)\s*(?:warrants|shares|common\s+shares|units)', text_clean, re.IGNORECASE)

                                ex_p = f"${ex_price_match.group(1) or ex_price_match.group(2)}" if ex_price_match else "غير محدد"
                                qty = f"{qty_match.group(1)}" if qty_match else "غير محددة"
                                offering_info = f"طرح/إصدار {f_form} ({f_date}) | الكمية: {qty} | سعر التنفيذ: {ex_p}"
                        except Exception:
                            pass

                # ج) فحص أخبار المحفزات الإيجابية من إفصاحات SEC الرسمية
                desc_lower = desc.lower()
                if "1.01" in str(item_val) or "entry into a material definitive agreement" in desc_lower:
                    catalysts.append(f"اتفاقية جوهرية جديدة (8-K {f_date})")
                elif "2.02" in str(item_val) or "results of operations" in desc_lower or "earnings" in desc_lower:
                    catalysts.append(f"إعلان نتائج مالية/أرباح (8-K {f_date})")
                elif "fda" in desc_lower or "pdufa" in desc_lower or "approval" in desc_lower:
                    catalysts.append(f"موافقة/إفصاح FDA (إفصاح {f_form} {f_date})")
                elif "patent" in desc_lower:
                    catalysts.append(f"براءة اختراع جديدة (إفصاح {f_form} {f_date})")
                elif "trial" in desc_lower or "phase" in desc_lower:
                    catalysts.append(f"تجارب سريرية (إفصاح {f_form} {f_date})")
                elif "contract" in desc_lower or "partnership" in desc_lower:
                    catalysts.append(f"عقد/شراكة استراتيجية (إفصاح {f_form} {f_date})")

            sec_filings_list = seen_forms

    except Exception as e:
        print(f"⚠️ خطأ جلب بيانات SEC لـ {symbol}: {e}")

    # 3. جلب الأخبار الإضافية من Yahoo RSS لرصد المحفزات الإيجابية (Forward Catalysts)
    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        rss_res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if rss_res.status_code == 200:
            titles = re.findall(r'<title>(.*?)</title>', rss_res.text)
            for t in titles[1:8]:
                t_lower = t.lower()
                if any(kw in t_lower for kw in ["fda", "approval", "pdufa", "phase 1", "phase 2", "phase 3", "contract", "partnership", "earnings", "patent", "buyback", "acquisition", "merger"]):
                    clean_t = t.replace("&quot;", '"').replace("&amp;", "&")
                    if len(clean_t) > 65:
                        clean_t = clean_t[:62] + "..."
                    catalysts.append(f"خبر: {clean_t}")
    except Exception as e:
        print(f"⚠️ خطأ جلب أخبار Yahoo لـ {symbol}: {e}")

    sec_summary = ", ".join(sec_filings_list) if sec_filings_list else "لا توجد إفصاحات حديثة"
    
    # تنقية وتنسيق المحفزات الفريدة
    unique_catalysts = list(dict.fromkeys(catalysts))
    catalyst_str = " | ".join(unique_catalysts[:2]) if unique_catalysts else "لا توجد محفزات إيجابية رصدت مؤخراً"

    return split_info, offering_info, sec_summary, catalyst_str

# ================================
# الدوال الرئيسية مع المصادر البديلة
# ================================
def check_reverse_split_schedule(symbol):
    """فحص التقسيم العكسي (مفعل فقط للأسهم أقل من 1.0$)"""
    symbol = symbol.upper().strip()

    # 1. البحث في إفصاحات SEC المباشرة لقراءة النسبة والتاريخ بدقة
    sec_split, _, _, _ = fetch_sec_filings_and_catalysts(symbol, check_split=True)
    if sec_split:
        return sec_split

    # 2. البحث في تقويم Nasdaq
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    try:
        cal_url = "https://api.nasdaq.com/api/calendar/splits"
        res_cal = requests.get(cal_url, headers=headers, timeout=5)
        if res_cal.status_code == 200:
            rows = res_cal.json().get("data", {}).get("rows", []) or []
            for r in rows:
                if r.get("symbol", "").upper() == symbol:
                    ratio = r.get("ratio", "")
                    exec_date = r.get("executionDate", "")
                    return f"مجدول ({ratio}) بتاريخ {exec_date}"
    except Exception as e:
        print(f"⚠️ خطأ Nasdaq Split Calendar لـ {symbol}: {e}")

    return "لا توجد جدولة معلنة"

def check_warrants_and_issuances(symbol):
    """فحص الورنتس والإصدارات والكمية وسعر التنفيذ لجميع الأسهم المرسلة"""
    symbol = symbol.upper().strip()

    # 1. البحث في SEC EDGAR لاستخراج الكمية وسعر التنفيذ من وثيقة الطرح/الإصدار الرسمية
    _, sec_offering, _, _ = fetch_sec_filings_and_catalysts(symbol, check_split=False)
    if sec_offering:
        return sec_offering

    # 2. البحث عن الورنتس المباشرة المسجلة في TradingView
    try:
        tv_url = "https://scanner.tradingview.com/america/scan"
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        warrant_candidates = [f"{symbol}W", f"{symbol}.WS", f"{symbol}-WT", f"{symbol}WS", f"{symbol}.W"]
        payload = {
            "filter": [{"left": "name", "operation": "in_range", "right": warrant_candidates}],
            "columns": ["name", "close"],
            "range": [0, 5]
        }
        res = requests.post(tv_url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            w_data = res.json().get("data", [])
            if w_data:
                w_item = w_data[0].get("d", [])
                w_name = w_item[0]
                w_price = w_item[1] if len(w_item) > 1 and w_item[1] is not None else 0.0
                return f"ورنتس متداولة بالسوق ({w_name}) | سعر الورنت الحالي: ${w_price:.2f}"
    except Exception as e:
        print(f"⚠️ خطأ TradingView Warrants لـ {symbol}: {e}")

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
            sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={symbol}"

            # جلب تفاصيل SEC والمحفزات والورنتس والتقسيم العكسي
            split_sched, warrants_info, sec_summary, catalyst_str = fetch_sec_filings_and_catalysts(
                symbol, 
                check_split=(price < 1.0)
            )

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

            # 1. التقسيم العكسي: للأسهم أقل من $1.0 فقط
            if price < 1.0:
                lines.append(f"<b>SCHEDULE to splitting:</b> {split_sched or 'لا توجد جدولة معلنة'}")

            # 2. الورنتس والإصدارات القابلة للتنفيذ (لكل الأسهم)
            lines.append(f"<b>ورنتس / إصدارات قابلة للتنفيذ:</b> {warrants_info or 'لا توجد ورنتس/إصدارات معلنة مؤخراً'}")

            # 3. أخبار المحفزات الإيجابية (Forward Catalysts)
            lines.append(f"<b>اخبار المحفزات الإيجابية (Forward Catalysts):</b> {catalyst_str}")

            # 4. إفصاحات SEC الرسمية مع رابط مباشر
            lines.append(f"<b>إفصاحات SEC:</b> {sec_summary} | <a href='{sec_browse_url}'>عرض الإفصاحات</a>")

            # 5. رابط الشارت
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
