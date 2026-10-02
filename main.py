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
# دالة تلخيص وتحليل مضمون نماذج SEC
# ================================
def get_form_description(f_form, doc_desc="", item_val="", doc_text=""):
    f_upper = f_form.upper()
    desc_lower = doc_desc.lower()
    item_str = str(item_val)
    text_clean = re.sub('<[^<]+?>', ' ', doc_text) if doc_text else ""

    # Form D (طرح خاص / إعفاء تنظيم D)
    if f_upper == "D":
        if "notice of exempt offering of securities" in desc_lower or "offering" in text_clean.lower():
            return "إشعار طرح خاص للأوراق المالية (Regulation D)"
        return "إشعار طرح أوراق مالية مستثناة (Form D)"

    # Form 4 (تغييرات ملكية المطلعين - تحديد شراء أو بيع)
    if f_upper == "4":
        if text_clean:
            # البحث عن رموز المعاملات P (شراء) أو S (بيع) في نماذج المطلعين
            if re.search(r'\bcode\s*[:\-]?\s*P\b', text_clean, re.IGNORECASE) or "purchase" in text_clean.lower() or "acquire" in text_clean.lower():
                return "شراء أسهم من قبل مطلع (Insider Purchase)"
            elif re.search(r'\bcode\s*[:\-]?\s*S\b', text_clean, re.IGNORECASE) or "sale" in text_clean.lower() or "dispose" in text_clean.lower():
                return "بيع أسهم من قبل مطلع (Insider Sale)"
        if "sale" in desc_lower:
            return "بيع أسهم من قبل مطلع (Insider Sale)"
        elif "purchase" in desc_lower or "award" in desc_lower:
            return "شراء/حيازة أسهم من قبل مطلع"
        return "تغييرات ملكية مطلع (شراء/بيع أسهم)"

    # 1. تحليل نماذج النشرات والطرح 424B / S-1 / F-1 / S-3 (استخراج الأرقام بدقة)
    if f_upper.startswith("424B") or any(f_upper.startswith(p) for p in ["S-1", "F-1", "S-3", "F-3"]):
        if text_clean:
            resale_match = re.search(r'(?:resale\s+of\s+up\s+to|resale\s+of)\s+([0-9,]+)\s+shares(?:\s+of\s+class\s+a|\s+of\s+common\s+stock)?', text_clean, re.IGNORECASE)
            offering_match = re.search(r'(?:offering\s+of\s+up\s+to|offering\s+of)\s+([0-9,]+)\s+shares', text_clean, re.IGNORECASE)
            
            if resale_match:
                class_a = " (Class A)" if "class a" in text_clean.lower() else ""
                return f"إعادة بيع حتى {resale_match.group(1)} سهم من العادية{class_a}"
            elif offering_match:
                return f"طرح/إصدار حتى {offering_match.group(1)} سهم عادي"

        if "resale" in desc_lower or "selling stockholder" in desc_lower:
            return "إعادة بيع أسهم مملوكة لمساهمين"
        elif "warrant" in desc_lower:
            return "نشرة طرح/إصدار أسهم وورنتس"
        return "نشرة طرح/إصدار أسهم عادية"

    # 2. نموذج 8-K للأحداث الجوهرية (تحديد البند والمضمون بدقة)
    if f_upper == "8-K":
        if "1.01" in item_str or "material definitive agreement" in desc_lower:
            return "اتفاقية جوهرية جديدة (البند 1.01)"
        elif "2.02" in item_str or "results of operations" in desc_lower or "earnings" in desc_lower:
            return "إعلان نتائج مالية وأرباح (البند 2.02)"
        elif "3.01" in item_str or "delisting" in desc_lower:
            return "إشعار شروط الإدراج والامتثال (البند 3.01)"
        elif "5.02" in item_str or "director" in desc_lower:
            return "تغييرات بالإدارة ومجلس الإدارة (البند 5.02)"
        elif "7.01" in item_str or "regulation fd" in desc_lower:
            return "إفصاح تنظيم الإفصاح العادل FD (البند 7.01)"
        elif "8.01" in item_str or "other events" in desc_lower:
            return "أحداث ومعلومات جوهرية أخرى (البند 8.01)"
        
        if doc_desc:
            return f"حدث جوهري: {doc_desc[:40].strip()}"
        return "إفصاح عن أحداث جوهرية (Form 8-K)"

    # 3. نموذج 6-K للشركات الأجنبية
    if f_upper == "6-K":
        if "fda" in desc_lower:
            return "تطورات وموافقات FDA"
        elif "split" in desc_lower:
            return "إفصاح تقسيم أسهم"
        elif "financial" in desc_lower or "earnings" in desc_lower:
            return "نتائج وتقارير مالية"
        if doc_desc:
            return f"تقرير أجنبي: {doc_desc[:40].strip()}"
        return "تقرير جوهري لشركة أجنبية (6-K)"

    # 4. ملكية كبار المساهمين والمطلعين
    if "13G" in f_upper or "13D" in f_upper:
        return "إفصاح ملكية كبار المساهمين (>5%)"
    if f_upper == "425":
        return "بيانات متعلقة بصفقة اندماج/استحواذ"
    if "14A" in f_upper:
        return "توكيل تصويت اجتماعات المساهمين"
    if f_upper in ["10-K", "20-F"]:
        return "التقرير المالي السنوي"
    if f_upper == "10-Q":
        return "التقرير المالي الربع سنوي"

    if doc_desc:
        clean_desc = doc_desc[:40].strip()
        return f"{clean_desc}"

    return "إفصاح رسمي معتمد"

# ================================
# تحليل وتعميق جلب بيانات SEC للتقسيم العكسي، الورنتس، الإفصاحات، والمحفزات
# ================================
def fetch_sec_filings_and_catalysts(symbol, check_split=True):
    symbol = symbol.upper().strip()
    sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
    
    split_info = None
    offering_info = None
    sec_filings_details = []
    catalysts = []
    cik_str_val = None

    try:
        # 1. الحصول على CIK للسهم
        tickers_res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers, timeout=5)
        if tickers_res.status_code != 200:
            return split_info, offering_info, "غير متاح", "لا توجد محفزات رصدت مؤخراً", None

        tickers_data = tickers_res.json()
        cik = None
        cik_raw = None
        for idx, val in tickers_data.items():
            if val.get("ticker", "").upper() == symbol:
                cik = str(val.get("cik_str")).zfill(10)
                cik_raw = str(val.get("cik_str"))
                cik_str_val = cik_raw
                break

        if not cik:
            return split_info, offering_info, "غير متاح", "لا توجد محفزات رصدت مؤخراً", None

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

            for i in range(min(12, len(forms))):
                f_form = forms[i]
                f_date = filing_dates[i]
                f_upper = f_form.upper()
                acc_num = accession_numbers[i]
                acc_clean = acc_num.replace("-", "")
                p_doc = primary_docs[i]
                desc = doc_descs[i] if i < len(doc_descs) else ""
                item_val = items_list[i] if i < len(items_list) else ""

                doc_text = ""
                if f_upper.startswith("424B") or f_upper in ["6-K", "8-K", "S-1", "F-1", "4"]:
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{p_doc}"
                    try:
                        doc_res = requests.get(doc_url, headers=sec_headers, timeout=3.5)
                        if doc_res.status_code == 200:
                            doc_text = doc_res.text
                    except Exception:
                        pass

                brief_desc = get_form_description(f_form, desc, item_val, doc_text)
                if len(sec_filings_details) < 4:
                    sec_filings_details.append(f"• <b>{f_form}</b> ({f_date}): {brief_desc}")

                # أ) البحث عن التقسيم العكسي (للأسهم < 1.0$)
                if check_split and not split_info and f_upper in ["6-K", "8-K", "DEF 14A", "PRE 14A", "424B5", "424B3"]:
                    if doc_text:
                        text_clean = re.sub('<[^<]+?>', ' ', doc_text)
                        ratio_match = re.search(r'(?:ratio\s+of\s+|ratio\s*)?1\s*[-:\s]\s*for\s*[-:\s]*(\d+)|1\s*[:/]\s*(\d+)\s*reverse', text_clean, re.IGNORECASE)
                        date_match = re.search(r'(?:effective|scheduled|expected|execution)\s*(?:on|date)?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})', text_clean, re.IGNORECASE)

                        if ratio_match:
                            r_val = ratio_match.group(1) or ratio_match.group(2)
                            d_str = date_match.group(1) if date_match else f_date
                            split_info = f"مجدول (1:{r_val}) بتاريخ {d_str} (إفصاح {f_form})"
                        elif "reverse split" in text_clean.lower():
                            split_info = f"معلن بإفصاح {f_form} بتاريخ {f_date}"

                # ب) الورنتس والإصدارات القابلة للتنفيذ
                if not offering_info and (f_upper.startswith("424B") or f_upper.startswith("S-") or f_upper.startswith("F-") or f_upper in ["8-K", "6-K"]):
                    if doc_text:
                        text_clean = re.sub('<[^<]+?>', ' ', doc_text)
                        ex_price_match = re.search(r'(?:exercise\s+price|offering\s+price|purchase\s+price|public\s+offering\s+price)\s+(?:of|is|equal\s+to|at)?\s*\$?\s*([0-9]+\.?[0-9]*)|\$([0-9]+\.?[0-9]*)\s+per\s+(?:warrant|share|unit)', text_clean, re.IGNORECASE)
                        qty_match = re.search(r'(?:up\s+to\s+|offering\s+of\s+|resale\s+of\s+up\s+to\s+)?([0-9,]{4,})\s*(?:warrants|shares|common\s+shares|units)', text_clean, re.IGNORECASE)

                        ex_p = f"${ex_price_match.group(1) or ex_price_match.group(2)}" if ex_price_match else None
                        qty = f"{qty_match.group(1)}" if qty_match else None

                        if ex_p and qty:
                            offering_info = f"طرح/إصدار {f_form} ({f_date}) | الكمية: {qty} | سعر التنفيذ/الطرح: {ex_p}"
                        elif qty:
                            offering_info = f"طرح/إصدار {f_form} ({f_date}) | الكمية: {qty} سهم"
                        elif ex_p:
                            offering_info = f"طرح/إصدار {f_form} ({f_date}) | سعر التنفيذ: {ex_p}"
                        else:
                            offering_info = f"نشرة طرح/إعادة بيع معلنة ({f_form} {f_date})"
                    elif f_upper.startswith("424B"):
                        offering_info = f"نشرة طرح/إعادة بيع معلنة ({f_form} {f_date})"

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

    except Exception as e:
        print(f"⚠️ خطأ جلب بيانات SEC لـ {symbol}: {e}")

    # 3. جلب الأخبار الإضافية من Yahoo RSS لرصد المحفزات الإيجابية
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
        print(f"⚠ خطأ جلب أخبار Yahoo لـ {symbol}: {e}")

    sec_summary = "\n".join(sec_filings_details) if sec_filings_details else "• لا توجد إفصاحات حديثة"
    unique_catalysts = list(dict.fromkeys(catalysts))
    catalyst_str = " | ".join(unique_catalysts[:2]) if unique_catalysts else "لا توجد محفزات رصدت مؤخراً"

    return split_info, offering_info, sec_summary, catalyst_str, cik_str_val

# ================================
# الدوال الرئيسية مع المصادر البديلة
# ================================
def check_reverse_split_schedule(symbol):
    sec_split, _, _, _, _ = fetch_sec_filings_and_catalysts(symbol, check_split=True)
    if sec_split:
        return sec_split
    return "لا توجد جدولة معلنة"

def check_warrants_and_issuances(symbol):
    _, sec_offering, _, _, _ = fetch_sec_filings_and_catalysts(symbol, check_split=False)
    if sec_offering:
        return sec_offering
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
            price_field,     # Index 2
            change_field,    # Index 3
            volume_field,    # Index 4
            "sector",        # Index 5
            "industry",      # Index 6
            "country",       # Index 7
            "exchange",      # Index 8
            "close"          # Index 9
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
            f"⏱️ <b>الجلسة:</b> {session_name} | <code>{now_str} KSA</code>\n"
            f"────────────────────────"
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

            # جلب تفاصيل SEC مع CIK الحقيقي المباشر لصفحة الشركة المخصصة
            split_sched, warrants_info, sec_summary, catalyst_str, cik_code = fetch_sec_filings_and_catalysts(
                symbol, 
                check_split=(price < 1.0)
            )

            # رابط صفحة الإفصاحات الخاصة بالشركة عبر CIK في SEC
            if cik_code:
                sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={cik_code}"
            else:
                sec_browse_url = f"https://www.sec.gov/edgar/searchedgar/companysearch"

            # تنسيق البطاقة بشكل مريح للعين (تصغير الخط وترتيب الأسطر)
            lines = [
                f"<b>{alert_title} | {symbol}</b>",
                f"🏷 <code>{sector}</code> / <code>{industry}</code>",
                f"💵 <b>السعر:</b> <code>${price:.2f}</code> | <b>التغير:</b> <code>{change_pct:+.2f}%</code> | <b>Vol:</b> <code>{format_number(volume)}</code>",
            ]

            if price < 1.0:
                lines.append(f"📉 <b>Reverse Split:</b> {split_sched or 'لا توجد جدولة'}")

            lines.append(f"📋 <b>الإصدارات:</b> {warrants_info or 'لا توجد إصدارات معلنة'}")
            lines.append(f"⚡ <b>المحفزات:</b> {catalyst_str}")
            lines.append(f"📄 <b>إفصاحات SEC:</b>\n{sec_summary}")
            
            # الروابط في سطر واحد منظم ومرتب
            lines.extend([
                f"🔗 <a href='{sec_browse_url}'>إفصاحات SEC</a> | 📊 <a href='{tv_url}'>TradingView</a>",
                "────────────────────────"
            ])
            blocks.append("\n".join(lines))

        save_seen(today, counts)
        send_in_chunks(header, blocks)
        print(f"✅ تم إرسال {len(blocks)} سهم بنجاح.")
    else:
        print(f"ℹ [{now_str}] لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    main()
