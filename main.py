import os
import json
import re
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
# دالة ترجمة للنصوص (من الإنجليزية إلى العربية)
# ================================
def translate_to_arabic(text):
    if not text:
        return text
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ar&dt=t&q={urllib.parse.quote(text)}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if res.status_code == 200:
            result = res.json()
            translated = "".join([item[0] for item in result[0] if item[0]])
            return translated if translated else text
    except Exception as e:
        print(f"⚠️ خطأ أثناء الترجمة: {e}")
    return text

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
# تحديد نوع الجلسة بدقة بتوقيت نيويورك وتوقيت الرياض
# ================================
def get_current_session():
    now_ny = datetime.now(NEW_YORK)
    
    # فحص العطلة الأسبوعية (السبت والأحد)
    if now_ny.weekday() in [5, 6]:
        return "closed", "⏸️ المغلق (عطلة نهاية الأسبوع)"

    time_num_ny = now_ny.hour * 100 + now_ny.minute

    # Pre-market: 04:00 AM - 09:30 AM EST (11:00 AM - 04:30 PM KSA)
    if 400 <= time_num_ny < 930:
        return "premarket", "🌅 Pre-Market (ما قبل الافتتاح)"
    # Main Market: 09:30 AM - 04:00 PM EST (04:30 PM - 11:00 PM KSA)
    elif 930 <= time_num_ny < 1600:
        return "market", "🔔 Main Session (السوق الرئيسي)"
    # Post-market: 04:00 PM - 08:00 PM EST (11:00 PM - 03:00 AM KSA)
    elif 1600 <= time_num_ny < 2000:
        return "postmarket", "🌙 Post-Market (ما بعد الإغلاق)"
    else:
        return "closed", "⏸️ المغلق (خارج أوقات التداول)"

# ================================
# جلب أحدث الأخبار المباشرة لـ TradingView (مترجمة ومع رابط)
# ================================
def fetch_tradingview_latest_updates(symbol, exchange):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    symbol_param = f"{exchange}:{symbol}"
    url = f"https://news-headlines.tradingview.com/headlines/?category=stock&lang=en&symbol={symbol_param}"

    try:
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200:
            items = res.json()
            if isinstance(items, list) and len(items) > 0:
                latest = items[0]
                title = latest.get("title", "")
                pub_time = latest.get("published", None)
                story_path = latest.get("storyPath", "")
                
                # رابط الخبر المباشر في TradingView
                news_url = f"https://www.tradingview.com{story_path}" if story_path else f"https://www.tradingview.com/symbols/{exchange}-{symbol}/news/"

                time_str = ""
                if pub_time:
                    dt = datetime.fromtimestamp(pub_time, tz=ZoneInfo("UTC")).astimezone(RIYADH)
                    time_str = f" ({dt.strftime('%H:%M')} KSA)"

                if title:
                    # ترجمة عنوان الخبر للغة العربية
                    title_ar = translate_to_arabic(title)
                    return f"<a href='{news_url}'>{title_ar}</a>{time_str} (TradingView)"
    except Exception as e:
        print(f"⚠️ خطأ جلب أخبار TradingView لـ {symbol}: {e}")

    return "لا توجد تحديثات جديدة من TradingView"

# ================================
# دالة تلخيص وتحليل مضمون نماذج SEC
# ================================
def get_form_description(f_form, doc_desc="", item_val="", doc_text=""):
    f_upper = f_form.upper()
    desc_lower = doc_desc.lower()
    item_str = str(item_val)
    text_clean = re.sub('<[^<]+?>', ' ', doc_text) if doc_text else ""

    if f_upper == "D":
        if "notice of exempt offering of securities" in desc_lower or "offering" in text_clean.lower():
            return "إشعار طرح خاص للأوراق المالية (Regulation D)"
        return "إشعار طرح أوراق مالية مستثناة (Form D)"

    if f_upper == "4":
        if text_clean:
            if re.search(r'\bcode\s*[:\-]?\s*P\b', text_clean, re.IGNORECASE) or "purchase" in text_clean.lower() or "acquire" in text_clean.lower():
                return "شراء أسهم من قبل مطلع (Insider Purchase)"
            elif re.search(r'\bcode\s*[:\-]?\s*S\b', text_clean, re.IGNORECASE) or "sale" in text_clean.lower() or "dispose" in text_clean.lower():
                return "بيع أسهم من قبل مطلع (Insider Sale)"
        if "sale" in desc_lower:
            return "بيع أسهم من قبل مطلع (Insider Sale)"
        elif "purchase" in desc_lower or "award" in desc_lower:
            return "شراء/حيازة أسهم من قبل مطلع"
        return "تغييرات ملكية مطلع (شراء/بيع أسهم)"

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
# تحليل جلب بيانات SEC والأخبار (إمكانية استخراج حتى 4 أخبار مهمة)
# ================================
def fetch_sec_filings_and_catalysts(symbol, check_split=True, change_pct=0.0):
    symbol = symbol.upper().strip()
    sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
    
    split_info = None
    offering_info = None
    sec_filings_details = []
    catalysts = []
    cik_str_val = None

    # إضافة خبر تحرك اليوم تلقائياً عند وجود ارتفاع ملحوظ
    if abs(change_pct) >= 10.0:
        dir_str = "ارتفاع" if change_pct > 0 else "انخفاض"
        catalysts.append(f"تحرك اليوم: {dir_str} قوي بنسبة {change_pct:+.2f}%")

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

                        if p_doc:
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{p_doc}"
                        else:
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/{acc_num}-index.htm"

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
                            sec_filings_details.append(f"• <b>{f_form}</b> ({f_date}): <a href='{filing_url}'>{brief_desc}</a>")

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

                            if offering_info:
                                offering_info = f"<a href='{filing_url}'>{offering_info}</a>"

                        desc_lower = desc.lower()
                        catalysts_before = len(catalysts)
                        if "1.01" in str(item_val) or "entry into a material definitive agreement" in desc_lower:
                            catalysts.append(f"اتفاقية جوهرية جديدة (8-K {f_date})")
                        elif "2.02" in str(item_val) or "results of operations" in desc_lower or "earnings" in desc_lower:
                            catalysts.append(f"إعلان نتائج مالية وأرباح (8-K {f_date})")
                        elif "fda" in desc_lower or "pdufa" in desc_lower or "approval" in desc_lower:
                            catalysts.append(f"موافقة/إفصاح FDA (إفصاح {f_form} {f_date})")
                        elif "patent" in desc_lower:
                            catalysts.append(f"براءة اختراع جديدة (إفصاح {f_form} {f_date})")
                        elif "trial" in desc_lower or "phase" in desc_lower:
                            catalysts.append(f"تجارب سريرية (إفصاح {f_form} {f_date})")
                        elif "contract" in desc_lower or "partnership" in desc_lower:
                            catalysts.append(f"عقد/شراكة استراتيجية (إفصاح {f_form} {f_date})")

                        if len(catalysts) > catalysts_before:
                            catalysts[-1] = f"<a href='{filing_url}'>{catalysts[-1]}</a>"

    except Exception as e:
        print(f"⚠️ خطأ جلب بيانات SEC لـ {symbol}: {e}")

    # جلب الأخبار الإضافية من Yahoo RSS مع الترجمة للعربية
    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        rss_res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if rss_res.status_code == 200:
            titles = re.findall(r'<title>(.*?)</title>', rss_res.text)
            links = re.findall(r'<link>(.*?)</link>', rss_res.text)
            for n, t in enumerate(titles[1:8], start=1):
                clean_t = t.replace("&quot;", '"').replace("&amp;", "&")
                if len(clean_t) > 65:
                    clean_t = clean_t[:62] + "..."
                news_link = links[n].strip() if n < len(links) else None
                
                # ترجمة الخبر إلى العربية
                clean_t_ar = translate_to_arabic(clean_t)
                
                if news_link:
                    catalysts.append(f"<a href='{news_link}'>خبر: {clean_t_ar}</a>")
                else:
                    catalysts.append(f"خبر: {clean_t_ar}")
    except Exception as e:
        print(f"⚠ خطأ جلب أخبار Yahoo لـ {symbol}: {e}")

    sec_summary = "\n".join(sec_filings_details) if sec_filings_details else "• لا توجد إفصاحات حديثة"
    unique_catalysts = list(dict.fromkeys(catalysts))
    catalyst_str = " | ".join(unique_catalysts[:4]) if unique_catalysts else "لا توجد محفزات رصدت مؤخراً"

    return split_info, offering_info, sec_summary, catalyst_str, cik_str_val

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
        print(f"⏸️ [{now_str}] السوق مغلق حالياً ({session_name}).")
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

            # جلب Latest updates المترجم للغة العربية والرابط القابل للنقر المباشر
            latest_updates = fetch_tradingview_latest_updates(symbol, exchange)

            curr_count = counts.get(symbol, 0) + 1
            counts[symbol] = curr_count

            alert_title = "🚨 Alert" if curr_count == 1 else f"🚨 Alert {curr_count}"
            tv_url = f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"

            # جلب تفاصيل SEC وأخبار المحفزات
            split_sched, warrants_info, sec_summary, catalyst_str, cik_code = fetch_sec_filings_and_catalysts(
                symbol, 
                check_split=(price < 1.0),
                change_pct=change_pct
            )

            if cik_code:
                sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={cik_code}"
            else:
                sec_browse_url = f"
