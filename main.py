# ================================
# جلب الأسهم من TradingView API (معدّل)
# ================================
def fetch_filtered_stocks(session_type):
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }

    # نطلب كل الحقول المهمة دائماً لتجنب مشاكل None والـ fallback
    columns = [
        "name",                          # 0
        "description",                   # 1
        "close",                         # 2  ← السعر الحالي (السوق العادي)
        "change",                        # 3  ← نسبة التغيير اليومية %
        "change_abs",                    # 4  ← التغيير المطلق
        "volume",                        # 5
        "premarket_close",               # 6
        "premarket_change",              # 7
        "premarket_change_abs",          # 8
        "premarket_volume",              # 9
        "postmarket_close",              # 10
        "postmarket_change",             # 11
        "postmarket_change_abs",         # 12
        "postmarket_volume",             # 13
        "sector",                        # 14
        "industry",                      # 15
        "country",                       # 16
        "exchange",                      # 17
        "average_volume_10d_calc",       # 18
        "relative_volume_10d_calc",      # 19
        "float_shares_outstanding_current"  # 20
    ]

    # الفلاتر الأساسية
    filters = [
        {"left": "float_shares_outstanding_current", "operation": "less", "right": 500_000_000},
        {"left": "close", "operation": "less", "right": 50.0},
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]}
    ]

    # فلتر الحجم والنسبة حسب الجلسة
    if session_type == "premarket":
        filters.append({"left": "premarket_volume", "operation": "greater", "right": 15_000})
        filters.append({"left": "premarket_change", "operation": "greater", "right": 2.0})
    elif session_type == "postmarket":
        filters.append({"left": "postmarket_volume", "operation": "greater", "right": 15_000})
        filters.append({"left": "postmarket_change", "operation": "greater", "right": 2.0})
    else:  # market
        filters.append({"left": "volume", "operation": "greater", "right": 30_000})
        filters.append({"left": "change", "operation": "greater", "right": 2.0})
        filters.append({"left": "average_volume_10d_calc", "operation": "greater", "right": 50_000})
        filters.append({"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.2})

    # ترتيب حسب نسبة التغيير المناسبة
    sort_by = "change"
    if session_type == "premarket":
        sort_by = "premarket_change"
    elif session_type == "postmarket":
        sort_by = "postmarket_change"

    payload = {
        "filter": filters,
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": {"sortBy": sort_by, "sortOrder": "desc"},
        "range": [0, MAX_SHOWN]
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json().get("data", [])
        return data
    except Exception as e:
        print(f"❌ خطأ أثناء جلب البيانات: {e}")
        return []


# ================================
# داخل الدالة main() - استبدل الجزء الخاص بمعالجة كل سهم
# ================================
# ... (بعد for item in stocks:)

            d = item.get("d", [])
            if len(d) < 18:  # نتأكد من وجود الحقول الأساسية
                continue

            symbol = escape_html(d[0])
            
            # استخراج القيم مع fallback ذكي
            regular_close = d[2]
            regular_change = d[3]
            regular_change_abs = d[4]
            regular_volume = d[5]

            pre_close = d[6]
            pre_change = d[7]
            pre_change_abs = d[8]
            pre_volume = d[9]

            post_close = d[10]
            post_change = d[11]
            post_change_abs = d[12]
            post_volume = d[13]

            sector = escape_html(d[14] or "")
            industry = escape_html(d[15] or "")
            country = escape_html(d[16] or "")
            exchange = escape_html(d[17] or "")

            # اختيار السعر والنسبة والحجم حسب الجلسة + fallback
            if session_key == "premarket" and pre_close is not None:
                price = float(pre_close)
                change_pct = float(pre_change) if pre_change is not None else 0.0
                volume = float(pre_volume or 0)
            elif session_key == "postmarket" and post_close is not None:
                price = float(post_close)
                change_pct = float(post_change) if post_change is not None else 0.0
                volume = float(post_volume or 0)
            else:
                # السوق الرئيسي أو fallback
                price = float(regular_close or 0)
                change_pct = float(regular_change) if regular_change is not None else 0.0
                volume = float(regular_volume or 0)

            # حماية إضافية: لو النسبة صفر والسعر موجود، حاول حسابها من change_abs
            if change_pct == 0.0 and price > 0 and regular_change_abs is not None:
                try:
                    prev_close = price - float(regular_change_abs)
                    if prev_close > 0:
                        change_pct = (float(regular_change_abs) / prev_close) * 100
                except Exception:
                    pass

            # باقي الكود كما هو (جلب SEC + شروط الإرسال ...)
            # ...
            lines = [
                f"<b>{alert_title} | {symbol} | {country}</b>",
                f"🏷 <b>القطاع:</b> {sector} | <b>الصناعة:</b> {industry}",
                f"💵 <b>السعر:</b> ${price:.4f} | <b>التغير:</b> {change_pct:+.2f}% | <b>Vol:</b> {format_number(volume)}",
                f"📄 <b>إفصاحات SEC:</b>\n{sec_summary}",
                f"🔗 <a href='{sec_browse_url}'>إفصاحات SEC</a> | 📊 <a href='{tv_url}'>TradingView</a>",
                "────────────────────────"
            ]
