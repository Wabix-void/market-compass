"""分析层查询（F3 商情分析引擎）：看板、排行、价格带、竞争格局、供需缺口。

所有数值都来自指标层 fact_metric_daily，AI 层只能引用这里算出的结果。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

PRICE_BANDS = [(0, 30), (30, 60), (60, 100), (100, 150), (150, 250), (250, 10 ** 9)]


def _as_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else date.today()


def latest_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(stat_date) AS d FROM fact_metric_daily").fetchone()
    return row["d"] if row and row["d"] else None


def window(conn: sqlite3.Connection, days: int) -> tuple[str, str]:
    end = _as_date(latest_date(conn))
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def list_categories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT category_id, parent_id, name, level FROM dim_category ORDER BY level, category_id"
    ).fetchall()
    return [dict(row) for row in rows]


def _shares(values: list[float]) -> tuple[list[float], float, float]:
    total = sum(values)
    if total <= 0:
        return [], 0.0, 0.0
    shares = [v / total for v in values]
    cr5 = sum(sorted(shares, reverse=True)[:5])
    hhi = sum(s ** 2 for s in shares)
    return shares, cr5, hhi


def overview(conn: sqlite3.Connection, category_id: str | None = None, days: int = 56) -> dict:
    start, end = window(conn, days)
    params: list = [start, end]
    category_filter = ""
    if category_id:
        category_filter = " AND m.category_id = ?"
        params.append(category_id)

    rows = conn.execute(
        "SELECT m.product_id, SUM(m.sps_mid) AS sps, SUM(m.gms_mid) AS gms,"
        "       AVG(m.confidence) AS confidence"
        " FROM fact_metric_daily m WHERE m.stat_date BETWEEN ? AND ?" + category_filter +
        " GROUP BY m.product_id",
        params,
    ).fetchall()

    sps_values = [float(r["sps"] or 0.0) for r in rows]
    total_sps = sum(sps_values)
    total_gms = sum(float(r["gms"] or 0.0) for r in rows)
    avg_conf = (sum(float(r["confidence"] or 0.0) for r in rows) / len(rows)) if rows else 0.0
    _, cr5, hhi = _shares(sps_values)

    product_count = conn.execute(
        "SELECT COUNT(*) AS c FROM dim_product p WHERE 1=1" +
        (" AND p.category_id = ?" if category_id else ""),
        ([category_id] if category_id else []),
    ).fetchone()["c"]

    # 近一半窗口 vs 前一半窗口的增长
    mid = _as_date(end) - timedelta(days=max(days // 2 - 1, 1))
    recent = conn.execute(
        "SELECT SUM(m.sps_mid) AS s FROM fact_metric_daily m"
        " WHERE m.stat_date > ? AND m.stat_date <= ?" + category_filter,
        [mid.isoformat(), end] + ([category_id] if category_id else []),
    ).fetchone()["s"] or 0.0
    previous = conn.execute(
        "SELECT SUM(m.sps_mid) AS s FROM fact_metric_daily m"
        " WHERE m.stat_date >= ? AND m.stat_date <= ?" + category_filter,
        [start, mid.isoformat()] + ([category_id] if category_id else []),
    ).fetchone()["s"] or 0.0
    growth = ((recent - previous) / previous) if previous > 0 else 0.0

    return {
        "period": [start, end],
        "total_sps": round(total_sps, 1),
        "total_gms": round(total_gms, 2),
        "product_count": product_count,
        "listing_count": len(rows),
        "cr5": round(cr5, 3),
        "hhi": round(hhi, 4),
        "growth": round(growth, 4),
        "avg_confidence": round(avg_conf, 3),
        "metric_note": "SPS 为公开信号推导的销量代理指标，非平台真实销量",
    }


def daily_trend(conn: sqlite3.Connection, category_id: str | None = None, days: int = 56) -> list[dict]:
    start, end = window(conn, days)
    params: list = [start, end]
    category_filter = ""
    if category_id:
        category_filter = " AND m.category_id = ?"
        params.append(category_id)
    rows = conn.execute(
        "SELECT m.stat_date, SUM(m.sps_mid) AS sps, SUM(m.sps_low) AS sps_low,"
        "       SUM(m.sps_high) AS sps_high, SUM(m.gms_mid) AS gms, AVG(m.confidence) AS confidence"
        " FROM fact_metric_daily m WHERE m.stat_date BETWEEN ? AND ?" + category_filter +
        " GROUP BY m.stat_date ORDER BY m.stat_date",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def price_bands(conn: sqlite3.Connection, category_id: str | None = None, days: int = 56) -> list[dict]:
    start, end = window(conn, days)
    params: list = [start, end]
    category_filter = ""
    if category_id:
        category_filter = " AND m.category_id = ?"
        params.append(category_id)

    rows = conn.execute(
        "SELECT p.product_id, COALESCE(s.price, 0) AS price, SUM(m.sps_mid) AS sps"
        " FROM fact_metric_daily m"
        " JOIN dim_product p ON p.product_id = m.product_id"
        " LEFT JOIN (SELECT product_id, AVG(price) AS price FROM fact_signal_daily GROUP BY product_id) s"
        "   ON s.product_id = m.product_id"
        " WHERE m.stat_date BETWEEN ? AND ?" + category_filter +
        " GROUP BY p.product_id",
        params,
    ).fetchall()

    buckets = []
    for low, high in PRICE_BANDS:
        members = [r for r in rows if low <= float(r["price"] or 0) < high]
        sps = sum(float(r["sps"] or 0.0) for r in members)
        label = f"{low}-{high}" if high < 10 ** 9 else f"{low}+"
        buckets.append({
            "band": label,
            "low": low,
            "high": None if high >= 10 ** 9 else high,
            "listing_count": len(members),
            "sps": round(sps, 1),
        })
    total = sum(b["sps"] for b in buckets)
    for bucket in buckets:
        bucket["sps_share"] = round(bucket["sps"] / total, 3) if total > 0 else 0.0
    return buckets


def demand_heat(conn: sqlite3.Connection, days: int = 7) -> dict[str, float]:
    start, end = window(conn, days)
    rows = conn.execute(
        "SELECT category_id, AVG(heat_index) AS heat FROM ("
        "  SELECT k.category_id AS category_id, h.heat_index AS heat_index"
        "  FROM fact_search_heat h JOIN dim_keyword k ON k.keyword_id = h.keyword_id"
        "  WHERE h.stat_date BETWEEN ? AND ?"
        ") GROUP BY category_id",
        [start, end],
    ).fetchall()
    return {row["category_id"]: float(row["heat"] or 0.0) for row in rows}


def subcategory_ranking(conn: sqlite3.Connection, days: int = 56) -> list[dict]:
    start, end = window(conn, days)
    heat = demand_heat(conn)
    rows = conn.execute(
        "SELECT m.category_id, m.product_id, SUM(m.sps_mid) AS sps, SUM(m.gms_mid) AS gms,"
        "       AVG(m.confidence) AS confidence"
        " FROM fact_metric_daily m WHERE m.stat_date BETWEEN ? AND ?"
        " GROUP BY m.category_id, m.product_id",
        [start, end],
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["category_id"], []).append(row)

    names = {c["category_id"]: c["name"] for c in list_categories(conn)}
    result = []
    for category_id, members in grouped.items():
        values = [float(m["sps"] or 0.0) for m in members]
        _, cr5, hhi = _shares(values)
        total_sps = sum(values)
        heat_value = heat.get(category_id, 0.0)
        listing_count = len(members)
        gap_score = (heat_value / listing_count) if listing_count else 0.0
        result.append({
            "category_id": category_id,
            "name": names.get(category_id, category_id),
            "total_sps": round(total_sps, 1),
            "total_gms": round(sum(float(m["gms"] or 0.0) for m in members), 2),
            "listing_count": listing_count,
            "cr5": round(cr5, 3),
            "hhi": round(hhi, 4),
            "avg_confidence": round(sum(float(m["confidence"] or 0.0) for m in members) / len(members), 3),
            "heat_index": round(heat_value, 1),
            "gap_score": round(gap_score, 2),
        })

    # 供需缺口归一化到 0-100
    if result:
        max_gap = max(item["gap_score"] for item in result) or 1.0
        for item in result:
            item["gap_index"] = round(item["gap_score"] / max_gap * 100, 1)
            item.pop("gap_score")
    return sorted(result, key=lambda item: item["total_sps"], reverse=True)


def product_ranking(conn: sqlite3.Connection, category_id: str | None = None,
                    keyword: str | None = None, sort: str = "sps", limit: int = 30,
                    days: int = 56) -> list[dict]:
    start, end = window(conn, days)
    params: list = [start, end]
    filters = ""
    if category_id:
        filters += " AND m.category_id = ?"
        params.append(category_id)
    if keyword:
        filters += " AND (p.title LIKE ? OR p.brand LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    rows = conn.execute(
        "SELECT p.product_id, p.title, p.brand, p.category_id, p.platform_id, pl.name AS platform_name,"
        "       SUM(m.sps_mid) AS sps, SUM(m.gms_mid) AS gms, AVG(m.confidence) AS confidence,"
        "       AVG(COALESCE(s.promo_price, s.price)) AS price,"
        "       (SELECT cluster_id FROM dim_product_cluster_map cm WHERE cm.product_id = p.product_id) AS cluster_id"
        " FROM fact_metric_daily m"
        " JOIN dim_product p ON p.product_id = m.product_id"
        " JOIN dim_platform pl ON pl.platform_id = p.platform_id"
        " LEFT JOIN (SELECT product_id, AVG(price) AS price, AVG(promo_price) AS promo_price"
        "            FROM fact_signal_daily GROUP BY product_id) s ON s.product_id = p.product_id"
        " WHERE m.stat_date BETWEEN ? AND ?" + filters +
        " GROUP BY p.product_id",
        params,
    ).fetchall()

    mid = _as_date(end) - timedelta(days=max(days // 2 - 1, 1))
    recent_rows = conn.execute(
        "SELECT product_id, SUM(sps_mid) AS sps FROM fact_metric_daily"
        " WHERE stat_date > ? AND stat_date <= ? GROUP BY product_id",
        [mid.isoformat(), end],
    ).fetchall()
    prev_rows = conn.execute(
        "SELECT product_id, SUM(sps_mid) AS sps FROM fact_metric_daily"
        " WHERE stat_date >= ? AND stat_date <= ? GROUP BY product_id",
        [start, mid.isoformat()],
    ).fetchall()
    recent_map = {r["product_id"]: float(r["sps"] or 0.0) for r in recent_rows}
    prev_map = {r["product_id"]: float(r["sps"] or 0.0) for r in prev_rows}

    result = []
    for row in rows:
        product_id = row["product_id"]
        recent, previous = recent_map.get(product_id, 0.0), prev_map.get(product_id, 0.0)
        growth = ((recent - previous) / previous) if previous > 0 else 0.0
        item = dict(row)
        item["sps"] = round(float(item["sps"] or 0.0), 1)
        item["gms"] = round(float(item["gms"] or 0.0), 2)
        item["confidence"] = round(float(item["confidence"] or 0.0), 3)
        item["price"] = round(float(item["price"] or 0.0), 2)
        item["growth"] = round(growth, 4)
        result.append(item)

    key_map = {
        "sps": lambda i: i["sps"],
        "gms": lambda i: i["gms"],
        "growth": lambda i: i["growth"],
        "price": lambda i: i["price"],
        "confidence": lambda i: i["confidence"],
    }
    result.sort(key=key_map.get(sort, key_map["sps"]), reverse=True)
    return result[:limit]


def product_detail(conn: sqlite3.Connection, product_id: str) -> dict | None:
    row = conn.execute(
        "SELECT p.*, pl.name AS platform_name FROM dim_product p"
        " JOIN dim_platform pl ON pl.platform_id = p.platform_id WHERE p.product_id = ?",
        [product_id],
    ).fetchone()
    if not row:
        return None

    product = dict(row)
    product["attrs"] = json.loads(product.pop("attrs_json") or "{}")

    series = conn.execute(
        "SELECT stat_date, sps_low, sps_mid, sps_high, gms_mid, confidence, evidence_json"
        " FROM fact_metric_daily WHERE product_id = ? ORDER BY stat_date",
        [product_id],
    ).fetchall()
    product["series"] = [dict(item) for item in series]
    if product["series"]:
        product["evidence"] = json.loads(product["series"][-1]["evidence_json"])
    else:
        product["evidence"] = {}

    review = conn.execute(
        "SELECT review_cnt, sentiment_pos, sentiment_neg, top_keywords_json"
        " FROM fact_review_agg WHERE product_id = ?", [product_id],
    ).fetchone()
    if review:
        product["review"] = {
            "review_cnt": review["review_cnt"],
            "sentiment_pos": review["sentiment_pos"],
            "sentiment_neg": review["sentiment_neg"],
            "keywords": json.loads(review["top_keywords_json"] or "[]"),
        }
    else:
        product["review"] = None

    cluster = conn.execute(
        "SELECT m.cluster_id, m.match_score, m.match_reason, c.canonical_title"
        " FROM dim_product_cluster_map m JOIN dim_product_cluster c ON c.cluster_id = m.cluster_id"
        " WHERE m.product_id = ?", [product_id],
    ).fetchone()
    product["cluster"] = dict(cluster) if cluster else None

    if cluster:
        competitors = conn.execute(
            "SELECT p.product_id, p.title, pl.name AS platform_name, m.match_score, m.match_reason,"
            "       (SELECT SUM(sps_mid) FROM fact_metric_daily f WHERE f.product_id = p.product_id) AS sps,"
            "       (SELECT AVG(COALESCE(promo_price, price)) FROM fact_signal_daily s"
            "        WHERE s.product_id = p.product_id) AS price"
            " FROM dim_product_cluster_map m"
            " JOIN dim_product p ON p.product_id = m.product_id"
            " JOIN dim_platform pl ON pl.platform_id = p.platform_id"
            " WHERE m.cluster_id = ? ORDER BY sps DESC",
            [cluster["cluster_id"]],
        ).fetchall()
        product["competitors"] = [
            {**dict(item), "sps": round(float(item["sps"] or 0.0), 1),
             "price": round(float(item["price"] or 0.0), 2)}
            for item in competitors
        ]
    else:
        product["competitors"] = []

    return product


def audit_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT log_id, source, url, fetched_at, robots_allowed, fields, records, batch_id"
        " FROM audit_collect_log ORDER BY log_id DESC LIMIT ?", [limit],
    ).fetchall()
    return [dict(row) for row in rows]


def cluster_list(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT c.cluster_id, c.canonical_title, c.category_id, COUNT(m.product_id) AS listing_count"
        " FROM dim_product_cluster c JOIN dim_product_cluster_map m ON m.cluster_id = c.cluster_id"
        " GROUP BY c.cluster_id HAVING listing_count > 1"
        " ORDER BY listing_count DESC, c.cluster_id LIMIT ?", [limit],
    ).fetchall()
    return [dict(row) for row in rows]
