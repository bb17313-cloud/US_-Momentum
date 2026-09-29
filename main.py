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
MAX_SHOWN = 20  # 👈 تم التعديل ليصبح 20 بدلاً من 10

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
# جلب بيانات الأسهم (TradingView API)
# ================================
def fetch_filtered_stocks(session_type):
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }

    # تحديد أسماء الحقول بحسب الجلسة الحالية لضمان جلب السعر المباشر الصحيح
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

    # الفلاتر الأساسية لجميع الجلسات
    filters = [
        {"left": "float_shares_outstanding_current", "operation": "less", "right": 500_000_000}, # 👈 تم التعديل إلى أقل من 500M
        {"left": volume_field, "operation": "greater", "right": 30_000},
        {"left": change_field, "operation": "greater", "right": 2.0},
        {"left": "average_volume_10d_calc", "operation": "greater", "right": 100_000},
        {"left": "close", "operation": "less", "right": 50.0},
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]}
    ]

    # فلاتر إضافية خاصة بالسوق الرئيسي
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
    """تقسيم الرسالة إلى أجزاء لتفادي تجاوز حد تليجرام (4096 حرفاً)"""
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
            # جلب سعر الجلسة الحالية، وإن لم يتوفر يُستخدم سعر الإغلاق d[9]
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
                f"<b>Vol:</b> {format_number(volume)}",
                f"<b>الشارت TradingView:</b> <a href='{tv_url}'>فتح الشارت</a>",
                "-----------------------------------"
            ]
            blocks.append("\n".join(lines))

        save_seen(today, counts)
        send_in_chunks(header, blocks)
        print(f"✅ تم إرسال {len(blocks)} سهم بنجاح.")
    else:
        print(f"ℹ️️ [{now_str}] لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    main()
