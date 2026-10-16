"""ETL 流水线：原始层 → 维度/事实层 → 指标层。

等价于设计文档中的 F2 数据治理与商品对齐 + F3 指标计算部分。
所有步骤幂等，可反复执行。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "marketcompass.db"
SCHEMA_PATH = PROJECT_ROOT / "infra" / "sql" / "schema.sql"

# SPS 融合权重：累计已售增量 / 评价反推 / 榜单分位反推
W_SOLD, W_REVIEW, W_RANK = 0.58, 0.24, 0.18

# 公开页面通常不提供"已售件数"增量，此时按评价存量做量级估计所需的假设窗口
STOCK_WINDOW_DAYS = 90

# 各数据源的审计元信息（url 与字段范围）
SOURCE_META = {
    "seed": {
        "url": "local://seed_simulator",
        "fields": "sold_cumulative,review_cumulative,rank,price,promo_price",
        "label": "演示用模拟数据源",
    },
    "suning": {
        "url": "https://search.suning.com/<关键词>/",
        "fields": "sku,title,sell_point,review_count,shop_type,rank",
        "label": "苏宁易购公开搜索结果页",
    },
}

# 注意：audit_collect_log **不在此列** —— 审计台账必须跨 bootstrap 保留。
# 否则「每次采集都可追溯」的承诺会被下一次重建抹掉，真实源的采集历史将永久丢失。
TABLES = [
    "fact_metric_daily", "fact_review_agg", "fact_search_heat", "fact_signal_daily",
    "dim_product_cluster_map", "dim_product_cluster", "dim_product", "dim_category",
    "dim_platform", "dim_keyword", "ai_claim",
]


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：为已存在的旧库补齐后加的列。"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(dim_category)")}
    if "aliases_json" not in columns:
        conn.execute("ALTER TABLE dim_category ADD COLUMN aliases_json TEXT")

    signal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(fact_signal_daily)")}
    if "sales_semantics" not in signal_columns:
        conn.execute("ALTER TABLE fact_signal_daily ADD COLUMN sales_semantics TEXT")


def reset_db(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def discover_sources() -> list[str]:
    """自动发现 data/raw 下所有可用的数据源目录（含 listings.jsonl 即为一个源）。"""
    if not RAW_ROOT.exists():
        return []
    return sorted(
        path.name for path in RAW_ROOT.iterdir()
        if path.is_dir() and (path / "listings.jsonl").exists()
    )


def _read_jsonl(name: str, sources: list[str] | None = None) -> list[dict]:
    """合并读取多个数据源的原始层文件。"""
    rows: list[dict] = []
    for source in (sources if sources is not None else discover_sources()):
        path = RAW_ROOT / source / name
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


# ---------------------------------------------------------------------------
# 维度与原始事实入库
# ---------------------------------------------------------------------------
def load_dimensions(conn: sqlite3.Connection, sources: list[str]) -> dict[str, int]:
    platforms = _read_jsonl("platforms.jsonl", sources)
    categories = _read_jsonl("categories.jsonl", sources)
    listings = _read_jsonl("listings.jsonl", sources)

    conn.executemany(
        "INSERT OR REPLACE INTO dim_platform(platform_id, name, source_type, compliance_note)"
        " VALUES (?,?,?,?)",
        [(p["platform_id"], p["name"], p["source_type"], p["compliance_note"]) for p in platforms],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO dim_category"
        "(category_id, parent_id, name, level, aliases_json) VALUES (?,?,?,?,?)",
        [(c["category_id"], c.get("parent_id"), c["name"], c["level"],
          json.dumps(c.get("aliases", []), ensure_ascii=False)) for c in categories],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO dim_product"
        "(product_id, platform_id, title, brand, category_id, attrs_json, url, first_seen)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(
            item["product_id"], item["platform_id"], item["title"], item["brand"],
            item["category_id"], json.dumps(item.get("attrs", {}), ensure_ascii=False),
            item.get("url"), item.get("first_seen"),
        ) for item in listings],
    )
    conn.commit()
    return {"platforms": len(platforms), "categories": len(categories), "products": len(listings)}


def load_signals(conn: sqlite3.Connection, batch_id: str, sources: list[str]) -> int:
    rows = _read_jsonl("signals.jsonl", sources)
    conn.executemany(
        "INSERT OR REPLACE INTO fact_signal_daily"
        "(product_id, stat_date, sold_cumulative, sales_semantics, review_cumulative,"
        " rank, list_size, price, promo_price, platform_id, batch_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(
            r["product_id"], r["stat_date"], r["sold_cumulative"], r.get("sales_semantics"),
            r["review_cumulative"], r["rank"], r["list_size"], r["price"],
            r.get("promo_price"), r["platform_id"], batch_id,
        ) for r in rows],
    )
    conn.commit()
    return len(rows)


def load_reviews_and_heat(conn: sqlite3.Connection, sources: list[str]) -> dict[str, int]:
    reviews = _read_jsonl("reviews.jsonl", sources)
    conn.executemany(
        "INSERT OR REPLACE INTO fact_review_agg"
        "(product_id, review_cnt, sentiment_pos, sentiment_neg, top_keywords_json)"
        " VALUES (?,?,?,?,?)",
        [(
            r["product_id"], r["review_cnt"], r.get("sentiment_pos"), r.get("sentiment_neg"),
            json.dumps(r.get("top_keywords", []), ensure_ascii=False),
        ) for r in reviews],
    )

    heat = _read_jsonl("search_heat.jsonl", sources)
    conn.executemany(
        "INSERT OR REPLACE INTO fact_search_heat(keyword_id, stat_date, heat_index, source)"
        " VALUES (?,?,?,?)",
        [(h["keyword_id"], h["stat_date"], h["heat_index"], h.get("source")) for h in heat],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO dim_keyword(keyword_id, text, category_id, source) VALUES (?,?,?,?)",
        [(f"kw_{s['category_id']}", s["name"], s["category_id"], "public_search_index")
         for s in _read_jsonl("categories.jsonl", sources) if s["level"] == 2],
    )
    conn.commit()
    return {"reviews": len(reviews), "search_heat": len(heat)}


def write_audit(conn: sqlite3.Connection, source: str, url: str, fields: str,
                records: int, batch_id: str, robots_allowed: int = 1) -> None:
    """写入采集审计。

    审计台账跨 bootstrap 保留（不在 TABLES 重置清单里），因此这里的策略是：
    - 真实数据源（suning / openapi_*）每次追加，形成可追溯的采集历史 —— 这正是审计的意义；
    - 演示数据源（seed）每次重建都会重新生成，若也追加会迅速堆满噪声，故只保留最新一条。
    """
    if source == "seed":
        conn.execute("DELETE FROM audit_collect_log WHERE source = ?", [source])
    conn.execute(
        "INSERT INTO audit_collect_log(source, url, fetched_at, robots_allowed, fields, records, batch_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (source, url, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         robots_allowed, fields, records, batch_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 跨平台同款对齐
# ---------------------------------------------------------------------------
def _char_jaccard(left: str, right: str) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def align_clusters(conn: sqlite3.Connection) -> dict[str, int]:
    """基于品牌 + 规格 + 材质 + 标题相似度识别跨平台同款，输出可解释的匹配依据。"""
    products = conn.execute(
        "SELECT product_id, title, brand, category_id, platform_id, attrs_json FROM dim_product"
    ).fetchall()

    groups: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in products:
        attrs = json.loads(row["attrs_json"] or "{}")
        key = (row["category_id"], row["brand"], attrs.get("规格"), attrs.get("材质"))
        groups[key].append(row)

    conn.execute("DELETE FROM dim_product_cluster")
    conn.execute("DELETE FROM dim_product_cluster_map")

    multi_platform = 0
    for key, members in groups.items():
        digest = hashlib.md5("|".join(str(part) for part in key).encode("utf-8")).hexdigest()[:8]
        cluster_id = f"cl_{digest}"
        category_id, brand, spec, material = key
        conn.execute(
            "INSERT OR REPLACE INTO dim_product_cluster(cluster_id, canonical_title, category_id)"
            " VALUES (?,?,?)",
            (cluster_id, f"{brand}{spec}{material}", category_id),
        )
        platform_ids = {m["platform_id"] for m in members}
        if len(platform_ids) > 1:
            multi_platform += 1

        base = members[0]
        for member in members:
            score = 0.55 + 0.45 * _char_jaccard(base["title"], member["title"])
            reason = (f"品牌一致[{brand}]|规格一致[{spec}]|材质一致[{material}]|"
                      f"标题相似度={_char_jaccard(base['title'], member['title']):.2f}")
            conn.execute(
                "INSERT OR REPLACE INTO dim_product_cluster_map"
                "(cluster_id, product_id, match_score, match_reason) VALUES (?,?,?,?)",
                (cluster_id, member["product_id"], round(score, 3), reason),
            )
    conn.commit()
    return {"clusters": len(groups), "multi_platform_clusters": multi_platform}


# ---------------------------------------------------------------------------
# 指标计算：销量代理指标 SPS
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_metrics(conn: sqlite3.Connection) -> int:
    """公开数据无法获得平台真实销量，因此输出可校准的销量代理指标（SPS）+ 置信区间。"""
    conn.execute("DELETE FROM fact_metric_daily")

    rows = conn.execute(
        "SELECT s.product_id, s.stat_date, s.sold_cumulative, s.sales_semantics,"
        "       s.review_cumulative, s.rank, s.list_size, s.price, s.promo_price,"
        "       p.category_id, s.platform_id"
        " FROM fact_signal_daily s JOIN dim_product p ON p.product_id = s.product_id"
        " ORDER BY s.product_id, s.stat_date"
    ).fetchall()

    series: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        series[row["product_id"]].append(row)

    deltas: dict[str, list[tuple[sqlite3.Row, float, float]]] = {}
    cat_daily_total: dict[tuple[str, str], float] = defaultdict(float)
    cat_sold_total: dict[str, float] = defaultdict(float)
    cat_review_total: dict[str, float] = defaultdict(float)

    for product_id, items in series.items():
        computed = []
        prev_sold = prev_review = None
        for item in items:
            sold_value = item["sold_cumulative"]
            review_value = item["review_cumulative"]
            semantics = item["sales_semantics"]

            # rolling_30d 是"滚动窗口销量"，不同日期之间相减没有意义，不能当累计值算增量
            if sold_value is None or semantics == "rolling_30d":
                delta_sold = None
            elif prev_sold is None:
                delta_sold = max(float(sold_value), 0.0)
            else:
                delta_sold = max(float(sold_value) - float(prev_sold), 0.0)

            if review_value is None:
                delta_review = None
            elif prev_review is None:
                delta_review = max(float(review_value), 0.0)
            else:
                delta_review = max(float(review_value) - float(prev_review), 0.0)

            if sold_value is not None:
                prev_sold = sold_value
            if review_value is not None:
                prev_review = review_value

            computed.append((item, delta_sold, delta_review))
            cat_daily_total[(item["category_id"], item["stat_date"])] += delta_sold or 0.0
            cat_sold_total[item["category_id"]] += delta_sold or 0.0
            cat_review_total[item["category_id"]] += delta_review or 0.0
        deltas[product_id] = computed

    # 类目级评论转化率（避免使用任何内部真值，只用公开信号反推）
    comment_rate = {}
    for category_id, sold_sum in cat_sold_total.items():
        rate = cat_review_total[category_id] / sold_sum if sold_sum > 0 else 0.03
        comment_rate[category_id] = _clamp(rate, 0.004, 0.2)

    # 同款簇覆盖的平台数 → 作为置信度因子
    cluster_coverage: dict[str, int] = {}
    for row in conn.execute(
        "SELECT m.product_id AS product_id, c.cnt AS listing_cnt"
        " FROM dim_product_cluster_map m"
        " JOIN (SELECT cluster_id, COUNT(*) AS cnt FROM dim_product_cluster_map GROUP BY cluster_id) c"
        "   ON c.cluster_id = m.cluster_id"
    ):
        cluster_coverage[row["product_id"]] = row["listing_cnt"]

    payload = []
    for product_id, computed in deltas.items():
        window: list[float] = []
        for index, (item, delta_sold, delta_review) in enumerate(computed):
            category_id = item["category_id"]
            rate = comment_rate[category_id]

            list_size = max(int(item["list_size"] or 1), 1)
            rank = int(item["rank"] or list_size)
            harmonic = sum(1.0 / i for i in range(1, list_size + 1))
            rank_share = (1.0 / rank) / harmonic if harmonic > 0 else 0.0
            cat_total = cat_daily_total[(category_id, item["stat_date"])]
            rank_implied = cat_total * rank_share * list_size * 0.35

            semantics = item["sales_semantics"]
            sold_value = item["sold_cumulative"]
            if delta_sold is None:
                if semantics == "rolling_30d" and sold_value:
                    # 官方开放平台直接返回销量 → 直接作为规模值，不做任何推算
                    sps_mid = float(sold_value)
                    mode = "api_volume_direct"
                    basis = (f"官方 API 直接返回的滚动窗口销量 {float(sold_value):.0f}，"
                             f"直接作为规模值（不参与增量推算）")
                    completeness = 1.0
                    if item["review_cumulative"] is None:
                        completeness -= 0.2
                    if item["rank"] is None:
                        completeness -= 0.2
                    confidence_cap = 0.85
                    window_value = 0.0
                else:
                    # 该数据源只提供评价等公开信号，没有"已售件数"增量
                    review_stock = float(item["review_cumulative"] or 0.0)
                    if index == 0:
                        # 单日快照：没有历史可比，只能给量级估计，置信度上限压到 0.46
                        mode = "single_snapshot_stock_basis"
                        sps_mid = (review_stock / rate) / STOCK_WINDOW_DAYS if rate > 0 else 0.0
                        basis = (f"无已售信号：评价存量 {review_stock:.0f} ÷ 类目评价转化率 {rate:.4f}"
                                 f" ÷ 假设累积窗口 {STOCK_WINDOW_DAYS} 天")
                        confidence_cap = 0.46
                        completeness = 0.66 if item["review_cumulative"] is not None else 0.33
                    elif (delta_review or 0.0) > 0:
                        mode = "review_increment_basis"
                        sps_mid = (delta_review / rate) if rate > 0 else 0.0
                        basis = f"无已售信号：评价增量 {delta_review:.0f} ÷ 转化率 {rate:.4f}"
                        confidence_cap = 0.46
                        completeness = 0.66
                    else:
                        # 增量本期为 0：公开页评价数是缓存展示值（如 "9000+"），日内不更新。
                        # 不编造增量，退化为存量估计并进一步压低置信度。
                        mode = "review_increment_stale_stock_fallback"
                        sps_mid = (review_stock / rate) / STOCK_WINDOW_DAYS if rate > 0 else 0.0
                        basis = (f"评价增量本期为 0（公开页评价数为缓存展示值），退化为存量估计："
                                 f"评价存量 {review_stock:.0f} ÷ 转化率 {rate:.4f}"
                                 f" ÷ 假设窗口 {STOCK_WINDOW_DAYS} 天")
                        confidence_cap = 0.40
                        completeness = 0.50
                    window_value = 0.0
            else:
                review_implied = ((delta_review or 0.0) / rate) if rate > 0 else 0.0
                sps_mid = W_SOLD * delta_sold + W_REVIEW * review_implied + W_RANK * rank_implied
                mode = "full_signal"
                basis = "已售增量 + 评价增量反推 + 榜单分位反推"
                completeness = 1.0
                if item["review_cumulative"] is None:
                    completeness -= 0.33
                if item["rank"] is None:
                    completeness -= 0.33
                confidence_cap = 0.96
                window_value = delta_sold

            window.append(window_value)
            recent = window[-7:]
            mean = sum(recent) / len(recent) if recent else 0.0
            if mean > 0 and len(recent) > 1:
                var = sum((value - mean) ** 2 for value in recent) / len(recent)
                cv = (var ** 0.5) / mean
            else:
                cv = 0.6
            stability = 1.0 / (1.0 + cv)

            coverage = {1: 0.85, 2: 0.93}.get(cluster_coverage.get(product_id, 1), 1.0)
            if item["promo_price"]:
                coverage *= 0.93  # 促销日价格扰动，量价关系不稳

            confidence = _clamp(
                0.36 * completeness + 0.36 * stability + 0.28 * coverage,
                0.30, confidence_cap,
            )

            margin = _clamp(0.55 - 0.42 * confidence, 0.10, 0.45)
            effective_price = float(item["promo_price"] or item["price"] or 0.0)

            evidence = {
                "mode": mode,
                "basis": basis,
                "sales_semantics": semantics,
                "signals": {
                    "delta_sold_visible": round(delta_sold, 2) if delta_sold is not None else None,
                    "delta_review_visible": round(delta_review, 2) if delta_review is not None else None,
                    "review_cumulative_visible": item["review_cumulative"],
                    "rank": rank,
                    "rank_list_size": list_size,
                    "price": item["price"],
                    "promo_price": item["promo_price"],
                },
                "weights": {"sold": W_SOLD, "review": W_REVIEW, "rank": W_RANK},
                "category_comment_rate": round(rate, 4),
                "stability": round(stability, 3),
                "platform_coverage": cluster_coverage.get(product_id, 1),
                "platform": item["platform_id"] if "platform_id" in item.keys() else None,
                "period": item["stat_date"],
            }

            payload.append((
                product_id, item["stat_date"], category_id,
                round(sps_mid * (1 - margin), 2), round(sps_mid, 2), round(sps_mid * (1 + margin), 2),
                round(sps_mid * effective_price, 2), round(confidence, 3),
                json.dumps(evidence, ensure_ascii=False),
            ))

    conn.executemany(
        "INSERT OR REPLACE INTO fact_metric_daily"
        "(product_id, stat_date, category_id, sps_low, sps_mid, sps_high, gms_mid, confidence, evidence_json)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return len(payload)


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def run_all(verbose: bool = True, sources: list[str] | None = None) -> dict:
    sources = sources if sources is not None else discover_sources()
    batch_id = "batch_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    conn = connect()
    try:
        init_db(conn)
        reset_db(conn)
        dims = load_dimensions(conn, sources)
        signal_count = load_signals(conn, batch_id, sources)
        aux = load_reviews_and_heat(conn, sources)
        clusters = align_clusters(conn)
        metric_count = compute_metrics(conn)

        for source in sources:
            meta = SOURCE_META.get(source, {})
            write_audit(
                conn, source, meta.get("url", f"source://{source}"),
                meta.get("fields", ""), len(_read_jsonl("signals.jsonl", [source])), batch_id,
            )

        modes = {
            row["mode"]: row["cnt"] for row in conn.execute(
                "SELECT json_extract(evidence_json, '$.mode') AS mode, COUNT(*) AS cnt"
                " FROM fact_metric_daily GROUP BY mode"
            )
        }
        result = {
            "batch_id": batch_id,
            "sources": sources,
            "dimensions": dims,
            "signals": signal_count,
            "aux": aux,
            "clusters": clusters,
            "metrics": metric_count,
            "metric_modes": modes,
        }
        if verbose:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run_all()
