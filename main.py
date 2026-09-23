"""US Top Gainers & Sudden Momentum Tracker.

Monitors TradingView's official Top Gainers for Pre-market, Market, and After-hours.
Alerts on NEW tickers entering Top 20 or SUDDEN spikes in percentage gain.
Includes Sector, Hyperlinked TradingView text, Repeat count, and Real VWAP.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from tradingview_screener import Query, col

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

NY = ZoneInfo("America/New_York")
SEEN_FILE = "seen.json"

# إعدادات الفلترة والشروط المحفوظة
MIN_PRICE = 0.60                # السعر أعلى من 0.60 دولار
MIN_VOL = 30_000                # السيولة والحجم من 30 ألف وأعلى لجميع الجلسات
TOP_LIMIT = 20                 # متابعة أفضل 20 سهم في نادي Top Gainers
SPIKE_THRESHOLD = 2.0          # تسارع الزخم: قفزة بـ 2% أو أكثر عن آخر قراءة محفوظة

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
        return "after"
    return None


def get_top_gainers_query(session):
    """جلب ماسح Top Gainers المباشر لـ TradingView مع القطاع و VWAP."""
    if session == "pre":
        filters = [
            col("premarket_close") > MIN_PRICE, 
            col("premarket_change") > 2.0,
            col("premarket_volume") >= MIN_VOL
        ]
        sort_col = "premarket_change"
        extra = ["premarket_close", "premarket_change", "premarket_volume"]
    elif session == "after":
        filters = [
            col("postmarket_close") > MIN_PRICE, 
            col("postmarket_change") > 2.0,
            col("postmarket_volume") >= MIN_VOL
        ]
        sort_col = "postmarket_change"
        extra = ["postmarket_close", "postmarket_change", "postmarket_volume"]
    else: # market
        filters = [
            col("close") > MIN_PRICE, 
            col("change") > 2.0,
            col("volume") >= MIN_VOL
        ]
        sort_col = "change"
        extra = ["close", "change", "volume"]

    # إضافة "sector" و "VWAP" للقوائم الفنية
    tech_cols = ["high", "low", "EMA21", "EMA50", "average_volume_10d_calc", "sector", "VWAP"]
    columns = list(dict.fromkeys(["name"] + extra + tech_cols))

    query = (
        Query()
        .set_markets("america")
        .select(*columns)
        .where(col("type") == "stock", *filters)
        .order_by(sort_col, ascending=False)
        .limit(100)
    )
    return query, sort_col, extra


def run_screen(session):
    query, sort_col, extra = get_top_gainers_query(session)
    _, df = query.get_scanner_data()
    if df.empty:
        return df
        
    return df.head(TOP_LIMIT)


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


def send(text):
    """إرسال الرسالة مع تفعيل HTML لتنسيق الألوان والروابط."""
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()


def calculate_levels(price, high, low, ema21, ema50):
    pivot = (high + low + price) / 3
    r1 = (2 * pivot) - low if ((2 * pivot) - low) > price else price * 1.025
    r2 = pivot + (high - low) if (pivot + (high - low)) > r1 else r1 * 1.03
    r3 = high + 2 * (pivot - low) if (high + 2 * (pivot - low)) > r2 else r2 * 1.04

    support_intraday = min(low, ema21 if 0 < ema21 < price else low)
    support_ilz = min(ema50 if 0 < ema50 < price else support_intraday * 0.98, pivot)

    return {
        "support_intraday": support_intraday,
        "support_ilz": support_ilz,
        "t1": r1,
        "t2": r2,
        "t3": r3,
        "t_max": r3 * 1.08,
        "stop_1": support_intraday * 0.985,
    }


def main():
    session = current_session()
    if not session:
        print("Outside US sessions, nothing to do.")
        return

    today, state = load_state()
    price_c, chg_c, vol_c = DISPLAY[session]

    try:
        df = run_screen(session)
    except Exception as e:
        print(f"[{session}] error fetching data: {e}")
        sys.exit(1)

    if df.empty:
        print("No Top Gainers found.")
        return

    new_entries = []
    spike_entries = []

    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        ticker = str(row['name']).strip()
        change = float(row[chg_c]) if row[chg_c] else 0.0
        price = float(row[price_c]) if row[price_c] else 0.0

        key = f"{session}:{ticker}"
        last_data = state.get(key)

        if not last_data:
            # أول ظهور للسهم (تكرار 1)
            count = 1
            new_entries.append((rank, row, "دخول جديد إلى Top 20 🚨", count))
        else:
            old_change = last_data["change"]
            count = last_data.get("count", 1)
            # تسارع في الزخم (قفزة بـ 2% أو أكثر)
            if change - old_change >= SPIKE_THRESHOLD:
                count += 1
                spike = change - old_change
                spike_entries.append((rank, row, f"تسارع زخم مفاجئ (+{spike:.1f}% 📈)", count))

        # تحديث الحالة الحالية للسهم مع عداد التكرار
        state[key] = {"change": change, "price": price, "rank": rank, "count": count}

    alerts = new_entries + spike_entries

    if alerts:
        lines = [f"🚨 <b>تحديث الزخم وTop Gainers</b> | {SESSION_AR[session]}\n"]
        for rank, row, status_title, count in alerts:
            ticker = str(row['name']).strip()
            tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            
            price = float(row[price_c]) if row[price_c] else 0.0
            chg = float(row[chg_c]) if row[chg_c] else 0.0
            high = float(row['high']) if 'high' in row and row['high'] else price * 1.02
            low = float(row['low']) if 'low' in row and row['low'] else price * 0.98
            ema21 = float(row['EMA21']) if 'EMA21' in row and row['EMA21'] else price * 0.99
            ema50 = float(row['EMA50']) if 'EMA50' in row and row['EMA50'] else price * 0.97
            
            # جلب القطاع و VWAP الحقيقي
            sector = str(row['sector']) if 'sector' in row and row['sector'] else "غير محدد"
            vwap_val = float(row['VWAP']) if 'VWAP' in row and row['VWAP'] else price

            lvl = calculate_levels(price, high, low, ema21, ema50)

            # نص التكرار باللون الأحمر (استخدام HTML للتمييز)
            repeat_str = f"🔴 <b>[تكرار {count}]</b>"

            lines.append(f"🔥 #{rank} <b>{ticker}</b> — {status_title} {repeat_str}")
            lines.append(f"🏢 القطاع: <b>{sector}</b>")
            lines.append(f"💵 السعر: <b>{price:.2f}$</b> | التغير: <b>{chg:+.1f}%</b> | Vol: {row[vol_c]:,.0f}")
            lines.append(f"📈 الشارت: <a href='{tv_url}'>TradingView</a>")
            lines.append(f"🎯 الأهداف: {lvl['t1']:.2f}$ -&gt; {lvl['t2']:.2f}$ -&gt; {lvl['t3']:.2f}$ (أقصى هدف: {lvl['t_max']:.2f}$)")
            lines.append(f"🛡 الدعم: {lvl['support_intraday']:.2f}$ | ⛔️ الوقف: {lvl['stop_1']:.2f}$ | 📊 VWAP: <b>{vwap_val:.2f}$</b>")
            lines.append("-----------------------------------\n")

        send("\n".join(lines))
        print(f"[{session}] Sent {len(alerts)} alerts.")
    else:
        print(f"[{session}] Top 20 checked, no new entries or sudden spikes.")

    save_state(today, state)


if __name__ == "__main__":
    main()
