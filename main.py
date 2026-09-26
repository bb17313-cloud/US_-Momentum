"""US Top Gainers & Sudden Momentum Tracker + Low Float Pre-Breakout Scanner.

Monitors:
1. TradingView's Top Gainers (Pre-market, Market, After-hours).
2. Low Float Pre-Breakout Stocks:
   - Float <= 20M
   - Daily Change: +2% to +8%
   - Total Volume >= 40,000
   - Sudden Spike: 1-min >= 1.5% OR 5-min >= 1.5%
   - 1-min Volume >= 4x (10-min average)
Excludes OTC / Pink Sheets stocks completely.
"""

import html
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from tradingview_screener import Query, col

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

NY = ZoneInfo("America/New_York")
SEEN_FILE = "seen.json"

# ذاكرة عامة في الرام لضمان عدم استعادة الذاكرة الفارغة
GLOBAL_STATE = {}
GLOBAL_DATE = None

# ذاكرة لحفظ حجوم التداول للدقائق الأخيرة للماسح الثاني (حساب متوسط 10 دقائق)
MINUTE_VOL_HISTORY = defaultdict(list)

# ---------------------------------------------------------
# إعدادات الفلترة والشروط العامة للماسح الأول (Top Gainers)
# ---------------------------------------------------------
MIN_PRICE = 0.55                # السعر الأدنى: 0.55 دولار
MAX_PRICE = 50.00               # السعر الأعلى: 50.00 دولار
MIN_VOL = 70_000                # السيولة والحجم الأدنى للماسح الأول
SCAN_LIMIT = 100                # البحث في قائمة أفضل 100 سهم
SPIKE_THRESHOLD = 2.0          # تسارع الزخم: قفزة بـ 2% أو أكثر

# ---------------------------------------------------------
# إعدادات الفلترة للماسح الثاني (Low Float Pre-Breakout)
# ---------------------------------------------------------
MAX_FLOAT = 20_000_000          # أسهم الفلوت أقل من أو يساوي 20 مليون
PRE_MIN_CHANGE = 2.0            # التغير اليومي الأدنى +2%
PRE_MAX_CHANGE = 8.0            # التغير اليومي الأقصى +8%
PRE_MIN_VOL = 40_000            # الحجم الإجمالي الأدنى للماسح الثاني (40 ألف سهم)
SPIKE_MIN = 1.5                 # قفزة الزخم الأدنى: 1.5% (على شمعة الدقيقة أو 5 دقائق)
VOL_MULT_THRESHOLD = 4.0        # حجم الدقيقة >= 4 أضعاف متوسط 10 دقائق

# البورصات الرسمية المسموح بها فقط
VALID_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]

SESSION_AR = {
    "pre": "قبل الافتتاح (Pre-Market)", 
    "market": "الجلسة الرئيسية (Market)", 
    "after": "بعد الإغلاق (After-Hours)"
}

DISPLAY = {
    "pre": ("premarket_close", "premarket_change", "premarket_volume"),
    "market": ("close", "change", "volume"),
    "after": ("postmarket_close", "postmarket_change", "postmarket_volume"),
}


def current_session():
    forced = os.environ.get("FORCE_SESSION", "").strip()
    if forced in DISPLAY:
        return forced
    now = datetime.now(NY)
    if now.weekday() >= 5:
        return None
    minutes = now.hour * 60 + now.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "market"
    if 16 * 60 <= minutes < 20 * 60:
        return "after"
    return None


def safe_float(val, default=0.0):
    try:
        if val is None or str(val).lower() == 'nan':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


# =========================================================
# الاستعلامات للماسح الأول (Top Gainers)
# =========================================================
def get_top_gainers_query(session):
    exchange_filter = col("exchange").isin(VALID_EXCHANGES)

    if session == "pre":
        filters = [
            col("premarket_close") >= MIN_PRICE,
            col("premarket_close") <= MAX_PRICE,
            col("premarket_change") > 0.0,
            col("premarket_volume") >= MIN_VOL,
            exchange_filter
        ]
        sort_col = "premarket_change"
        extra = ["premarket_close", "premarket_change", "premarket_volume"]
    elif session == "after":
        filters = [
            col("postmarket_close") >= MIN_PRICE,
            col("postmarket_close") <= MAX_PRICE,
            col("postmarket_change") > 0.0,
            col("postmarket_volume") >= MIN_VOL,
            exchange_filter
        ]
        sort_col = "postmarket_change"
        extra = ["postmarket_close", "postmarket_change", "postmarket_volume"]
    else:  # market
        filters = [
            col("close") >= MIN_PRICE,
            col("close") <= MAX_PRICE,
            col("change") > 0.0,
            col("volume") >= MIN_VOL,
            exchange_filter
        ]
        sort_col = "change"
        extra = ["close", "change", "volume"]

    tech_cols = [
        "high", "low", "EMA21", "EMA50", "average_volume_10d_calc", 
        "sector", "VWAP", "change|240", "change|15",
        "price_52_week_high", "price_52_week_low"
    ]
    columns = list(dict.fromkeys(["name"] + extra + tech_cols))

    query = (
        Query()
        .set_markets("america")
        .select(*columns)
        .where(col("type") == "stock", *filters)
        .order_by(sort_col, ascending=False)
        .limit(SCAN_LIMIT)
    )
    return query, sort_col, extra


# =========================================================
# الاستعلام للماسح الثاني (Low Float Pre-Breakout)
# =========================================================
def get_low_float_prebreakout_query(session):
    exchange_filter = col("exchange").isin(VALID_EXCHANGES)
    price_c, chg_c, vol_c = DISPLAY[session]

    filters = [
        col(price_c) >= MIN_PRICE,
        col(price_c) <= MAX_PRICE,
        col(chg_c) >= PRE_MIN_CHANGE,
        col(chg_c) <= PRE_MAX_CHANGE,
        col("float_shares_outstanding") <= MAX_FLOAT,
        col(vol_c) >= PRE_MIN_VOL,             # 40,000 سهم
        exchange_filter
    ]

    tech_cols = [
        "high", "low", "EMA21", "EMA50", "average_volume_10d_calc", 
        "sector", "VWAP", "change|1", "change|5", "volume|1", "float_shares_outstanding",
        "price_52_week_high", "price_52_week_low"
    ]
    columns = list(dict.fromkeys(["name", price_c, chg_c, vol_c] + tech_cols))

    query = (
        Query()
        .set_markets("america")
        .select(*columns)
        .where(col("type") == "stock", *filters)
        .order_by(chg_c, ascending=False)
        .limit(50)
    )
    return query


def load_state():
    today = datetime.now(NY).strftime("%Y-%m-%d")
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return today, data.get("state", {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return today, {}


def save_state(today, state):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump({"date": today, "state": state}, f)
    except Exception as e:
        print(f"Error saving state: {e}")


def send_single_message(text):
    if not text.strip():
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not r.ok:
        print(f"Telegram API Error: {r.status_code} - {r.text}")
    r.raise_for_status()


def send_alerts_in_batches(header, alert_blocks):
    current_message = header + "\n\n"
    
    for block in alert_blocks:
        if len(current_message) + len(block) > 3000:
            send_single_message(current_message)
            current_message = header + " (تابع)\n\n" + block + "\n-----------------------------------\n"
        else:
            current_message += block + "\n-----------------------------------\n"
            
    if current_message.strip():
        send_single_message(current_message)


def calculate_levels(price, high, low, ema21, ema50):
    pivot = (high + low + price) / 3
    r1 = (2 * pivot) - low if ((2 * pivot) - low) > price else price * 1.025
    r2 = pivot + (high - low) if (pivot + (high - low)) > r1 else r1 * 1.03
    r3 = high + 2 * (pivot - low) if (high + 2 * (pivot - low)) > r2 else r2 * 1.04
    r_max = r3 * 1.08
    r_possible = r3 * 1.15

    return {
        "t1": r1, "t2": r2, "t3": r3, "t_max": r_max, "t_possible": r_possible,
    }


# =========================================================
# تنفيذ الماسح الأول: Top Gainers & Momentum Spikes
# =========================================================
def check_top_gainers(session, today):
    global GLOBAL_STATE
    price_c, chg_c, vol_c = DISPLAY[session]

    try:
        query, _, _ = get_top_gainers_query(session)
        _, df = query.get_scanner_data()
    except Exception as e:
        print(f"[{session}] [Top Gainers] Error fetching data: {e}")
        return

    if df is None or df.empty:
        return

    state = GLOBAL_STATE
    new_entries = []
    spike_entries = []

    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        ticker = str(row['name']).strip().upper()
        change = safe_float(row[chg_c])
        price = safe_float(row[price_c])
        key = ticker

        if key not in state:
            count = 1
            state[key] = {
                "count": count,
                "last_alert_change": change,
                "min_change": change,
                "last_session": session,
                "price": price,
                "rank": rank
            }
            new_entries.append((rank, row, "جديد في القائمة 🚨", count))
        else:
            item = state[key]
            prev_count = item.get("count", 1)
            last_alert_change = item.get("last_alert_change", change)
            min_change = item.get("min_change", last_alert_change)
            last_session = item.get("last_session", session)

            diff_from_last = change - last_alert_change
            diff_from_min = change - min_change

            is_spike = (diff_from_last >= SPIKE_THRESHOLD) or (diff_from_min >= SPIKE_THRESHOLD)
            is_session_change = (session != last_session)

            if is_spike or is_session_change:
                new_count = prev_count + 1
                status_title = f"تسارع زخم مفاجئ (+{max(diff_from_last, diff_from_min):.1f}% 📈)" if is_spike else f"تجدد الزخم في {SESSION_AR[session]} 🚨"

                state[key] = {
                    "count": new_count,
                    "last_alert_change": change,
                    "min_change": change,
                    "last_session": session,
                    "price": price,
                    "rank": rank
                }
                spike_entries.append((rank, row, status_title, new_count))
            else:
                item["min_change"] = min(min_change, change)
                item["price"] = price
                item["rank"] = rank
                state[key] = item

    GLOBAL_STATE = state
    alerts = new_entries + spike_entries

    if alerts:
        header = f"🚨 <b>تحديث الزخم وTop Gainers</b> | {SESSION_AR[session]}"
        alert_blocks = []

        for rank, row, status_title, count in alerts:
            ticker = html.escape(str(row['name']).strip())
            tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            
            price = safe_float(row[price_c])
            chg = safe_float(row[chg_c])
            high = safe_float(row.get('high'), price * 1.02)
            low = safe_float(row.get('low'), price * 0.98)
            ema21 = safe_float(row.get('EMA21'), price * 0.99)
            ema50 = safe_float(row.get('EMA50'), price * 0.97)
            
            sector_raw = str(row.get('sector', 'غير محدد'))
            sector = "غير محدد" if sector_raw.lower() == 'nan' or not sector_raw else html.escape(sector_raw)
                
            vwap_val = safe_float(row.get('VWAP'), price)
            vol_val = safe_float(row.get(vol_c))

            h52 = safe_float(row.get('price_52_week_high'), price)
            l52 = safe_float(row.get('price_52_week_low'), price)
            h52_diff = ((price - h52) / h52 * 100) if h52 > 0 else 0.0
            l52_diff = ((price - l52) / l52 * 100) if l52 > 0 else 0.0

            chg_4h = safe_float(row.get('change|240'), abs(chg))
            chg_15m = safe_float(row.get('change|15'), abs(chg) / 3)
            pt_4h_count = max(1, int(chg_4h / 2.0))
            pt_4h_alert = " ( ⚠️اتجاه متقدم)" if pt_4h_count > 4 else ""
            pt_15m_count = max(1, int(chg_15m / 0.8)) if chg_15m > 0 else 1

            lvl = calculate_levels(price, high, low, ema21, ema50)

            block_lines = [
                f"🔥 #{rank} <b>{ticker}</b> — {status_title} 🔴 <b>[تكرار {count}]</b>",
                f"🏢 القطاع: <b>{sector}</b>",
                f"💵 السعر: <b>${price:.2f}</b> | التغير: <b>{chg:+.1f}%</b> | Vol: {vol_val:,.0f}",
                f"📈 الشارت: <a href='{tv_url}'>TradingView</a>",
                f"• Power Trend 4H: <b>{pt_4h_count} شمعة ⚡</b>{pt_4h_alert}",
                f"• Power Trend 15M: <b>{pt_15m_count} شمعة ⚡</b>",
                f"• قمة 52 أسبوع: <b>${h52:.2f}</b> ({h52_diff:+.1f}%)",
                f"• قاع 52 أسبوع: <b>${l52:.2f}</b> ({l52_diff:+.1f}%)",
                f"🎯 احتمالية TP (${lvl['t1']:.2f}) (${lvl['t2']:.2f}) (${lvl['t3']:.2f}) (${lvl['t_max']:.2f}) ممكن(${lvl['t_possible']:.2f})",
                f"📊 VWAP: <b>${vwap_val:.2f}</b>",
                f"<i>(هذا تنبيه ليس توصيه المرجع في الدخول ماتراه على الشارت)</i>",
                f"<i>(البوت يرسل أسهم ليست شرعيه انتبه مسؤليتك)</i>"
            ]
            alert_blocks.append("\n".join(block_lines))

        send_alerts_in_batches(header, alert_blocks)


# =========================================================
# تنفيذ الماسح الثاني: Low Float Pre-Breakout Hunter
# =========================================================
def check_low_float_prebreakout(session, today):
    price_c, chg_c, vol_c = DISPLAY[session]

    try:
        query = get_low_float_prebreakout_query(session)
        _, df = query.get_scanner_data()
    except Exception as e:
        print(f"[{session}] [Low Float Scanner] Error fetching data: {e}")
        return

    if df is None or df.empty:
        return

    alert_blocks = []

    for _, row in df.iterrows():
        ticker = str(row['name']).strip().upper()
        chg_1m = safe_float(row.get('change|1'))
        chg_5m = safe_float(row.get('change|5'))

        # تحقق شرط (1.5% أو أكثر في آخر دقيقة OR 1.5% أو أكثر في شمعة الـ 5 دقائق)
        if chg_1m < SPIKE_MIN and chg_5m < SPIKE_MIN:
            continue

        vol_1m = safe_float(row.get('volume|1'), 0)
        
        # حفظ تاريخ حجم الدقيقة للحساب التراكمي
        MINUTE_VOL_HISTORY[ticker].append(vol_1m)
        if len(MINUTE_VOL_HISTORY[ticker]) > 10:
            MINUTE_VOL_HISTORY[ticker].pop(0)

        # حساب متوسط حجم تداول الدقيقة
        history = MINUTE_VOL_HISTORY[ticker]
        if len(history) >= 2:
            avg_10m_vol = sum(history[:-1]) / len(history[:-1])
        else:
            avg_10d_vol = safe_float(row.get('average_volume_10d_calc'), 100_000)
            avg_10m_vol = avg_10d_vol / 390.0

        # شرط الانفجار في الحجم (>= 4 أضعاف متوسط آخر 10 دقائق)
        if avg_10m_vol > 0 and (vol_1m / avg_10m_vol) >= VOL_MULT_THRESHOLD:
            vol_ratio = vol_1m / avg_10m_vol
            price = safe_float(row[price_c])
            chg = safe_float(row[chg_c])
            float_shares = safe_float(row.get('float_shares_outstanding')) / 1_000_000
            sector_raw = str(row.get('sector', 'غير محدد'))
            sector = "غير محدد" if sector_raw.lower() == 'nan' or not sector_raw else html.escape(sector_raw)
            tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"

            # توضيح الفريم الذي حدثت عليه القفزة
            spike_info = []
            if chg_1m >= SPIKE_MIN:
                spike_info.append(f"دقيقة: +{chg_1m:.2f}%")
            if chg_5m >= SPIKE_MIN:
                spike_info.append(f"5 دقائق: +{chg_5m:.2f}%")
            spike_str = " | ".join(spike_info)

            # قالب التنبيه المحدث للماسح الثاني
            block_lines = [
                f"💣 | <b>Low Float Spike</b> — <b>{ticker}</b>",
                f"🏢 القطاع: <b>{sector}</b> | 🎈 الفلوت: <b>{float_shares:.2f}M سهم</b>",
                f"💵 السعر: <b>${price:.2f}</b> | التغير اليومي: <b>{chg:+.1f}%</b> (في القاع)",
                f"⚡ <b>قفزة الزخم: {spike_str} 🚀</b>",
                f"📊 <b>حجم الدقيقة: {vol_1m:,.0f} سهم ({vol_ratio:.1f}x ضعف المتوسط) 🔥</b>",
                f"📈 الشارت: <a href='{tv_url}'>TradingView</a>"
            ]
            alert_blocks.append("\n".join(block_lines))

    if alert_blocks:
        header = f"🎯 <b>سهم فلوت  منخفض (Low Float)</b> | {SESSION_AR[session]}"
        send_alerts_in_batches(header, alert_blocks)


def check_and_alert():
    global GLOBAL_STATE, GLOBAL_DATE

    session = current_session()
    if not session:
        print("Outside US sessions, skipping check.")
        return

    today = datetime.now(NY).strftime("%Y-%m-%d")

    if GLOBAL_DATE != today:
        GLOBAL_DATE = today
        file_date, loaded_state = load_state()
        GLOBAL_STATE = loaded_state if file_date == today else {}
        MINUTE_VOL_HISTORY.clear()

    # تشغيل الماسحين متتاليين
    check_top_gainers(session, today)
    check_low_float_prebreakout(session, today)

    save_state(today, GLOBAL_STATE)


def main():
    print("Starting tracker (Top Gainers + Low Float Pre-Breakout Scanner)...")
    while True:
        try:
            check_and_alert()
        except Exception as e:
            print(f"Error during check: {e}")
        time.sleep(180)  # الفحص كل 3 دقائق


if __name__ == "__main__":
    main()
