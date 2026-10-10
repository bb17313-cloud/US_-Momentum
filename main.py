import os
import json
import re
import html
import requests
import urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime
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

# آخر خبر جلبه TradingView لكل سهم (العنوان الأصلي) - يُستخدم لمنع تكراره داخل المحفزات
_TV_LATEST = {}

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

    # Pre-market: 04:00 AM - 09:30 AM EST
    if 400 <= time_num_ny < 930:
        return "premarket", "🌅 Pre-Market (ما قبل الافتتاح)"
    # Main Market: 09:30 AM - 04:00 PM EST
    elif 930 <= time_num_ny < 1600:
        return "market", "🔔 Main Session (السوق الرئيسي)"
    # Post-market: 04:00 PM - 08:00 PM EST
    elif 1600 <= time_num_ny < 2000:
        return "postmarket", "🌙 Post-Market (ما بعد الإغلاق)"
    else:
        return "closed", "⏸️ المغلق (خارج أوقات التداول)"

# ================================
# جلب أحدث الأخبار المباشرة لـ TradingView
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
                
                news_url = f"https://www.tradingview.com{story_path}" if story_path else f"https://www.tradingview.com/symbols/{exchange}-{symbol}/news/"

                time_str = ""
                if pub_time:
                    dt = datetime.fromtimestamp(pub_time, tz=ZoneInfo("UTC")).astimezone(RIYADH)
                    time_str = f" ({dt.strftime('%H:%M')} KSA)"

                if title:
                    _TV_LATEST[str(symbol).upper().strip()] = {"title": title, "url": news_url}
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
# دمج الأحداث (SEC + الأخبار) ومنع التكرار
# ================================
_NEWS_KIND_PATTERNS = [
    ("reverse_split", ("reverse split", "reverse stock split")),
    ("offering", ("offering", "private placement", "registered direct", "at-the-market")),
    ("earnings", ("earnings", "results", "guidance", "outlook", "revenue")),
    ("fda", ("fda", "pdufa", "approval")),
    ("trial", ("clinical trial", "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii")),
    ("patent", ("patent",)),
    ("deal", ("agreement", "contract", "partnership", "acquisition", "acquire", "merger", "award", "deal")),
    ("management", ("ceo", "cfo", "appoints", "resigns")),
    ("dividend", ("dividend",)),
]

_8K_KIND_BY_ITEM = [
    ("3.03", "reverse_split"), ("5.03", "reverse_split"), ("3.02", "offering"),
    ("3.01", "listing"), ("2.02", "earnings"), ("1.01", "deal"), ("5.02", "management"), ("2.03", "debt"),
]

_KIND_LABEL_AR = {
    "reverse_split": "تجزئة عكسية", "offering": "طرح/إصدار", "earnings": "نتائج مالية/أرباح",
    "deal": "اتفاقية جوهرية", "management": "تغيير في الإدارة", "debt": "التزام مالي جديد",
    "dividend": "توزيعات", "listing": "إشعار شروط الإدراج والامتثال",
    "fda": "موافقة/إفصاح FDA", "trial": "تجارب سريرية", "patent": "براءة اختراع",
}

SEC_FORMS_AR = {
    "4": "معاملة مطلع", "D": "إشعار طرح خاص", "6-K": "تقرير شركة أجنبية", "8-K": "إفصاح عن أحداث جوهرية",
    "10-Q": "التقرير الربع سنوي", "10-K": "التقرير السنوي", "20-F": "التقرير السنوي (أجنبية)",
}

ISSUANCE_FORMS = {
    "S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-1/A", "F-3", "F-3/A", "D", "D/A",
}

def _news_kind(title):
    t = title.lower()
    for kind, keys in _NEWS_KIND_PATTERNS:
        if any(re.search(rf"\b{re.escape(k)}", t) for k in keys):
            return kind
    return None

def _filing_kind(f):
    form = f["form"]
    if form == "8-K":
        for item, kind in _8K_KIND_BY_ITEM:
            if item in f["items"]:
                return kind, True
        return _news_kind(f.get("desc", "") or ""), False
    if form in ISSUANCE_FORMS or form.upper().startswith("424B"):
        return "offering", True
    if form in ("10-Q", "10-K", "20-F"):
        return "earnings", False
    if form == "6-K":
        return _news_kind(f.get("desc", "") or ""), False
    return None, False

def _filing_label(f, kind):
    if kind == "offering" and f["form"] == "8-K":
        return "بيع أسهم غير مسجل"
    if f["form"] != "8-K" and f.get("brief"):
        return f["brief"]
    return _KIND_LABEL_AR.get(kind, SEC_FORMS_AR.get(f["form"], f["form"]))

def _days_apart(d1, d2):
    try:
        return abs((datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d2, "%Y-%m-%d")).days)
    except Exception:
        return 999

def _title_tokens(title):
    t = re.sub(r"\s[-–|]\s[^-–|]{2,30}$", "", title.lower())
    return {w for w in re.findall(r"[a-z0-9$%.]+", t) if len(w) > 2}

def _same_story(a, b):
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter >= 4 and inter / min(len(ta), len(tb)) >= 0.7

def _parse_news_date(s):
    try:
        return parsedate_to_datetime(s.strip()).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(NEW_YORK).strftime("%Y-%m-%d")

def format_filing_line(f):
    return f"• <b>{f['form']}</b> ({f['date']}): <a href='{f['url']}'>{f['brief']}</a>"

def _render_event(ev, prefix="• "):
    raw = ev["title"] or ev["label"]
    if ev["title"]:
        short = raw if len(raw) <= 80 else raw[:77] + "..."
        raw = translate_to_arabic(short)
    text = html.escape(raw)
    if ev.get("note"):
        text += f" ({html.escape(ev['note'])})"
    links = " · ".join(f"<a href='{u}'>{html.escape(n)}</a>" for n, u in ev["links"][:3] if u)
    line = f'{prefix}{text} <code>{ev["date"]}</code>'
    return f"{line} — {links}" if links else line

def build_alert_sections(filings, news_items, sec_limit=4, cat_limit=5, skip_events_acc=(), skip_sec_acc=()):
    """يدمج SEC + الأخبار: كل حدث يظهر مرة واحدة وتتجمع مصادره في سطر واحد"""
    events = []

    # 1) الأخبار: نفس القصة من أكثر من مصدر = حدث واحد
    for n in news_items:
        src = n.get("source") or "News"
        target = next((e for e in events if e["title"] and _same_story(e["title"], n["title"])), None)
        if target:
            if src not in [x[0] for x in target["links"]]:
                target["links"].append((src, n["url"]))
            continue
        events.append({"kind": _news_kind(n["title"]), "date": n["date"], "title": n["title"],
                       "label": "", "links": [(src, n["url"])], "acc": None, "note": None})

    # 2) الإفصاحات: تُدمج مع خبر من نفس النوع (±3 أيام) وإلا تظهر وحدها مرة لكل نوع
    seen_alone = set()
    for f in filings:
        kind, alone = _filing_kind(f)
        if not kind:
            continue
        target = next((e for e in events if e["kind"] == kind and e["acc"] is None and e["title"]
                       and _days_apart(e["date"], f["date"]) <= 3), None)
        if target:
            target["links"].insert(0, (f["form"], f["url"]))
            target["acc"] = f["accession"]
            if kind in ("offering", "reverse_split") and f["form"] != "8-K" and f.get("brief"):
                target["note"] = f["brief"]
        elif alone and kind not in seen_alone:
            seen_alone.add(kind)
            events.append({"kind": kind, "date": f["date"], "title": None, "label": _filing_label(f, kind),
                           "links": [(f["form"], f["url"])], "acc": f["accession"], "note": None})

    # 3) التوزيع على الأقسام (الأحداث المصنّفة أولاً ثم الأحدث تاريخاً)
    skip_events_acc = {a for a in skip_events_acc if a}
    skip_sec_acc = {a for a in skip_sec_acc if a}
    ordered = sorted(events, key=lambda e: e["date"], reverse=True)
    ordered.sort(key=lambda e: e["kind"] is None)
    ordered = [e for e in ordered if not (e["title"] is None and e["acc"] in skip_events_acc)]

    corp = [e for e in ordered if e["kind"] == "reverse_split"][:2]
    issuance = [e for e in ordered if e["kind"] == "offering" and e["acc"]][:2]
    taken = {id(e) for e in corp + issuance}
    rest = [e for e in ordered if id(e) not in taken]
    cats = rest[:cat_limit]
    omitted = len(rest) - len(cats)

    corp_lines = [_render_event(e, prefix="📉 ") for e in corp]
    catalyst_lines = [_render_event(e) for e in cats]
    if omitted > 0:
        catalyst_lines.append(f"➕ {omitted} أخبار/أحداث أخرى غير معروضة")

    # 4) إفصاحات SEC التي لم تظهر أعلاه (نموذج واحد لكل يوم)
    shown = {e["acc"] for e in corp + issuance + cats if e["acc"]} | skip_sec_acc
    counts = {}
    for f in filings:
        counts[(f["form"], f["date"])] = counts.get((f["form"], f["date"]), 0) + 1
    sec_lines, seen_keys = [], set()
    for f in filings:
        key = (f["form"], f["date"])
        if f["accession"] in shown or key in seen_keys:
            continue
        seen_keys.add(key)
        line = format_filing_line(f)
        if counts[key] > 1:
            line += f" ×{counts[key]}"
        sec_lines.append(line)
        if len(sec_lines) >= sec_limit:
            break

    return {
        "corp": corp_lines,
        "issuance": [_render_event(e) for e in issuance],
        "catalysts": catalyst_lines,
        "sec": sec_lines,
    }

# ================================
# تحليل جلب بيانات SEC والأخبار
# ================================
def fetch_sec_filings_and_catalysts(symbol, check_split=True, change_pct=0.0):
    symbol = symbol.upper().strip()
    sec_headers = {"User-Agent": "StockRadarBot/1.0 (contact@stockradar.com)"}
    
    split_info = None
    split_acc = None
    offering_info = None
    offering_acc = None
    filings = []
    news_items = []
    catalysts = []
    cik_str_val = None

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
                        filings.append({
                            "form": f_form, "items": str(item_val), "date": f_date, "url": filing_url,
                            "accession": acc_num, "desc": desc, "brief": brief_desc,
                        })

                        if check_split and not split_info and f_upper in ["6-K", "8-K", "DEF 14A", "PRE 14A", "424B5", "424B3"]:
                            if doc_text:
                                text_clean = re.sub('<[^<]+?>', ' ', doc_text)
                                ratio_match = re.search(r'(?:ratio\s+of\s+|ratio\s*)?1\s*[-:\s]\s*for\s*[-:\s]*(\d+)|1\s*[:/]\s*(\d+)\s*reverse', text_clean, re.IGNORECASE)
                                date_match = re.search(r'(?:effective|scheduled|expected|execution)\s*(?:on|date)?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})', text_clean, re.IGNORECASE)

                                if ratio_match:
                                    r_val = ratio_match.group(1) or ratio_match.group(2)
                                    d_str = date_match.group(1) if date_match else f_date
                                    split_info = f"مجدول (1:{r_val}) بتاريخ {d_str} (إفصاح {f_form})"
                                    split_acc = acc_num
                                elif "reverse split" in text_clean.lower():
                                    split_info = f"معلن بإفصاح {f_form} بتاريخ {f_date}"
                                    split_acc = acc_num

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
                                offering_acc = acc_num
                                offering_info = f"<a href='{filing_url}'>{offering_info}</a>"

    except Exception as e:
        print(f"⚠️ خطأ جلب بيانات SEC لـ {symbol}: {e}")

    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        rss_res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if rss_res.status_code == 200:
            for item_xml in re.findall(r'<item>(.*?)</item>', rss_res.text, re.DOTALL)[:7]:
                t_m = re.search(r'<title>(.*?)</title>', item_xml, re.DOTALL)
                l_m = re.search(r'<link>(.*?)</link>', item_xml, re.DOTALL)
                d_m = re.search(r'<pubDate>(.*?)</pubDate>', item_xml, re.DOTALL)
                if not t_m:
                    continue
                clean_t = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t_m.group(1), flags=re.DOTALL)
                clean_t = html.unescape(clean_t).strip()
                if not clean_t:
                    continue
                news_link = l_m.group(1).strip() if l_m else None
                news_items.append({
                    "title": clean_t, "url": news_link or None,
                    "date": _parse_news_date(d_m.group(1)) if d_m else datetime.now(NEW_YORK).strftime("%Y-%m-%d"),
                    "source": "Yahoo",
                })
    except Exception as e:
        print(f"⚠️ خطأ جلب أخبار Yahoo لـ {symbol}: {e}")

    # خبر TradingView الأحدث يظهر في سطر Latest updates، فلا يتكرر داخل المحفزات
    tv_latest = _TV_LATEST.get(symbol)
    if tv_latest:
        news_items = [n for n in news_items if not _same_story(tv_latest["title"], n["title"])]

    sections = build_alert_sections(
        filings, news_items,
        skip_events_acc={split_acc, offering_acc},
        skip_sec_acc={offering_acc},
    )

    catalysts.extend(sections["corp"])
    catalysts.extend(sections["catalysts"])

    if sections["issuance"]:
        offering_info = "\n".join(([offering_info] if offering_info else []) + sections["issuance"])

    sec_summary = "\n".join(sections["sec"]) if sections["sec"] else "• لا توجد إفصاحات حديثة"
    unique_catalysts = list(dict.fromkeys(catalysts))
    catalyst_str = "\n".join(unique_catalysts) if unique_catalysts else "لا توجد محفزات رصدت مؤخراً"

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

            latest_updates = fetch_tradingview_latest_updates(symbol, exchange)

            curr_count = counts.get(symbol, 0) + 1
            counts[symbol] = curr_count

            alert_title = "🚨 Alert" if curr_count == 1 else f"🚨 Alert {curr_count}"
            tv_url = f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"

            split_sched, warrants_info, sec_summary, catalyst_str, cik_code = fetch_sec_filings_and_catalysts(
                symbol, 
                check_split=(price < 1.0),
                change_pct=change_pct
            )

            if cik_code:
                sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={cik_code}"
            else:
                sec_browse_url = "https://www.sec.gov/edgar/searchedgar/companysearch"

            lines = [
                f"<b>{alert_title} | {symbol} | {country}</b>",
                f"🏷 <b>القطاع:</b> {sector} | <b>الصناعة:</b> {industry}",
                f"💵 <b>السعر:</b> ${price:.2f} | <b>التغير:</b> {change_pct:+.2f}% | <b>Vol:</b> {format_number(volume)}",
            ]

            if price < 1.0:
                lines.append(f"📉 <b>Reverse Split:</b> {split_sched or 'لا توجد جدولة'}")

            lines.append(f"📋 <b>الإصدارات:</b> {warrants_info or 'لا توجد إصدارات معلنة'}")
            lines.append(f"⚡ <b>المحفزات والأخبار:</b>\n{catalyst_str}")
            lines.append(f"📲 <b>Latest updates:</b> {latest_updates}")
            lines.append(f"📄 <b>إفصاحات SEC:</b>\n{sec_summary}")
            
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
