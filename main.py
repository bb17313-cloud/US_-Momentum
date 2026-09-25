"""US Top Gainers & Sudden Momentum Tracker.

Monitors TradingView's official Top Gainers for Pre-market, Market, and After-hours.
Alerts on NEW tickers or SUDDEN spikes in percentage gain across Top 100.
Includes Sector, Hyperlinked TradingView text, Repeat count, Real VWAP, Power Trends, and 52-Week Range.
Excludes OTC / Pink Sheets stocks completely and enforces strict minimum volume (70k).
"""

import html
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from tradingview_screener import Query, col

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

NY = ZoneInfo("America/New_York")
SEEN_FILE = "seen.json"

# إعدادات الفلترة والشروط الصارمة
MIN_PRICE = 0.60                # السعر أعلى من 0.60 دولار
MIN_VOL = 70_000                # السيولة والحجم الأدنى الصارم (70 ألف وأعلى لجميع الجلسات)
SCAN_LIMIT = 100                # البحث والمسح في قائمة أفضل 100 سهم
SPIKE_THRESHOLD = 2.0          # تسارع الزخم: قفزة بـ 2% أو أكثر عن آخر قراءة محفوظة

# البورصات الرسمية المسموح بها فقط (استبعاد تام لأسهم OTC / OCPK)
VALID_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]

SESSION_AR = {
    "pre": "قبل الافتتاح (Pre-Market)", 
    "market": "الجلسة النظامية (Market)", 
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


def get_top_gainers_query(session):
    exchange_filter = col("exchange").isin(VALID_EXCHANGES)

    if session == "pre":
        filters = [
            col("premarket_close") > MIN_PRICE, 
            col("premarket_change") > 0.0,
            col("premarket_volume") >= MIN_VOL,
            exchange_filter
        ]
        sort_col = "premarket_change"
        extra = ["premarket_close", "premarket_change", "premarket_volume"]
    elif session == "after":
        filters = [
            col("postmarket_close") > MIN_PRICE, 
            col("postmarket_change") > 0.0,
            col("postmarket_volume") >= MIN_VOL,
            exchange_filter
        ]
        sort_col = "postmarket_change"
        extra = ["postmarket_close", "postmarket_change", "postmarket_volume"]
    else:  # market
        filters = [
            col("close") > MIN_PRICE, 
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


def run_screen(session):
    query, sort_col, extra = get_top_gainers_query(session)
    _, df = query.get_scanner_data()
    return df


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
    with open(SEEN_FILE, "w") as f:
        json.dump({"date": today, "state": state}, f)


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
        "t1": r1,
        "t2": r2,
        "t3": r3,
        "t_max": r_max,
        "t_possible": r_possible,
    }


def safe_float(val, default=0.0):
    try:
        if val is None or str(val).lower() == 'nan':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def check_and_alert():
    session = current_session()
    if not session:
        print("Outside US sessions, skipping check.")
        return

    today, state = load_state()
    price_c, chg_c, vol_c = DISPLAY[session]

    try:
        df = run_screen(session)
    except Exception as e:
        print(f"[{session}] Error fetching data: {e}")
        return

    if df is None or df.empty:
        print(f"[{session}] No Top Gainers found.")
        return

    print(f"[{datetime.now(NY).strftime('%H:%M:%S')}] [{session}] Fetched {len(df)} non-OTC high-volume rows.")

    new_entries = []
    spike_entries = []

    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        ticker = str(row['name']).strip()
        change = safe_float(row[chg_c])
        price = safe_float(row[price_c])

        key = f"{session}:{ticker}"
        last_data = state.get(key)

        if not last_data:
            count = 1
            new_entries.append((rank, row, "جديد في القائمة 🚨", count))
            state[key] = {"change": change, "price": price, "rank": rank, "count": count}
        else:
            old_change = last_data["change"]
            count = last_data.get("count", 1)
            if change - old_change >= SPIKE_THRESHOLD:
                count += 1
                spike = change - old_change
                spike_entries.append((rank, row, f"تسارع زخم مفاجئ (+{spike:.1f}% 📈)", count))
                state[key] = {"change": change, "price": price, "rank": rank, "count": count}

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
            if sector_raw.lower() == 'nan' or not sector_raw:
                sector = "غير محدد"
            else:
                sector = html.escape(sector_raw)
                
            vwap_val = safe_float(row.get('VWAP'), price)
            vol_val = safe_float(row.get(vol_c))

            # حساب قمة وقاع 52 أسبوع والنسب المئوية
            h52 = safe_float(row.get('price_52_week_high'), price)
            l52 = safe_float(row.get('price_52_week_low'), price)
            
            h52_diff = ((price - h52) / h52 * 100) if h52 > 0 else 0.0
            l52_diff = ((price - l52) / l52 * 100) if l52 > 0 else 0.0

            # حساب مؤشرات الاتجاه
            chg_4h = safe_float(row.get('change|240'), abs(chg))
            chg_15m = safe_float(row.get('change|15'), abs(chg) / 3)

            pt_4h_count = max(1, int(chg_4h / 2.0))
            pt_4h_alert = " ( ⚠️اتجاه متقدم)" if pt_4h_count > 4 else ""

            pt_15m_count = max(1, int(chg_15m / 0.8)) if chg_15m > 0 else 1

            lvl = calculate_levels(price, high, low, ema21, ema50)

            repeat_str = f"🔴 <b>[تكرار {count}]</b>"

            block_lines = [
                f"🔥 #{rank} <b>{ticker}</b> — {status_title} {repeat_str}",
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
        print(f"[{session}] Sent {len(alerts)} alerts safely.")
    else:
        print(f"[{session}] Checked Top {SCAN_LIMIT}, no new entries or sudden spikes.")

    save_state(today, state)


def main():
    print("Starting tracker... Loop interval set to every 3 minutes.")
    while True:
        try:
            check_and_alert()
        except Exception as e:
            print(f"Error during check: {e}")
        time.sleep(180)  # الانتظار 3 دقائق (180 ثانية)


if __name__ == "__main__":
    main()
