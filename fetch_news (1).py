#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
يسحب عناوين وملخصات قصيرة (مو المقال كامل) من خلاصات RSS لمصادر عالمية
وعربية موثوقة، يفلترها بكلمات متعلقة باليمن/الجنوب، ويحدّث تلقائيًا:
  - الشريط العاجل
  - الخبر الرئيسي (الهيرو)
  - بطاقات "آخر الأخبار"
كل عنوان مرتبط بالمصدر الأصلي عبر رابط (target=_blank) — احترامًا لحقوق النشر.
"""

import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEEDS = {
    "الجزيرة":     "https://www.aljazeera.net/xml/rss/all.xml",
    "فرانس 24":    "https://www.france24.com/ar/rss",
    "بي بي سي":    "https://feeds.bbci.co.uk/arabic/rss.xml",
    "رويترز عربي": "https://arabic.rt.com/rss/",
}

KEYWORDS = ["اليمن", "عدن", "الجنوب", "حضرموت", "لحج", "أبين", "شبوة", "المهرة", "سقطرى"]

TIMEOUT = 12
TICKER_COUNT = 6
CARD_COUNT = 6

TAG_RE = re.compile(r"<[^>]+>")


def esc(text):
    return html.escape(text or "", quote=True)


def clean_text(text, max_len=None):
    text = TAG_RE.sub("", text or "")
    text = html.unescape(text).strip()
    text = re.sub(r"\s+", " ", text)
    if max_len and len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def relative_time(pubdate_raw):
    try:
        dt = parsedate_to_datetime(pubdate_raw)
        return dt.strftime("%H:%M")
    except Exception:
        return "تحديث تلقائي"


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NahshalBot)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def parse_items(xml_bytes, source_name):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate")
        title = clean_text(title_el.text) if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        desc = clean_text(desc_el.text, max_len=160) if desc_el is not None else ""
        pubdate = date_el.text if date_el is not None else ""
        if title:
            items.append({
                "title": title, "link": link, "source": source_name,
                "dek": desc, "time": relative_time(pubdate),
            })
    return items


def matches_keywords(title):
    return any(k in title for k in KEYWORDS)


def collect_headlines():
    collected = []
    for name, url in FEEDS.items():
        try:
            raw = fetch_feed(url)
            for it in parse_items(raw, name):
                if matches_keywords(it["title"]):
                    collected.append(it)
        except Exception as e:
            print(f"تحذير: تعذّر جلب {name} ({url}): {e}", file=sys.stderr)
    return collected


def build_ticker_html(items):
    parts = [f'<span>{esc(it["source"])}</span>{esc(it["title"])}' for it in items]
    return "\n        ".join(parts)


def build_hero_html(item):
    dek = item["dek"] or "تفاصيل الخبر متوفرة عبر رابط المصدر."
    return {
        "title": f'<a href="{esc(item["link"])}" target="_blank" rel="noopener" style="color:inherit;">{esc(item["title"])}</a>',
        "dek": esc(dek),
        "author": esc(item["source"]),
        "time": esc(item["time"]),
    }


def build_cards_html(items):
    cards = []
    for it in items:
        dek = it["dek"] or "التفاصيل الكاملة عبر رابط المصدر."
        cards.append(f'''
          <article class="card">
            <div class="card-figure"><span class="tag">{esc(it["source"])}</span></div>
            <div class="card-body">
              <h3><a href="{esc(it["link"])}" target="_blank" rel="noopener" style="color:inherit;">{esc(it["title"])}</a></h3>
              <p>{esc(dek)}</p>
              <div class="meta"><span>{esc(it["source"])}</span><span>{esc(it["time"])}</span></div>
            </div>
          </article>''')
    return "".join(cards)


def replace_block(html_text, pattern, replacement_inner, label):
    m = pattern.search(html_text)
    if not m:
        print(f"تحذير: لم يتم العثور على قسم {label} — تم تخطّيه.", file=sys.stderr)
        return html_text, False
    new_html = html_text[:m.start(2)] + replacement_inner + html_text[m.end(2):]
    return new_html, True


def update_index_html(path, headlines):
    with open(path, encoding="utf-8") as f:
        html_text = f.read()

    changed_any = False

    # --- الشريط العاجل ---
    ticker_items = headlines[:TICKER_COUNT]
    if ticker_items:
        pattern = re.compile(r'(<div class="track">\n)(.*?)(\n\s*</div>\n\s*</div>\n\s*</div>)', re.S)
        html_text, ok = replace_block(html_text, pattern, "        " + build_ticker_html(ticker_items) + "\n      ", "الشريط العاجل")
        changed_any = changed_any or ok

    # --- الخبر الرئيسي ---
    if headlines:
        hero = build_hero_html(headlines[0])

        h1_pattern = re.compile(r'(<h1>)(.*?)(</h1>)', re.S)
        html_text, ok1 = replace_block(html_text, h1_pattern, hero["title"], "عنوان الهيرو")

        dek_pattern = re.compile(r'(<p class="dek">)(.*?)(</p>)', re.S)
        html_text, ok2 = replace_block(html_text, dek_pattern, hero["dek"], "ملخص الهيرو")

        byline_inner = (
            f'\n            <span>المصدر: <b>{hero["author"]}</b></span>\n'
            f'            <span>{hero["time"]}</span>\n'
            f'            <span>تحديث تلقائي</span>\n          '
        )
        byline_pattern = re.compile(r'(<div class="byline">)(.*?)(</div>)', re.S)
        html_text, ok3 = replace_block(html_text, byline_pattern, byline_inner, "بيانات الهيرو")

        changed_any = changed_any or ok1 or ok2 or ok3

    # --- بطاقات آخر الأخبار ---
    card_items = headlines[1:1 + CARD_COUNT] or headlines[:CARD_COUNT]
    if card_items:
        cards_pattern = re.compile(r'(<div class="card-grid">)(.*?)(\n\s*</div>\n\s*</div>\n\s*</section>)', re.S)
        html_text, ok = replace_block(html_text, cards_pattern, build_cards_html(card_items) + "\n        ", "بطاقات الأخبار")
        changed_any = changed_any or ok

    if changed_any:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_text)
    return changed_any


if __name__ == "__main__":
    index_path = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    headlines = collect_headlines()
    if not headlines:
        print("ما فيه عناوين مطابقة الآن — الملف ما تغيّر.", file=sys.stderr)
        sys.exit(0)
    ok = update_index_html(index_path, headlines)
    print("تم التحديث (الشريط العاجل + الهيرو + البطاقات)." if ok else "فشل التحديث.")
