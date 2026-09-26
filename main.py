import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from tradingview_screener import Query, col

# إعدادات التلغرام من متغيرات البيئة
TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

RIYADH = ZoneInfo("Asia/Riyadh")
SEEN_FILE = "seen_saudi.json"

MAX_SHOWN = 10  # الحد الأقصى للأسهم المعروضة في الرسالة الواحدة


def get_saudi_stocks_dict():
    """قائمة الأسهم السعودية (222 سهم)"""
    return {
        "2030": "المصافي", "2222": "أرامكو السعودية", "2380": "بترو رابغ", "2381": "الحفر العربية",
        "2382": "اديس", "4030": "البحري", "1201": "تكوين", "1202": "ميكو", "1210": "بي سي آي",
        "1211": "معادن", "1301": "أسلاك", "1304": "اليمامة للحديد", "1320": "أنابيب السعودية",
        "1321": "أنابيب الشرق", "1322": "أماك", "1323": "يو سي آي سي", "1324": "صالح الراشد",
        "2001": "كيمانول", "2010": "سابك", "2020": "سابك للمغذيات الزراعية", "2060": "التصنيع",
        "2090": "جيسكو", "2150": "زجاج", "2170": "اللجين", "2180": "فيبكو", "2200": "أنابيب",
        "2210": "نماء للكيماويات", "2220": "معدنية", "2223": "لوبريف", "2240": "صناعات",
        "2250": "المجموعة السعودية", "2290": "ينساب", "2300": "صناعة الورق", "2310": "سبكيم العالمية",
        "2330": "المتقدمة", "2350": "كيان السعودية", "2360": "الفخارية", "3002": "اسمنت نجران",
        "3003": "اسمنت المدينة", "3004": "اسمنت الشمالية", "3005": "أسمنت أم القرى", "3007": "الواحة",
        "3008": "الكثيري", "3010": "اسمنت العربية", "3020": "أسمنت اليمامة", "3030": "اسمنت السعودية",
        "3040": "اسمنت القصيم", "3050": "اسمنت الجنوب", "3060": "أسمنت ينبع", "3080": "اسمنت الشرقية",
        "3090": "اسمنت تبوك", "3091": "أسمنت الجوف", "3092": "اسمنت الرياض", "4143": "تالكو",
        "1212": "استرا الصناعية", "1214": "شاكر", "1302": "يوان", "1303": "الصناعات الكهربائية",
        "2040": "الخزف السعودي", "2110": "الكابلات السعودية", "2160": "اميانتيت", "2320": "البابطين",
        "2370": "مسك", "4110": "باتك", "4140": "صادرات", "4141": "العمران", "4142": "كابلات الرياض",
        "4144": "رووم", "4145": "او جي سي", "4146": "جاز", "4147": "سي جي اس", "4148": "الوسائل الصناعية",
        "1831": "مهارة", "1832": "صدر", "1833": "الموارد", "1834": "سماسكو", "1835": "تمكين",
        "4270": "طباعة وتغليف", "6004": "كاتريون", "2190": "سيسكو القابضة", "4031": "الأرضية",
        "4040": "سابتكو", "4260": "بدجت السعودية", "4261": "ذيب", "4262": "لومي", "4263": "سال",
        "4264": "طيران ناس", "4265": "شري", "1213": "نسيج", "2130": "صدق", "2340": "ارتيكس",
        "4011": "لازوردي", "4012": "الأاصيل", "1810": "سيرا", "1820": "بان", "1830": "لحام للرياضة",
        "4090": "طيبة", "4170": "شمس", "4250": "جيل عمر", "4290": "الخليج للتدريب", "4291": "الوطنية للتعليم",
        "4292": "عطاء", "6002": "هرفي للأغذية", "6012": "ريدان", "6013": "التطويرية الغذائية",
        "6014": "التمار", "6015": "أمريكانا", "6016": "برغرايززر", "6017": "جاهز", "6018": "الأندية للرياضة",
        "6019": "المسار الشامل", "6022": "أرماح", "4003": "اكسترا", "4008": "ساكو", "4050": "ساسكو",
        "4051": "باعظيم", "4180": "مجموعة فتيحي", "4190": "جرير", "4191": "أبو معطي", "4192": "السيف غاليري",
        "4193": "نايس ون", "4194": "محطة البناء", "4200": "الدريس", "4240": "سينومي ريتيل",
        "4001": "أسواق العثيم", "4006": "اسواق المزرعة", "4061": "انعام القابضة", "4160": "ثمار",
        "4161": "بن داود", "4162": "المنجم", "4163": "الدواء", "4164": "النهدي", "2050": "مجموعة صافولا",
        "2100": "وفرة", "2140": "ايان", "2270": "سدافكو", "2280": "المراعي", "2281": "تنمية",
        "2282": "نقى", "2283": "المطاحن الأولى", "2284": "المطاحن الحديثة", "2285": "المطاحن العربية",
        "2286": "المطاحن الرابعة", "2287": "انتاج", "2288": "نفوذ", "4080": "سناد القابضة",
        "6001": "حلواني اخوان", "6010": "نادك", "6020": "جلكو", "6040": "تبوك الزراعية", "6050": "الأسماك",
        "6060": "الشرقية سمنة", "6070": "الجوف", "6090": "جازادكو", "4165": "الماجد للعود", "2230": "الكيميائية",
        "4002": "المواساة", "4004": "دله الصحية", "4005": "رعاية", "4007": "الحمادي", "4009": "السعودي الألماني الصحية",
        "4013": "سليمان الحبيب", "4014": "دار المعدات", "4017": "فقيه الطبية", "4018": "الموسى",
        "4019": "اس ام علي للرعاية الصحية", "4021": "المركز الكندي الطبي", "2070": "الدوائية",
        "4015": "جمجوم فارما", "4016": "أفالون فارما", "1010": "الرياض", "1020": "الجزيرة", "1030": "الاستثمار",
        "1050": "بي اس اف", "1060": "الأول", "1080": "العربي", "1120": "الراجحي", "1140": "البلاد",
        "1150": "الإنماء", "1180": "الأهلي", "1111": "مجموعة تداول", "1182": "أملاك", "1183": "سهل",
        "2120": "متطورة", "4081": "النايفات", "4082": "مرنة", "4083": "تسهيل", "4084": "دراية",
        "4130": "درب السعودية", "4280": "المملكة", "7200": "ام أي اس", "7201": "بحر العرب", "7202": "سلوشنز",
        "7203": "علم", "7204": "تويي", "7205": "دي بي اس", "7211": "عزم", "7010": "اس تي سي",
        "7020": "اتحاد اتصالات", "7030": "زين السعودية", "7040": "قو للاتصالات", "2080": "الغاز القابضة",
        "2081": "الخريف", "2082": "أكوا", "2083": "مرافق", "2084": "مباهنا", "5110": "السعودية للطاقة",
        "4330": "الرياض ريت", "4331": "الجزيرة ريت", "4332": "جدوى ريت الحرمين", "4333": "تعليم ريت",
        "4334": "المعذر ريت", "4335": "مشاركة ريت", "4337": "العزيزية ريت", "4338": "الأهلي ريت 1",
        "4339": "دراية ريت", "4340": "الراجحي ريت", "4342": "جدوى ريت السعودية", "4344": "سدكو كابيتال ريت",
        "4345": "الإنماء ريت للتجزئة"
    }


def screens():
    """الفلاتر الأصلية بدون تقييد استعلامات البحث"""
    
    # 1. بداية انطلاق (0.5% - 1.5%)
    early_momentum = [
        col("close") > 0,
        col("change") >= 0.5,
        col("change") <= 1.5,
        col("volume") >= 150000,
        col("close") > col("VWAP")
    ]

    # 2. اختراق لحظي وسيولة
    intraday_breakout = [
        col("close") > 0,
        col("change") >= 0.8,
        col("change") <= 3.0,
        col("volume") >= 200000,
        col("close") > col("VWAP"),
        col("close") > col("EMA20")
    ]

    # 3. اختراق و CHOCH أسبوعي
    swing_choch = [
        col("close") > 0,
        col("change") >= 1.0,
        col("volume") >= 200000,
        col("close") > col("EMA20"),
        col("close") > col("high|1W")
    ]

    # 4. فلتر الانعكاس
    reversal_signal = [
        col("close") > 0,
        col("volume") >= 100000,
        col("RSI") <= 30,
        col("SMA10") > col("SMA20"),
        col("SMA10|1") <= col("SMA20|1")
    ]

    extra = ["close", "change", "volume"]
    return extra, "change", {
        "1️⃣ بداية انطلاق (0.5% - 1.5%)": early_momentum,
        "2️⃣ اختراق لحظي وسيولة": intraday_breakout,
        "3️⃣ اختراق و CHOCH أسبوعي": swing_choch,
        "🔄 فلتر الانعكاس (SMA Cross + RSI <= 30)": reversal_signal
    }


def get_power_trend_age(row, tf, max_bars=10):
    """حساب عدد الشموع المتتالية لاستمرار الـ Power Trend (شمعة خضراء وأعلى من EMA20)"""
    count = 0
    for i in range(max_bars):
        suffix = f"|{tf}" if i == 0 else f"|{tf}|{i}"
        c = float(row.get(f"close{suffix}", 0) or 0)
        o = float(row.get(f"open{suffix}", 0) or 0)
        ema = float(row.get(f"EMA20{suffix}", 0) or 0)
        
        if c > 0 and c > o and c > ema:
            count += 1
        else:
            break
    return count


def run_screen(filters, columns, sort_col, tickers_dict):
    symbols = [f"TADAWUL:{t}" for t in tickers_dict.keys()]
    
    query = (
        Query()
        .set_tickers(*symbols)
        .select(*columns)
        .where(*filters)
        .order_by(sort_col, ascending=False)
        .limit(300)
    )
    
    try:
        _, df = query.get_scanner_data()
    except Exception as e:
        print(f"خطأ في الاستعلام من TradingView: {e}")
        df = None

    if df is not None and not df.empty:
        df["clean_name"] = df["name"].astype(str).str.replace("TADAWUL:", "").str.strip()
        return df

    return df


def load_seen():
    today = datetime.now(RIYADH).strftime("%Y-%m-%d")
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            counts = data.get("counts", {})
            return today, counts
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return today, {}


def save_seen(today, counts):
    with open(SEEN_FILE, "w") as f:
        json.dump({
            "date": today,
            "counts": counts
        }, f, indent=2)


def send(text):
    if not TOKEN or not CHAT_ID:
        print("تحذير: BOT_TOKEN أو CHAT_ID غير موجود.")
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
    r.raise_for_status()


def calculate_levels(price, high, low, ema20, ema50):
    pivot = (high + low + price) / 3
    
    r1 = (2 * pivot) - low if ((2 * pivot) - low) > price else price * 1.025
    r2 = pivot + (high - low) if (pivot + (high - low)) > r1 else r1 * 1.03
    r3 = high + 2 * (pivot - low) if (high + 2 * (pivot - low)) > r2 else r2 * 1.04

    support_intraday = min(low, ema20 if 0 < ema20 < price else low)
    support_ilz = min(ema50 if 0 < ema50 < price else support_intraday * 0.98, pivot)

    t1, t2, t3, t4 = r1, r2, r3, r3 * 1.03
    t_max = t4 * 1.05

    stop_1 = support_intraday * 0.985
    stop_2 = support_ilz * 0.975

    return {
        "support_intraday": support_intraday,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "t_max": t_max,
        "stop_1": stop_1,
        "stop_2": stop_2,
    }


def main():
    today, counts = load_seen()
    extra, sort_col, defs = screens()
    stocks_dict = get_saudi_stocks_dict()
    
    # تحضير أعمدة الفريمات الزمنية لحساب عمر الشمعة (10 شموع سابقة لكل فريم)
    tf_cols = []
    for tf in ["240", "15"]:
        for i in range(10):
            suffix = f"|{tf}" if i == 0 else f"|{tf}|{i}"
            tf_cols.extend([f"close{suffix}", f"open{suffix}", f"EMA20{suffix}"])

    tech_cols = [
        "high", "low", "EMA20", "EMA50", "sector", "VWAP", 
        "price_52_week_high", "price_52_week_low",
        "high|1W", "high|2W", "RSI", "SMA10", "SMA20", "SMA10|1", "SMA20|1"
    ] + tf_cols

    columns = list(dict.fromkeys(["name", "close", "volume"] + extra + tech_cols))
    price_c, chg_c, vol_c = "close", "change", "volume"
    had_error = False

    for label, filters in defs.items():
        try:
            df = run_screen(filters, columns, sort_col, stocks_dict)
        except Exception as e:
            print(f"[السوق السعودي/{label}] error: {e}")
            had_error = True
            continue

        if df is None or df.empty:
            print(f"[السوق السعودي/{label}] 0 matches")
            continue

        # تطبيق الفلترة السعرية الدقيقة
        if label == "1️⃣ بداية انطلاق (0.5% - 1.5%)":
            df = df[df["close"] >= df["high"] * 0.985]
        elif label == "2️⃣ اختراق لحظي وسيولة":
            df = df[df["close"] >= df["high"] * 0.99]

        if df.empty:
            print(f"[السوق السعودي/{label}] 0 matches after fine filter")
            continue

        results = []
        for _, row in df.iterrows():
            ticker_name = str(row.get('clean_name', row['name'])).strip()
            results.append((ticker_name, row))

        print(f"[السوق السعودي/{label}] {len(results)} matches")

        lines = [f"🚨 <b>تحديث الزخم والأسهم | {label}</b>\n"]
        
        for idx, (ticker, row) in enumerate(results[:MAX_SHOWN], 1):
            arabic_name = stocks_dict.get(ticker, ticker)
            sector = str(row.get('sector', 'N/A')).strip()
            
            tv_url = f"https://www.tradingview.com/chart/?symbol=TADAWUL:{ticker}"
            
            price = float(row[price_c]) if row[price_c] else 0.0
            change = float(row[chg_c]) if row[chg_c] else 0.0
            volume = float(row[vol_c]) if row[vol_c] else 0.0
            vwap = float(row.get('VWAP', 0.0) or 0.0)
            rsi = float(row.get('RSI', 0.0) or 0.0)
            
            high = float(row['high']) if 'high' in row and row['high'] else price * 1.02
            low = float(row['low']) if 'low' in row and row['low'] else price * 0.98
            ema20 = float(row['EMA20']) if 'EMA20' in row and row['EMA20'] else price * 0.99
            ema50 = float(row['EMA50']) if 'EMA50' in row and row['EMA50'] else price * 0.97

            # حساب عمر شمعة Power Trend لفريم 4H وفريم 15M
            age_4h = get_power_trend_age(row, "240")
            age_15m = get_power_trend_age(row, "15")

            # بيانات أسبوعية واختبار CHOCH
            high_1w = float(row.get('high|1W', 0.0) or 0.0)
            high_2w = float(row.get('high|2W', 0.0) or 0.0)
            has_weekly_choch = (high_1w > 0 and price > high_1w) or (high_2w > 0 and price > high_2w)

            # قمة وقاع 52 أسبوع وحساب النسب
            high52 = float(row.get('price_52_week_high', 0.0) or 0.0)
            low52 = float(row.get('price_52_week_low', 0.0) or 0.0)
            
            dist_high52 = ((price - high52) / high52 * 100) if high52 > 0 else 0.0
            dist_low52 = ((price - low52) / low52 * 100) if low52 > 0 else 0.0

            # إدارة التنبيهات وزيادة العداد
            curr_count = counts.get(ticker, 0) + 1
            counts[ticker] = curr_count

            lvl = calculate_levels(price, high, low, ema20, ema50)

            lines.append(f"🔥 <b>دخول جديد إلى القائمة – #{idx} {arabic_name} ({ticker})</b>")
            lines.append(f"🚨 🛑 <b>[تنبيه {curr_count}]</b>")
            
            # عرض عمر شمعة Power Trend بالتنسيق المطلوب بالظبط
            if age_4h > 0:
                lines.append(f"⚡️ <b>شمعة {age_4h} : Power Trend 4H</b>")
            if age_15m > 0:
                lines.append(f"⚡️ <b>شمعة {age_15m} : Power Trend 15M</b>")

            if rsi > 0:
                lines.append(f"📉 <b>RSI:</b> {rsi:.1f}")
            if has_weekly_choch:
                lines.append("⚡️ <b>[CHOCH أسبوعي إيجابي: كسر القمة الأسبوعية]</b>")
                
            lines.append(f"🏢 <b>القطاع:</b> {sector}")
            lines.append(f"💵 <b>السعر:</b> {price:.2f} ر.س | <b>التغير:</b> +{change:.1f}% | Vol: {int(volume):,}")
            if high52 > 0 and low52 > 0:
                lines.append(f"🏔️ <b>قمة 52 أسبوع:</b> {high52:.2f} ر.س ({dist_high52:.1f}%)")
                lines.append(f"⛰️ <b>قاع 52 أسبوع:</b> {low52:.2f} ر.س (+{dist_low52:.1f}%)")
            lines.append(f"📈 <b>الشارت:</b> <a href='{tv_url}'>TradingView</a>")
            lines.append(f"🎯 <b>الأهداف:</b> {lvl['t1']:.2f} ر.س -&gt; {lvl['t2']:.2f} ر.س -&gt; {lvl['t3']:.2f} ر.س")
            lines.append(f"(أقصى هدف: {lvl['t_max']:.2f} ر.س)")
            lines.append(f"🛡️ <b>الدعم:</b> {lvl['support_intraday']:.2f} ر.س | ⛔️ <b>الوقف:</b> {lvl['stop_1']:.2f} ر.س")
            if vwap > 0:
                lines.append(f"📊 <b>VWAP:</b> {vwap:.2f} ر.س")
            lines.append("-----------------------------------\n")

        if len(results) > MAX_SHOWN:
            lines.append(f"+{len(results) - MAX_SHOWN} أخرى\n")
        lines.append("للفرز فقط، تأكد على الشارت قبل أي قرار.")
        
        send("\n".join(lines))

    save_seen(today, counts)
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
