"""US Top Gainers & Sudden Momentum Tracker with Sectors in Arabic.

Monitors TradingView's official Top Gainers for Pre-market, Market, and After-hours.
Alerts on NEW tickers entering Top 20 or SUDDEN spikes in percentage gain.
Runs on GitHub Actions every 10 minutes.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from tradingview_screener import Query, col

TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

NY = ZoneInfo("America/New_York")
SEEN_FILE = "seen.json"

# إعدادات الفلترة والشروط لأسهم الزخم (Momentum)
MIN_PRICE = 0.70                # أدنى سعر للسهم
TOP_LIMIT = 20                 # متابعة أفضل 20 سهم
SPIKE_THRESHOLD = 3.0          # قفزة زخم إضافية بـ 3% أو أكثر

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

# قاموس ترجمة القطاعات للغة العربية
SECTORS_AR = {
    "Technology": "التكنولوجيا 💻",
    "Health Technology": "التكنولوجيا الصحية 🏥",
    "Health Services": "الخدمات الصحية ⚕️",
    "Electronic Technology": "الإلكترونيات والتقنية 🔬",
    "Finance": "الخدمات المالية 🏦",
    "Commercial Services": "الخدمات التجارية 💼",
    "Consumer Durables": "السلع المعمرة 🚗",
    "Consumer Non-Durables": "السلع الاستهلاكية 🛒",
    "Consumer Services": "الخدمات الاستهلاكية 🛍️",
    "Energy Minerals": "الطاقة والمعدن ⛽",
    "Non-Energy Minerals": "التعدين والمواد ⛏️",
    "Process Industries": "الصناعات التحويلية 🏭",
    "Producer Manufacturing": "التصنيع الإنتاجي 🏗️",
    "Industrial Services": "الخدمات الصناعية 🛠️",
    "Utilities": "المرافق العامة 💡",
    "Communications": "الاتصالات والإنترنت 📡",
    "Transportation": "النقل اللوجستي 🚚",
    "Distribution Services": "التوزيع واللوجستيات 📦",
    "Retail Trade": "تجارة التجزئة 🏬",
    "Miscellaneous": "متنوع 🌐"
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
    """جلب ماسح Top Gainers المباشر لـ TradingView حسب الجلسة."""
    if session == "pre":
        filters = [col("premarket_close") >= MIN_PRICE, col("premarket_change") > 2.0]
        sort_col = "premarket_change"
        extra = ["premarket_close", "premarket_change", "premarket_volume", "premarket_high", "premarket_low"]
    elif session == "after":
        filters = [col("postmarket_close") >= MIN_PRICE, col("postmarket_change") > 2.0]
        sort_col = "postmarket_change"
        extra = ["postmarket_close", "postmarket_change", "postmarket_volume", "high", "low"]
    else: # market
        filters = [col("close") >= MIN_PRICE, col("change") > 2.0]
        sort_col = "change"
        extra = ["close", "change", "volume", "high", "low"]

    tech_cols = ["sector", "EMA21", "EMA50"]
    columns = list(dict.fromkeys(["name"] + extra + tech_cols))

    query = (
        Query()
        .set_markets("america")
        .select(*columns)
        .where(col("type") == "stock", *filters)
        .order_by(sort_col, ascending=False)
        .limit(TOP_LIMIT)
    )
    return query, sort_col, extra


def run_screen(session):
    query, _, _ = get_top_gainers_query(session)
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


def send(text):
    if not TOKEN or not CHAT_ID:
        print("BOT_TOKEN or CHAT_ID missing!")
        return
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
    if not r.ok:
        print(f"Telegram Response: {r.text}")
    r.raise_for_status()


def calculate_levels(price, high, low, ema21=None):
    pivot = (high + low + price) / 3 if (high > 0 and low > 0) else price
    
    r1 = (2 * pivot) - low if (low > 0 and (2 * pivot - low) > price) else price * 1.03
    r2 = pivot + (high - low) if (high > low and (pivot + high - low) > r1) else r1 * 1.04
    r3 = r2 * 1.05

    if ema21 and 0 < ema21 < price:
        support_intraday = max(low, ema21)
    else:
        support_intraday = low if low > 0 else price * 0.96

    return {
        "support_intraday": support_intraday,
        "t1": r1,
        "t2": r2,
        "t3": r3,
        "t_max": r3 * 1.08,
        "stop_1": support_intraday * 0.98,
    }


def safe_float(val, default=0.0):
    try:
        if pd.isna(val) or val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def main():
    session = current_session()
    if not session:
        print("Outside US sessions, nothing to do.")
        return

    print(f"Running session: {session}")
    today, state = load_state()
    price_c, chg_c, vol_c = DISPLAY[session]

    try:
        df = run_screen(session)
    except Exception as e:
        print(f"[{session}] error fetching data: {e}")
        sys.exit(1)

    if df is None or df.empty:
        print(f"[{session}] No Top Gainers found.")
        return

    new_entries = []
    spike_entries = []

    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        ticker = str(row['name']).strip()
        change = safe_float(row.get(chg_c))
        price = safe_float(row.get(price_c))

        if price <= 0:
            continue

        key = f"{session}:{ticker}"
        last_data = state.get(key)

        if not last_data:
            new_entries.append((rank, row, "دخول جديد إلى Top 20 🚨", 0.0))
        else:
            old_change = last_data["change"]
            if change - old_change >= SPIKE_THRESHOLD:
                spike = change - old_change
                spike_entries.append((rank, row, f"تسارع زخم مفاجئ (+{spike:.1f}% 📈)", old_change))

        state[key] = {"change": change, "price": price, "rank": rank}

    alerts = new_entries + spike_entries

    if alerts:
        header = f"🚨 <b>تحديث أسهم الزخم Momentum</b> | {SESSION_AR[session]}\n\n"
        current_chunk = header

        for rank, row, status_title, _ in alerts:
            ticker = str(row['name']).strip()
            tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            
            raw_sector = str(row.get('sector', '')).strip()
            sector_ar = SECTORS_AR.get(raw_sector, raw_sector if raw_sector else "غير محدد 🌐")
            
            price = safe_float(row.get(price_c))
            chg = safe_float(row.get(chg_c))
            vol = safe_float(row.get(vol_c))
            
            high_key = "premarket_high" if session == "pre" else "high"
            low_key = "premarket_low" if session == "pre" else "low"
            
            high = safe_float(row.get(high_key), price * 1.02)
            low = safe_float(row.get(low_key), price * 0.98)
            ema21 = safe_float(row.get('EMA21'), 0.0)

            lvl = calculate_levels(price, high, low, ema21)

            item_text = (
                f"🔥 #{rank} <b>{ticker}</b> — {status_title}\n"
                f"🏢 القطاع: <b>{sector_ar}</b>\n"
                f"💵 السعر: <b>{price:.2f}$</b> | التغير: <b>{chg:+.1f}%</b> | Vol: {vol:,.0f}\n"
                f'📈 الشارت: <a href="{tv_url}">TradingView</a>\n'
                f"🎯 الأهداف: {lvl['t1']:.2f}$ -> {lvl['t2']:.2f}$ -> {lvl['t3']:.2f}$ (أقصى: {lvl['t_max']:.2f}$)\n"
                f"🛡 الدعم: {lvl['support_intraday']:.2f}$ | ⛔️ الوقف: {lvl['stop_1']:.2f}$\n"
                "-----------------------------------\n\n"
            )

            # إذا كانت إضافة التنبيه الجديد ستتجاوز 3500 حرف، قم بإرسال الدفعة الحالية وافتح دفعة جديدة
            if len(current_chunk) + len(item_text) > 3500:
                send(current_chunk)
                current_chunk = header + item_text
            else:
                current_chunk += item_text

        if current_chunk.strip():
            send(current_chunk)

        print(f"[{session}] Sent {len(alerts)} alerts.")
    else:
        print(f"[{session}] Top 20 checked, no new entries or sudden spikes.")

    save_state(today, state)


if __name__ == "__main__":
    main()
