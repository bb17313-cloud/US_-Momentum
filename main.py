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
            cik_
