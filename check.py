"""IKEA サーキュラーマーケット ウォッチャー

watchlist.json の条件で対象店舗の出品を確認し、
- docs/index.html（GitHub Pages の一覧ページ）を更新
- state/seen.json（前回までに見た出品）を更新
- 新着があれば ntfy でスマホに通知
する。
"""

import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
OFFERS_URL = "https://web-api.ikea.com/circular/circular-asis/offers/grouped/search"
PAGE = "https://www.ikea.com/jp/ja/second-hand/buy-from-ikea/"
DEBUG = os.environ.get("DEBUG") == "1"


def get_json(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Origin": "https://www.ikea.com",
            "Referer": "https://www.ikea.com/jp/ja/second-hand/buy-from-ikea/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_offers(store_id):
    """1店舗分の出品をすべて取得する（ページ送り）。"""
    out, page = [], 0
    while True:
        data = get_json(
            OFFERS_URL,
            {"languageCode": "ja", "size": 64, "storeIds": store_id, "page": page},
        )
        if DEBUG and page == 0:
            dump(f"offers_{store_id}.json", data)
        content = data.get("content") or []
        out.extend(content)
        total_pages = data.get("totalPages") or 1
        page += 1
        if page >= total_pages or not content:
            break
        time.sleep(1.5)
    return out


def flatten(group, store):
    """API の1グループ（同一商品）を出品単位に展開する。"""
    rows = []
    for o in group.get("offers") or []:
        cond = "・".join(x for x in [o.get("productConditionTitle"), o.get("reasonDiscount"),
                                      o.get("additionalInfo")] if x)
        rows.append(
            {
                "key": f"{store['id']}:{o.get('offerNumber') or o.get('id')}",
                "store": store["name"],
                "title": group.get("title") or "",
                "desc": o.get("description") or group.get("description") or "",
                "condition": cond,
                "price": o.get("price"),
                "orig": group.get("originalPrice"),
                "image": group.get("heroImage") or "",
                "url": f"{PAGE}?stores={store['id']}#/item/{o.get('offerNumber')}",
                "offer_no": o.get("offerNumber") or "",
            }
        )
    return rows


def match(row, item):
    # 商品種別 = 説明の最初の「,」まで（例：「ラグ パイル短」「ペンダントランプ」）。
    # 色名（ライトグレー等）や商品名（LAGKAPTEN等）での誤ヒットを避けるため、
    # 既定では種別だけを見る。商品名で探すものは target を "title" にする。
    ptype = row["desc"].split(",")[0].split("\n")[0]
    text = (row["title"] if item.get("target") == "title" else ptype).lower()
    if item.get("target") == "title":
        ptype_l = ptype.lower()
        if any(x.lower() in ptype_l for x in item.get("exclude", [])):
            return False
    if not any(k.lower() in text for k in item["keywords"]):
        return False
    if any(x.lower() in text for x in item.get("exclude", [])):
        return False
    mp = item.get("max_price")
    if mp is not None and row["price"] is not None and float(row["price"]) > mp:
        return False
    return True


def yen(v):
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return "-"


def off(row):
    try:
        return f"{100 - round(float(row['price']) / float(row['orig']) * 100)}%引"
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


def dump(name, data):
    p = ROOT / "debug" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1)[:200000], encoding="utf-8")


def render(hits, new_keys, now):
    cards = []
    for cat, rows in hits.items():
        cards.append(f"<h2>{html.escape(cat)}<span>{len(rows)}件</span></h2>")
        if not rows:
            cards.append('<p class="none">該当なし</p>')
        for r in rows:
            badge = '<b class="new">NEW</b>' if r["key"] in new_keys else ""
            img = f'<img src="{html.escape(r["image"])}" loading="lazy" alt="">' if r["image"] else ""
            cards.append(
                f'<a class="card" href="{html.escape(r["url"])}">{img}<div>'
                f'<p class="t">{badge}{html.escape(r["title"])}</p>'
                f'<p class="d">{html.escape(r["desc"])}</p>'
                f'<p class="p">{yen(r["price"])} <s>{yen(r["orig"]) if r["orig"] else ""}</s> {off(r)}</p>'
                f'<p class="s">{html.escape(r["store"])}・{html.escape(r["condition"])}・出品番号 {html.escape(str(r["offer_no"]))}</p>'
                f"</div></a>"
            )
    body = "\n".join(cards)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IKEA サーキュラーマーケット</title><style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:0 auto;max-width:640px;padding:16px;color:#1a1a1a;background:#fff}}
h1{{font-size:18px;margin:0}} .u{{color:#666;font-size:12px;margin:4px 0 16px}}
h2{{font-size:15px;border-bottom:1px solid #ddd;padding-bottom:4px;margin:24px 0 8px}} h2 span{{color:#666;font-weight:normal;margin-left:8px}}
.card{{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #eee;color:inherit;text-decoration:none}}
.card img{{width:88px;height:88px;object-fit:cover;flex:none;background:#f4f4f4}}
.card p{{margin:2px 0}} .t{{font-weight:bold;font-size:14px}} .d,.s{{font-size:12px;color:#555}} .p{{font-size:14px}} s{{color:#999;font-size:12px}}
.new{{background:#1a1a1a;color:#fff;font-size:10px;padding:1px 5px;margin-right:6px}} .none{{color:#999;font-size:13px}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}} .d,.s,.u{{color:#aaa}} .card{{border-color:#333}} h2{{border-color:#444}} .new{{background:#eee;color:#111}}}}
</style></head><body>
<h1>IKEA サーキュラーマーケット</h1><p class="u">最終チェック {now:%Y/%m/%d %H:%M}</p>
{body}
</body></html>"""


def notify(new_rows):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic or not new_rows:
        return
    lines = [f"{r['category']}｜{r['title']} {yen(r['price'])}（{r['store']}）" for r in new_rows[:10]]
    if len(new_rows) > 10:
        lines.append(f"ほか{len(new_rows) - 10}件")
    page = os.environ.get("PAGE_URL", "")
    payload = {
        "topic": topic,
        "title": f"IKEAサーキュラー 新着{len(new_rows)}件",
        "message": "\n".join(lines),
        "click": page or PAGE,
    }
    req = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30)


def main():
    cfg = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    state_path = ROOT / "state" / "seen.json"
    seen = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    first_run = not seen

    stores = {name: {"id": sid, "name": name} for name, sid in cfg["stores"].items()}

    hits = {it["name"]: [] for it in cfg["items"]}
    current = set()
    for w, st in stores.items():
        try:
            groups = fetch_offers(st["id"])
        except Exception as e:  # 1店舗の失敗で全体を止めない
            print(f"[WARN] {st['name']} の取得に失敗: {e}")
            continue
        print(f"{st['name']}: {len(groups)}グループ")
        for g in groups:
            for row in flatten(g, st):
                current.add(row["key"])
                for it in cfg["items"]:
                    if it.get("stores") and w not in it["stores"]:
                        continue  # この商品は対象外の店舗
                    if match(row, it):
                        row["category"] = it["name"]
                        hits[it["name"]].append(row)
                        break
        time.sleep(1.5)

    if not current:
        sys.exit("[ERROR] 出品を1件も取得できなかった（アクセス遮断の可能性）")

    now = datetime.now(JST)
    all_hits = [r for rows in hits.values() for r in rows]
    new_rows = [r for r in all_hits if r["key"] not in seen]
    new_keys = {r["key"] for r in new_rows}

    # 今出ているものだけ残す（売れたものは消える）
    seen = {k: seen.get(k, now.isoformat()) for k in current}
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(seen, ensure_ascii=False, indent=0), encoding="utf-8")

    for rows in hits.values():
        rows.sort(key=lambda r: (r["key"] not in new_keys, float(r["price"] or 0)))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(render(hits, new_keys, now), encoding="utf-8")

    print(f"該当 {len(all_hits)}件 / 新着 {len(new_rows)}件")
    if first_run:
        print("初回のため通知は全該当分を送る")
    notify(new_rows)


if __name__ == "__main__":
    main()
