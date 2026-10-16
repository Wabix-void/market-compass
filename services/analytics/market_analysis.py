"""市场行情分析（数据侧）。

职责：
1. 把用户自由输入的商品名（如「保温杯」「露营装备」「慕思家」）解析为可分析的类目/品牌；
2. 罗列该标的的结构化行情数据（规模、趋势、价格带、竞争格局、品牌集中度、
   评价痛点、增长榜/下滑榜、置信度分布）。

只输出指标层（fact_metric_daily）算出的数值，供 AI 层生成结论并做证据链校验。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

DAYS = 56

# 评价关键词的负面提示词（用于把"痛点"从评价词里分离出来）
NEGATIVE_HINTS = [
    "偏薄", "偏重", "偏小", "偏紧", "偏松", "偏软", "偏少", "偏细", "偏深",
    "磕碰", "色差", "卡顿", "异味", "有味", "毛刺", "划痕", "生锈", "一般",
    "声偏大", "掉毛", "不稳", "粗糙", "费时", "发热", "塑料感", "焊接",
]

PRICE_BANDS = [(0, 30), (30, 60), (60, 100), (100, 150), (150, 250),
               (250, 500), (500, 1000), (1000, 10 ** 9)]


# ---------------------------------------------------------------------------
# 输入解析
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    table = str.maketrans("０１２３４５６７８９（）【】", "0123456789()[]")
    return "".join(text.translate(table).split()).lower()


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


DEMO_PLATFORMS = ("p_tmall", "p_jd", "p_pdd")   # 演示数据源使用的平台
_DEMO_SQL = ",".join("?" for _ in DEMO_PLATFORMS)


def _source_label(products: int, demo_products: int) -> str:
    if products <= 0:
        return "无商品"
    if demo_products == products:
        return "演示数据"
    if demo_products == 0:
        return "真实数据"
    return "混合来源"


def build_lexicon(conn: sqlite3.Connection) -> list[dict]:
    """词典：细分类目 / 父类目 / 品牌的名称与别名，并标注数据来源与商品数。

    同名类目可能来自不同数据源（例如演示数据的「保温杯」与苏宁真实数据的「保温杯」），
    因此带上 products / is_demo / source_label，供 resolve 排序与前端区分展示。
    """
    entries: list[dict] = []
    for row in conn.execute(
        "SELECT c.category_id, c.parent_id, c.name, c.level, c.aliases_json,"
        "  (SELECT COUNT(*) FROM dim_product p WHERE p.category_id = c.category_id) AS products,"
        f"  (SELECT COUNT(*) FROM dim_product p WHERE p.category_id = c.category_id"
        f"     AND p.platform_id IN ({_DEMO_SQL})) AS demo_products"
        " FROM dim_category c",
        DEMO_PLATFORMS,
    ):
        aliases = json.loads(row["aliases_json"] or "[]")
        kind = "subcategory" if row["level"] == 2 else "parent"
        products = int(row["products"] or 0)
        source = _source_label(products, int(row["demo_products"] or 0))
        for term in {row["name"], *aliases}:
            entries.append({
                "term": term, "norm": _normalize(term), "kind": kind,
                "category_id": row["category_id"], "label": row["name"],
                "products": products, "is_demo": source == "演示数据",
                "source_label": source,
            })
    for row in conn.execute(
        "SELECT brand, COUNT(*) AS products,"
        f"  SUM(CASE WHEN platform_id IN ({_DEMO_SQL}) THEN 1 ELSE 0 END) AS demo_products"
        " FROM dim_product WHERE brand IS NOT NULL GROUP BY brand",
        DEMO_PLATFORMS,
    ):
        products = int(row["products"] or 0)
        source = _source_label(products, int(row["demo_products"] or 0))
        entries.append({
            "term": row["brand"], "norm": _normalize(row["brand"]), "kind": "brand",
            "category_id": None, "label": row["brand"],
            "products": products, "is_demo": source == "演示数据",
            "source_label": source,
        })
    return entries


def _score(query: str, term: str) -> float:
    if not query or not term:
        return 0.0
    if query == term:
        return 1.0
    if term in query and len(term) >= 2:
        return 0.55 + 0.45 * (len(term) / len(query))
    if query in term and len(query) >= 2:
        return 0.50 + 0.50 * (len(query) / len(term))
    overlap = _bigrams(query) & _bigrams(term)
    union = _bigrams(query) | _bigrams(term)
    return 0.9 * (len(overlap) / len(union)) if union else 0.0


KIND_WEIGHT = {"subcategory": 1.0, "parent": 0.95, "brand": 0.9}
MATCH_THRESHOLD = 0.5


def resolve(conn: sqlite3.Connection, text: str, limit: int = 5) -> dict:
    """把自由输入解析为最可能的分析标的。"""
    query = _normalize(text)
    results: list[dict] = []
    for entry in build_lexicon(conn):
        raw = _score(query, entry["norm"])
        if raw <= 0:
            continue
        results.append({
            "term": entry["term"],
            "label": entry["label"],
            "kind": entry["kind"],
            "category_id": entry["category_id"],
            "products": entry.get("products", 0),
            "source_label": entry.get("source_label", ""),
            "is_demo": entry.get("is_demo", False),
            "score": round(min(raw * KIND_WEIGHT[entry["kind"]], 1.0), 3),
            "reason": "完全匹配" if raw == 1.0 else (
                "输入包含该词" if entry["norm"] in query else
                "该词包含输入" if query in entry["norm"] else "文本相似"),
        })

    # 同分时优先"真实数据"（其次商品数多的），避免同名类目命中演示数据
    results.sort(key=lambda item: (item["score"], not item["is_demo"], item["products"]),
                 reverse=True)
    # 同一类目只保留最高分条目
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in results:
        key = f"{item['kind']}:{item['category_id'] or item['label']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    best = deduped[0] if deduped else None
    matched = bool(best and best["score"] >= MATCH_THRESHOLD)
    return {
        "query": text,
        "matched": matched,
        "best": best if matched else None,
        "candidates": deduped,
        "message": (
            f"已解析为「{best['label']}」（{best.get('source_label', '')}，"
            f"{best['reason']}，匹配度 {best['score']:.2f}）"
            if matched else
            "当前数据未覆盖该商品。你可以在下方候选里选择最接近的标的，或等待接入更多公开数据源。"
        ),
    }


# ---------------------------------------------------------------------------
# 行情快照
# ---------------------------------------------------------------------------
def scope_category_ids(conn: sqlite3.Connection, category_id: str) -> list[str]:
    """父类目返回其全部子类目，子类目返回自身。"""
    row = conn.execute(
        "SELECT level FROM dim_category WHERE category_id = ?", [category_id]
    ).fetchone()
    if row and row["level"] == 1:
        children = [r["category_id"] for r in conn.execute(
            "SELECT category_id FROM dim_category WHERE parent_id = ?", [category_id])]
        return children or [category_id]
    return [category_id]


def _scope_clause(ids: list[str]) -> tuple[str, list]:
    return "(" + ",".join("?" for _ in ids) + ")", list(ids)


def _window(conn: sqlite3.Connection, days: int) -> tuple[str, str]:
    row = conn.execute("SELECT MAX(stat_date) AS d FROM fact_metric_daily").fetchone()
    end = date.fromisoformat(row["d"]) if row and row["d"] else date.today()
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def _shares(values: list[float]) -> tuple[float, float]:
    total = sum(values)
    if total <= 0:
        return 0.0, 0.0
    shares = sorted((v / total for v in values), reverse=True)
    return sum(shares[:5]), sum(s ** 2 for s in shares)


def brand_shares(conn: sqlite3.Connection, ids: list[str], days: int = DAYS) -> list[dict]:
    start, end = _window(conn, days)
    placeholders, params = _scope_clause(ids)
    rows = conn.execute(
        "SELECT p.brand AS brand, SUM(m.sps_mid) AS sps, SUM(m.gms_mid) AS gms,"
        "       COUNT(DISTINCT m.product_id) AS listing_count"
        " FROM fact_metric_daily m JOIN dim_product p ON p.product_id = m.product_id"
        f" WHERE m.stat_date BETWEEN ? AND ? AND m.category_id IN {placeholders}"
        " GROUP BY p.brand ORDER BY sps DESC",
        [start, end] + params,
    ).fetchall()
    total = sum(float(r["sps"] or 0) for r in rows)
    result = []
    for row in rows:
        sps = float(row["sps"] or 0)
        result.append({
            "brand": row["brand"] or "未知品牌",
            "sps": round(sps, 1),
            "gms": round(float(row["gms"] or 0), 2),
            "listing_count": row["listing_count"],
            "share": round(sps / total, 4) if total > 0 else 0.0,
        })
    return result


def keyword_analysis(conn: sqlite3.Connection, ids: list[str]) -> dict:
    placeholders, params = _scope_clause(ids)
    rows = conn.execute(
        "SELECT r.top_keywords_json AS keywords FROM fact_review_agg r"
        " JOIN dim_product p ON p.product_id = r.product_id"
        f" WHERE p.category_id IN {placeholders}",
        params,
    ).fetchall()

    counter: dict[str, int] = {}
    for row in rows:
        for word in json.loads(row["keywords"] or "[]"):
            counter[word] = counter.get(word, 0) + 1

    negative = [(w, c) for w, c in counter.items() if any(h in w for h in NEGATIVE_HINTS)]
    positive = [(w, c) for w, c in counter.items() if not any(h in w for h in NEGATIVE_HINTS)]
    negative.sort(key=lambda item: item[1], reverse=True)
    positive.sort(key=lambda item: item[1], reverse=True)
    total = sum(counter.values())
    negative_count = sum(c for _, c in negative)

    return {
        "negative_keyword_share": round(negative_count / total, 4) if total else 0.0,
        "negative": [{"keyword": w, "count": c} for w, c in negative[:8]],
        "positive": [{"keyword": w, "count": c} for w, c in positive[:8]],
        "sample_size": len(rows),
    }


def market_snapshot(conn: sqlite3.Connection, category_id: str, days: int = DAYS) -> dict:
    ids = scope_category_ids(conn, category_id)
    placeholders, params = _scope_clause(ids)
    start, end = _window(conn, days)

    info = conn.execute(
        "SELECT c.category_id, c.name, c.level, c.parent_id, p.name AS parent_name"
        " FROM dim_category c LEFT JOIN dim_category p ON p.category_id = c.parent_id"
        " WHERE c.category_id = ?", [category_id],
    ).fetchone()

    products = conn.execute(
        "SELECT m.product_id, p.title, p.brand, p.category_id, pl.name AS platform_name,"
        "       SUM(m.sps_mid) AS sps, SUM(m.gms_mid) AS gms, AVG(m.confidence) AS confidence,"
        "       AVG(COALESCE(s.promo_price, s.price)) AS price"
        " FROM fact_metric_daily m"
        " JOIN dim_product p ON p.product_id = m.product_id"
        " JOIN dim_platform pl ON pl.platform_id = p.platform_id"
        " LEFT JOIN (SELECT product_id, AVG(price) AS price, AVG(promo_price) AS promo_price"
        "            FROM fact_signal_daily GROUP BY product_id) s ON s.product_id = m.product_id"
        f" WHERE m.stat_date BETWEEN ? AND ? AND m.category_id IN {placeholders}"
        " GROUP BY m.product_id",
        [start, end] + params,
    ).fetchall()

    mid = (date.fromisoformat(end) - timedelta(days=max(days // 2 - 1, 1))).isoformat()
    recent_rows = conn.execute(
        "SELECT m.product_id, SUM(m.sps_mid) AS sps FROM fact_metric_daily m"
        f" WHERE m.stat_date > ? AND m.stat_date <= ? AND m.category_id IN {placeholders}"
        " GROUP BY m.product_id",
        [mid, end] + params,
    ).fetchall()
    prev_rows = conn.execute(
        "SELECT m.product_id, SUM(m.sps_mid) AS sps FROM fact_metric_daily m"
        f" WHERE m.stat_date >= ? AND m.stat_date <= ? AND m.category_id IN {placeholders}"
        " GROUP BY m.product_id",
        [start, mid] + params,
    ).fetchall()
    recent = {r["product_id"]: float(r["sps"] or 0) for r in recent_rows}
    previous = {r["product_id"]: float(r["sps"] or 0) for r in prev_rows}

    items = []
    for row in products:
        pid = row["product_id"]
        rec, prev = recent.get(pid, 0.0), previous.get(pid, 0.0)
        raw_price = float(row["price"] or 0.0)
        items.append({
            "product_id": pid,
            "title": row["title"],
            "brand": row["brand"],
            "category_id": row["category_id"],
            "platform_name": row["platform_name"],
            "sps": round(float(row["sps"] or 0), 1),
            "gms": round(float(row["gms"] or 0), 2),
            "confidence": round(float(row["confidence"] or 0), 3),
            "price": round(raw_price, 2) if raw_price > 0 else None,
            "growth": round((rec - prev) / prev, 4) if prev > 0 else 0.0,
        })

    sps_values = [item["sps"] for item in items]
    total_sps = sum(sps_values)
    total_gms = sum(item["gms"] for item in items)
    cr5, hhi = _shares(sps_values)

    recent_total = sum(recent.values())
    prev_total = sum(previous.values())
    growth = ((recent_total - prev_total) / prev_total) if prev_total > 0 else 0.0
    avg_confidence = (sum(item["confidence"] for item in items) / len(items)) if items else 0.0

    # 价格带（只在确实拿到价格的商品上计算；公开页面价格常为异步加载而缺失）
    priced = [item for item in items if item["price"]]
    price_coverage = round(len(priced) / len(items), 4) if items else 0.0
    bands = []
    for low, high in PRICE_BANDS:
        members = [item for item in priced if low <= item["price"] < high]
        sps = sum(item["sps"] for item in members)
        bands.append({
            "band": f"{low}-{high}" if high < 10 ** 9 else f"{low}+",
            "low": low, "high": None if high >= 10 ** 9 else high,
            "listing_count": len(members), "sps": round(sps, 1),
        })
    band_total = sum(b["sps"] for b in bands)
    for band in bands:
        band["sps_share"] = round(band["sps"] / band_total, 4) if band_total > 0 else 0.0
    valid_bands = [b for b in bands if b["sps"] > 0]
    main_band = max(valid_bands, key=lambda b: b["sps"]) if valid_bands else None
    avg_price = round(sum(item["price"] for item in priced) / len(priced), 2) if priced else None

    # 品牌集中度
    shares = brand_shares(conn, ids, days)
    brand_cr3 = round(sum(item["share"] for item in shares[:3]), 4)

    # 子类目分布（父类目视角）
    sub_map: dict[str, dict] = {}
    for item in items:
        entry = sub_map.setdefault(item["category_id"], {"sps": 0.0, "gms": 0.0, "count": 0})
        entry["sps"] += item["sps"]
        entry["gms"] += item["gms"]
        entry["count"] += 1
    names = {row["category_id"]: row["name"] for row in conn.execute(
        "SELECT category_id, name FROM dim_category WHERE level = 2")}
    subcategories = [
        {"category_id": cid, "name": names.get(cid, cid), "total_sps": round(v["sps"], 1),
         "total_gms": round(v["gms"], 2), "listing_count": v["count"],
         "share": round(v["sps"] / total_sps, 4) if total_sps > 0 else 0.0}
        for cid, v in sub_map.items()
    ]
    subcategories.sort(key=lambda item: item["total_sps"], reverse=True)

    # 需求热度与供需缺口（缺口指数借用跨子类目归一化口径，保证可比）
    from services.analytics import queries  # 局部导入，避免包内循环引用

    heat = 0.0
    for cid in ids:
        row = conn.execute(
            "SELECT AVG(heat_index) AS h FROM fact_search_heat"
            " WHERE keyword_id = ? AND stat_date BETWEEN ? AND ?",
            [f"kw_{cid}", start, end],
        ).fetchone()
        heat += float(row["h"] or 0.0) if row else 0.0

    gap_map = {item["category_id"]: item["gap_index"]
               for item in queries.subcategory_ranking(conn, days)}
    gap_candidates = [gap_map[cid] for cid in ids if cid in gap_map]
    gap_index = round(max(gap_candidates), 2) if gap_candidates else 0.0

    keywords = keyword_analysis(conn, ids)

    ranked = sorted(items, key=lambda item: item["sps"], reverse=True)
    movers = [item for item in items if item["sps"] > 0]
    top_growth = sorted(movers, key=lambda item: item["growth"], reverse=True)[:8]
    top_decline = sorted(movers, key=lambda item: item["growth"])[:8]

    high = len([i for i in items if i["confidence"] >= 0.8])
    mid_conf = len([i for i in items if 0.55 <= i["confidence"] < 0.8])
    low = len([i for i in items if i["confidence"] < 0.55])

    return {
        "category": {
            "category_id": info["category_id"], "name": info["name"],
            "level": info["level"], "parent_id": info["parent_id"],
            "parent_name": info["parent_name"],
            "scope": ids,
        },
        "period": [start, end],
        "days": days,
        "total_sps": round(total_sps, 1),
        "total_gms": round(total_gms, 2),
        "listing_count": len(items),
        "growth": round(growth, 4),
        "cr5": round(cr5, 4),
        "hhi": round(hhi, 4),
        "avg_confidence": round(avg_confidence, 4),
        "brand_cr3": brand_cr3,
        "negative_keyword_share": keywords["negative_keyword_share"],
        "main_band_share": round(main_band["sps_share"], 4) if main_band else 0.0,
        "main_band": main_band["band"] if main_band else None,
        "avg_price": avg_price,
        "price_coverage": price_coverage,
        "heat_index": round(heat, 1),
        "gap_index": gap_index,
        "brand_shares": shares[:10],
        "price_bands": bands,
        "subcategories": subcategories,
        "keywords": keywords,
        "top_products": ranked[:12],
        "top_growth": top_growth,
        "top_decline": top_decline,
        "confidence_dist": {"high": high, "mid": mid_conf, "low": low},
    }
