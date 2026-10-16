"""AI 决策参谋（F4）：检索 → 生成建议 → 证据链校验。

设计原则（对应设计文档第 5 章）：
1. 所有数字只能来自指标层（`services/analytics/queries.py`），模型不造数；
2. 每条建议绑定 evidence（指标 / 数值 / 周期 / 来源 / 置信度）；
3. 生成后由校验器**重算**指标并逐条比对，不通过则降级为"数据不足"；
4. 未配置 LLM 时走离线模板，配置后自动切换（见 llm_provider.py）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from services.ai.llm_provider import get_provider
from services.analytics import market_analysis, queries
from services.etl.pipeline import STOCK_WINDOW_DAYS

DAYS = 56

KNOWLEDGE_BASE = [
    {
        "id": "kb_price_band",
        "keywords": ["收纳", "家居"],
        "title": "家居收纳品类价格带经验区间",
        "text": "该类目以 30-100 元为主力成交带，百元以上需要强差异化卖点（材质升级、套装组合）支撑。",
        "source": "industry_public_knowledge:家居收纳品类观察",
    },
    {
        "id": "kb_concentration",
        "keywords": ["*"],
        "title": "集中度判读规则",
        "text": "CR5 高于 0.60 视为头部集中，新进入者应避开头部正面价格带；HHI 高于 0.15 视为高度集中。",
        "source": "metric_rule:concentration_threshold",
    },
    {
        "id": "kb_gap",
        "keywords": ["*"],
        "title": "供需缺口判读规则",
        "text": "供需缺口指数高于 70 表示需求热度相对在售商品数偏高，属于潜在蓝海细分，但需复核是否由低质供给造成。",
        "source": "metric_rule:demand_gap_threshold",
    },
    {
        "id": "kb_sentiment",
        "keywords": ["*"],
        "title": "评价情感判读规则",
        "text": "正面情感占比低于 0.80 说明该商品存在未被满足的痛点，可作为差异化切入点。",
        "source": "metric_rule:sentiment_threshold",
    },
    {
        "id": "kb_trend",
        "keywords": ["*"],
        "title": "走势判读规则",
        "text": "后半窗口相对前半窗口的总量变化在 ±2% 内视为持平，超过 +5% 视为明确上升通道。",
        "source": "metric_rule:trend_threshold",
    },
    {
        "id": "kb_pain",
        "keywords": ["*"],
        "title": "痛点切入规则",
        "text": "评价负面关键词占比高于 30% 说明该类目供给质量普遍不足，改良式产品有切入空间；低于 15% 则说明成熟度高，需靠价格或渠道竞争。",
        "source": "metric_rule:pain_point_threshold",
    },
    {
        "id": "kb_compliance",
        "keywords": ["*"],
        "title": "数据合规基线",
        "text": "所有指标仅由公开可访问数据推导，不采集个人信息、不绕过平台风控，报告中须标注数据口径与局限性。",
        "source": "compliance:project_baseline",
    },
]


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
def retrieve_knowledge(category_name: str, limit: int = 3) -> list[dict]:
    hits = []
    for entry in KNOWLEDGE_BASE:
        if "*" in entry["keywords"] or any(word in category_name for word in entry["keywords"]):
            hits.append(entry)
    return hits[:limit]


# ---------------------------------------------------------------------------
# 证据链校验
# ---------------------------------------------------------------------------
def metric_modes(conn: sqlite3.Connection, category_id: str | None = None) -> dict[str, int]:
    """统计指标的数据口径分布（full_signal / single_snapshot_stock_basis / ...）。"""
    sql = ("SELECT json_extract(evidence_json, '$.mode') AS mode, COUNT(*) AS cnt"
           " FROM fact_metric_daily")
    params: list = []
    if category_id:
        sql += " WHERE category_id = ?"
        params.append(category_id)
    sql += " GROUP BY mode"
    return {row["mode"] or "unknown": row["cnt"] for row in conn.execute(sql, params)}


def source_mix_note(modes: dict[str, int]) -> str | None:
    """混合数据源提醒：完整信号与单日快照口径不同，不能直接横向比较。"""
    if "full_signal" in modes and len(modes) > 1:
        parts = "、".join(f"{key}×{value}" for key, value in sorted(modes.items()))
        return f"当前为混合数据源（{parts}）：不同来源口径不同，横向比较需谨慎。"
    return None


def _metric_value(conn: sqlite3.Connection, metric: str) -> float | None:
    """按指标名重算数值，用于校验 AI 输出中的引用是否与指标层一致。"""
    if metric.startswith("overview."):
        field = metric.split(".", 1)[1]
        return queries.overview(conn, days=DAYS).get(field)

    if metric.startswith("subcategory."):
        field, category_id = metric.split(".", 1)[1].split(":", 1)
        for item in queries.subcategory_ranking(conn, days=DAYS):
            if item["category_id"] == category_id:
                return item.get(field)
        return None

    if metric.startswith("band."):
        field, band = metric.split(".", 1)[1].split(":", 1)
        for item in queries.price_bands(conn, days=DAYS):
            if item["band"] == band:
                return item.get(field)
        return None

    if metric.startswith("market."):
        field, category_id = metric.split(".", 1)[1].split(":", 1)
        snapshot = market_analysis.market_snapshot(conn, category_id, DAYS)
        return snapshot.get(field)

    if metric.startswith("brand.share:"):
        _, category_id, brand = metric.split(":", 2)
        snapshot = market_analysis.market_snapshot(conn, category_id, DAYS)
        for item in snapshot["brand_shares"]:
            if item["brand"] == brand:
                return item["share"]
        return None

    if metric.startswith("product."):
        field, product_id = metric.split(".", 1)[1].split(":", 1)
        start, end = queries.window(conn, DAYS)
        row = conn.execute(
            "SELECT SUM(sps_mid) AS sps, AVG(confidence) AS confidence"
            " FROM fact_metric_daily WHERE product_id = ? AND stat_date BETWEEN ? AND ?",
            [product_id, start, end],
        ).fetchone()
        if field == "sps":
            return round(float(row["sps"] or 0.0), 1)
        if field == "confidence":
            return round(float(row["confidence"] or 0.0), 3)
        return None

    return None


def verify_evidence(conn: sqlite3.Connection, evidence: list[dict]) -> dict:
    """逐条重算比对。返回 {"passed": bool, "checked": [...], "failed": [...]}"""
    checked, failed = [], []
    for item in evidence:
        metric = item.get("metric", "")
        claimed = item.get("value")
        actual = _metric_value(conn, metric)
        if actual is None:
            failed.append({**item, "reason": "指标层无法复现该指标"})
            continue
        tolerance = max(abs(float(claimed)) * 0.005, 0.01) if claimed is not None else 0.01
        ok = claimed is not None and abs(float(actual) - float(claimed)) <= tolerance
        record = {
            "metric": metric, "claimed": claimed, "recomputed": actual,
            "match": bool(ok), "source": item.get("source"),
        }
        checked.append(record)
        if not ok:
            failed.append({**record, "reason": "重算值与引用值不一致"})
    passed = bool(evidence) and not failed
    return {"passed": passed, "checked": checked, "failed": failed}


# ---------------------------------------------------------------------------
# 生成建议
# ---------------------------------------------------------------------------
def _evidence(metric: str, value, period: list[str], source: str, confidence: float,
              note: str = "") -> dict:
    return {
        "metric": metric,
        "value": value,
        "period": f"{period[0]}~{period[1]}",
        "source": source,
        "confidence": round(float(confidence), 3),
        "note": note,
    }


def _candidate_score(item: dict) -> float:
    sps = max(item["sps"], 0.0) ** 0.5
    growth_factor = 1.0 + max(min(item["growth"], 1.0), -0.5)
    return sps * growth_factor * item["confidence"]


def advise(conn: sqlite3.Connection, category_id: str | None = None, budget: float = 150.0,
           risk: str = "medium", goal: str = "选品") -> dict:
    overview = queries.overview(conn, category_id=category_id, days=DAYS)
    period = overview["period"]
    categories = {c["category_id"]: c["name"] for c in queries.list_categories(conn)
                  if c["level"] == 2}
    ranking = queries.subcategory_ranking(conn, days=DAYS)
    if category_id:
        ranking = [item for item in ranking if item["category_id"] == category_id]
    bands = queries.price_bands(conn, category_id=category_id, days=DAYS)
    products = queries.product_ranking(conn, category_id=category_id, limit=200, days=DAYS)

    source_label = "metric_layer:fact_metric_daily"
    category_name = categories.get(category_id) if category_id else "全部类目"

    # 判定数据口径：是否只有"单日快照存量"模式（真实公开页面接入初期的常态）
    modes = metric_modes(conn, category_id)
    stock_only = bool(modes) and "full_signal" not in modes
    period_label = "统计窗口内"

    evidence: list[dict] = [
        _evidence("overview.total_sps", overview["total_sps"], period, source_label,
                  overview["avg_confidence"], f"{period_label}销量代理总量（件当量）"),
        _evidence("overview.growth", overview["growth"], period, source_label,
                  overview["avg_confidence"], "后半窗口相对前半窗口的总量变化"),
        _evidence("overview.cr5", overview["cr5"], period, source_label,
                  overview["avg_confidence"], "Top5 商品销量代理占比"),
        _evidence("overview.hhi", overview["hhi"], period, source_label,
                  overview["avg_confidence"], "竞争结构赫芬达尔指数"),
    ]

    # 主力价格带
    valid_bands = [b for b in bands if b["sps"] > 0]
    main_band = max(valid_bands, key=lambda b: b["sps"]) if valid_bands else None
    if main_band:
        evidence.append(_evidence(
            f"band.sps_share:{main_band['band']}", main_band["sps_share"], period, source_label,
            overview["avg_confidence"], f"价格带 {main_band['band']} 元的销量代理占比",
        ))

    # 蓝海子类目
    gap_leader = max(ranking, key=lambda item: item.get("gap_index", 0)) if ranking else None
    if gap_leader:
        evidence.append(_evidence(
            f"subcategory.gap_index:{gap_leader['category_id']}", gap_leader["gap_index"],
            period, source_label, gap_leader["avg_confidence"], "供需缺口指数（0-100）",
        ))

    # 候选品
    candidates = [item for item in products
                  if item["price"] <= budget and item["confidence"] >= 0.55]
    candidates.sort(key=_candidate_score, reverse=True)
    top_candidates = candidates[:3]
    for item in top_candidates:
        evidence.append(_evidence(
            f"product.sps:{item['product_id']}", item["sps"], period, source_label,
            item["confidence"], f"候选品 {item['title'][:28]} 的销量代理总量",
        ))

    # 结论与行动
    cr5, hhi, growth = overview["cr5"], overview["hhi"], overview["growth"]
    concentration = "高度集中" if cr5 >= 0.6 or hhi >= 0.15 else "中等分散"
    trend_word = "上升" if growth > 0.02 else ("持平" if growth > -0.02 else "下滑")

    growth_text = ("环比不可用（评价增量本期不可观测）"
                   if "review_increment_stale_stock_fallback" in modes
                   else "环比暂不可用（仅 1 天快照）" if stock_only
                   else f"环比{'增长' if growth >= 0 else '下降'} {abs(growth) * 100:.1f}%")
    summary = (f"{category_name}{period_label}销量代理总量 {overview['total_sps']:,.0f} 件当量，"
               f"{growth_text}，"
               f"竞争结构 {concentration}（CR5={cr5:.2f}、HHI={hhi:.3f}）。"
               + ("【口径提示】公开页评价数为缓存展示值，本期增量不可观测，"
                  "指标已退化为存量估计（置信度上限 0.40）。"
                  if "review_increment_stale_stock_fallback" in modes else
                  "【口径提示】当前数据来自公开页面单日快照，指标按评价存量估算，"
                  "趋势结论需累积 ≥2 天数据后才成立。" if stock_only else ""))

    conclusions = [
        f"大盘走势{trend_word}，处于{trend_word}期的类目更适合以'小批量测款'方式进入。",
    ]
    if main_band:
        conclusions.append(
            f"成交集中在 {main_band['band']} 元价格带，占销量代理的 {main_band['sps_share'] * 100:.1f}%，"
            f"是定价锚点。"
        )
    if gap_leader:
        conclusions.append(
            f"细分「{categories.get(gap_leader['category_id'], gap_leader['category_id'])}」"
            f"供需缺口指数 {gap_leader['gap_index']:.0f}，为当前相对机会最大的细分。"
        )

    actions = []
    if gap_leader:
        actions.append({
            "step": f"优先切入细分：{categories.get(gap_leader['category_id'], gap_leader['category_id'])}",
            "reason": f"该细分供需缺口指数 {gap_leader['gap_index']:.0f}，"
                      f"需求热度 {gap_leader['heat_index']:.0f} 而有效在售商品仅 {gap_leader['listing_count']} 个。",
            "evidence_metric": f"subcategory.gap_index:{gap_leader['category_id']}",
        })
    if main_band:
        actions.append({
            "step": f"定价锚定 {main_band['band']} 元区间",
            "reason": f"该价格带贡献 {main_band['sps_share'] * 100:.1f}% 的销量代理，"
                      f"客单价与转化平衡最好。",
            "evidence_metric": f"band.sps_share:{main_band['band']}",
        })
    for item in top_candidates:
        actions.append({
            "step": f"候选品测款：{item['title'][:30]}（{item['platform_name']}，约 {item['price']:.0f} 元）",
            "reason": f"销量代理 {item['sps']:,.0f}，环比 {item['growth'] * 100:+.1f}%，"
                      f"数据置信度 {item['confidence']:.2f}。",
            "evidence_metric": f"product.sps:{item['product_id']}",
        })
    if risk == "low":
        actions.append({
            "step": "首单控制在最小起订量，2 周内以点击转化率决定是否加单",
            "reason": "低风险偏好下的测款策略，避免压货。",
            "evidence_metric": "overview.growth",
        })

    risks = []
    if cr5 >= 0.6:
        risks.append(f"头部集中度偏高（CR5={cr5:.2f}），新品冷启动的流量成本可能显著高于类目均值。")
    if hhi >= 0.15:
        risks.append(f"HHI={hhi:.3f} 表明竞争结构集中，价格战风险上升。")
    low_conf = [item for item in products if item["confidence"] < 0.55]
    if low_conf:
        risks.append(f"{len(low_conf)} 个商品的数据置信度低于 0.55，其指标未纳入候选。")
    risks.append("部分商品处于促销周期，价格与销量存在短期扰动，量价关系不稳定。")
    risks.append("本报告基于公开页面采集的真实数据（单日快照口径）。" if stock_only
                 else "本报告基于演示用模拟数据生成，接入真实公开数据源后结论需重新计算。")

    limitations = [
        "SPS 为公开信号推导的销量代理指标，非平台真实销量，仅用于横向比较。",
        "仅覆盖公开渠道的公开展示字段，未包含站内广告与私域数据。",
        "评价数据仅做聚合情感与关键词统计，不含任何用户个人信息。",
        f"统计窗口 {period[0]} ~ {period[1]}。",
    ]
    if stock_only:
        limitations.insert(0, (
            "公开页评价数是缓存展示值，本期增量不可观测：指标按「评价存量 ÷ 转化率 ÷ 假设窗口 "
            f"{STOCK_WINDOW_DAYS} 天」估算，环比与趋势不可用（置信度上限 0.40）。"
            if "review_increment_stale_stock_fallback" in modes else
            "当前仅有单日公开快照：指标按「评价存量 ÷ 类目评价转化率 ÷ 假设窗口 "
            f"{STOCK_WINDOW_DAYS} 天」估算，只适合判断量级，环比与趋势暂不可用。"
        ))
    mix_note = source_mix_note(modes)
    if mix_note:
        limitations.insert(0, mix_note)

    confidence = round(overview["avg_confidence"] * 0.7 +
                       (0.25 if top_candidates else 0.0), 3)

    report = {
        "goal": goal,
        "params": {"budget": budget, "risk": risk, "goal": goal},
        "category_id": category_id,
        "category_name": category_name,
        "summary": summary,
        "conclusion": " ".join(conclusions),
        "evidence": evidence,
        "actions": actions,
        "risks": risks,
        "limitations": limitations,
        "confidence": confidence,
        "knowledge": retrieve_knowledge(category_name),
        "period": period,
    }

    # ---- 证据链校验 ----
    verification = verify_evidence(conn, evidence)
    report["verification"] = verification

    provider = get_provider()
    report["generated_by"] = provider.name

    if not verification["passed"]:
        report["degraded"] = True
        report["summary"] = "数据不足：部分引用指标无法在指标层复现，已拒绝输出结论。"
        report["conclusion"] = "请先补全数据后重试。"
        report["actions"] = []
        return report

    report["degraded"] = False

    # 已配置真实模型时，仅让它把结论润色成自然语言（不得引入新数字）
    if provider.available():
        system = ("你是电商选品分析师。只能使用用户提供的指标数值，禁止引入任何新数字，"
                  "禁止修改给定数值，输出 3 句以内的中文结论。")
        user = json.dumps({
            "summary": summary,
            "conclusion": conclusions,
            "metrics": {item["metric"]: item["value"] for item in evidence},
        }, ensure_ascii=False)
        polished = provider.complete(system, user)
        if polished:
            report["conclusion"] = polished.strip()

    _persist(conn, report)
    return report


# ---------------------------------------------------------------------------
# 自由输入商品 → 行情分析
# ---------------------------------------------------------------------------
def _brand_main_category(conn: sqlite3.Connection, brand: str) -> str | None:
    row = conn.execute(
        "SELECT p.category_id AS cid, COUNT(*) AS cnt FROM dim_product p"
        " WHERE p.brand = ? GROUP BY p.category_id ORDER BY cnt DESC LIMIT 1",
        [brand],
    ).fetchone()
    return row["cid"] if row else None


def analyze_market_query(conn: sqlite3.Connection, query: str, budget: float = 150.0,
                         risk: str = "medium", goal: str = "行情分析",
                         category_id: str | None = None) -> dict:
    """用户自由输入商品名 → 解析标的 → 罗列行情数据 → 生成行情分析并校验证据链。

    `category_id` 非空时跳过文本解析，直接分析指定标的——用于用户在候选列表里
    明确切换数据源（例如同名类目「保温杯」在演示数据与真实数据里各有一个）。
    """
    provider = get_provider()

    if category_id:
        row = conn.execute("SELECT category_id, name FROM dim_category WHERE category_id = ?",
                           [category_id]).fetchone()
        if row is None:
            return {"query": query, "matched": False,
                    "message": f"指定的标的 {category_id} 不存在",
                    "candidates": [], "generated_by": provider.name}
        resolution = {
            "query": query, "matched": True,
            "best": {"term": query, "label": row["name"], "kind": "subcategory",
                     "category_id": category_id, "score": 1.0,
                     "reason": "用户指定标的", "source_label": "指定"},
            "candidates": [],
            "message": f"按指定标的「{row['name']}」分析",
        }
    else:
        resolution = market_analysis.resolve(conn, query)

    if not resolution["matched"]:
        return {
            "query": query,
            "matched": False,
            "message": resolution["message"],
            "candidates": resolution["candidates"],
            "generated_by": provider.name,
        }

    best = resolution["best"]
    brand_focus = None
    category_id = best["category_id"]
    if best["kind"] == "brand":
        brand_focus = best["label"]
        category_id = _brand_main_category(conn, brand_focus) or category_id

    snapshot = market_analysis.market_snapshot(conn, category_id, DAYS)
    category_name = snapshot["category"]["name"]
    period = snapshot["period"]
    source = "metric_layer:fact_metric_daily"
    confidence_base = snapshot["avg_confidence"]

    # 数据口径：单日快照（真实公开页面接入初期）时指标为存量估计，置信度天然偏低
    modes = metric_modes(conn, category_id)
    stock_only = bool(modes) and "full_signal" not in modes
    min_confidence = 0.40 if stock_only else 0.55

    def make(metric: str, value, note: str, confidence: float | None = None) -> dict:
        return _evidence(metric, value, period, source,
                         confidence if confidence is not None else confidence_base, note)

    evidence = [
        make(f"market.total_sps:{category_id}", snapshot["total_sps"], "窗口内销量代理总量（件当量）"),
        make(f"market.growth:{category_id}", snapshot["growth"], "后半窗口相对前半窗口的总量变化"),
        make(f"market.cr5:{category_id}", snapshot["cr5"], "Top5 商品销量代理占比"),
        make(f"market.hhi:{category_id}", snapshot["hhi"], "竞争结构赫芬达尔指数"),
        make(f"market.negative_keyword_share:{category_id}", snapshot["negative_keyword_share"],
             "评价中负面关键词占比（痛点集中度）"),
        make(f"market.avg_confidence:{category_id}", snapshot["avg_confidence"], "全量商品平均数据置信度"),
    ]
    # 价格相关证据只在确实采到价格时才引用（公开页面价格常为异步加载而缺失）
    if snapshot["main_band"]:
        evidence.append(make(f"market.main_band_share:{category_id}", snapshot["main_band_share"],
                             f"主力价格带 {snapshot['main_band']} 元的销量代理占比"))
    if snapshot["avg_price"]:
        evidence.append(make(f"market.avg_price:{category_id}", snapshot["avg_price"],
                             "在售商品平均价格"))

    if brand_focus:
        share = next((item["share"] for item in snapshot["brand_shares"]
                      if item["brand"] == brand_focus), 0.0)
        evidence.append(make(f"brand.share:{category_id}:{brand_focus}", share,
                             f"品牌「{brand_focus}」在{category_name}的销量代理份额"))

    # 候选品：同款不同颜色/规格的 SKU 常共用标题前缀，按前缀归组，只保留组内量级最高者
    candidates: list[dict] = []
    seen_groups: set[str] = set()
    for item in snapshot["top_products"]:
        group_key = item["title"][:18]
        if group_key in seen_groups:
            continue
        if (item["price"] or budget) <= budget and item["confidence"] >= min_confidence:
            candidates.append(item)
            seen_groups.add(group_key)
        if len(candidates) >= 3:
            break
    for item in candidates:
        evidence.append(make(f"product.sps:{item['product_id']}", item["sps"],
                             f"候选品 {item['title'][:28]} 的销量代理总量", item["confidence"]))

    cr5, hhi, growth = snapshot["cr5"], snapshot["hhi"], snapshot["growth"]
    concentration = "高度集中" if (cr5 >= 0.6 or hhi >= 0.15) else "中等分散"
    trend_word = "上升" if growth > 0.02 else ("持平" if growth > -0.02 else "下滑")

    growth_text = ("环比不可用（评价增量本期不可观测）"
                   if "review_increment_stale_stock_fallback" in modes
                   else "环比暂不可用（仅 1 天快照）" if stock_only
                   else f"环比{'增长' if growth >= 0 else '下降'} {abs(growth) * 100:.1f}%")
    price_text = (f"平均价格 {snapshot['avg_price']:.0f} 元"
                  if snapshot["avg_price"] else "价格未采集（公开页面异步加载）")
    sales_text = (f"销售额估计 {snapshot['total_gms']:,.0f} 元"
                  if snapshot["avg_price"] else "销售额估计不可用（缺价格）")
    summary = (
        f"「{query}」解析为{category_name}：统计窗口内销量代理总量 "
        f"{snapshot['total_sps']:,.0f} 件当量，{sales_text}，"
        f"{growth_text}，"
        f"竞争结构{concentration}（CR5={cr5:.2f}、HHI={hhi:.3f}），"
        f"{price_text}。"
        + ("【口径提示】公开页评价数为缓存展示值，本期增量不可观测，"
           "指标已退化为存量估计（置信度上限 0.40）。"
           if "review_increment_stale_stock_fallback" in modes else
           "【口径提示】当前数据来自公开页面单日快照，指标按评价存量估算，"
           "趋势与环比需累积 ≥2 天数据后才成立。" if stock_only else "")
    )

    conclusions = [
        (f"当前仅 1 天公开快照，先看量级与结构：{snapshot['listing_count']} 个在售条目，"
         f"平均数据置信度 {snapshot['avg_confidence']:.2f}。" if stock_only else
         f"大盘处于{trend_word}通道，{snapshot['listing_count']} 个在售条目的样本量可支撑小批量测款。")
    ]
    if snapshot["main_band"]:
        conclusions.append(
            f"成交集中在 {snapshot['main_band']} 元价格带（占比 "
            f"{snapshot['main_band_share'] * 100:.1f}%），定价锚点明确。"
        )
    top_growth = [item for item in snapshot["top_growth"] if item["growth"] > 0.10]
    if top_growth:
        conclusions.append(
            f"增速最快的是「{top_growth[0]['title'][:24]}」（环比 {top_growth[0]['growth'] * 100:+.1f}%），"
            f"说明该价位段仍有新增需求。"
        )
    keywords = snapshot["keywords"]
    if keywords["negative"]:
        conclusions.append(
            f"评价痛点集中在「{'、'.join(k['keyword'] for k in keywords['negative'][:3])}」，"
            f"负面词占比 {keywords['negative_keyword_share'] * 100:.1f}%，存在改良式切入空间。"
        )

    actions = []
    if snapshot["main_band"]:
        actions.append({
            "step": f"定价锚定 {snapshot['main_band']} 元区间",
            "reason": f"该价格带贡献 {snapshot['main_band_share'] * 100:.1f}% 的销量代理，"
                      f"是类目成交最密集的位置。",
            "evidence_metric": f"market.main_band_share:{category_id}",
        })
    if keywords["negative"]:
        top_pain = keywords["negative"][0]
        actions.append({
            "step": f"以「解决{top_pain['keyword']}」为差异化卖点切入",
            "reason": f"该类目评价中「{top_pain['keyword']}」出现 {top_pain['count']} 次，"
                      f"是最高频的未被满足痛点。",
            "evidence_metric": f"market.negative_keyword_share:{category_id}",
        })
    for item in candidates:
        price_label = f"约 {item['price']:.0f} 元" if item["price"] else "价格未采集"
        short_title = item["title"][:38] + ("…" if len(item["title"]) > 38 else "")
        actions.append({
            "step": (f"对标测款：{short_title}"
                     f"（{item['platform_name']} · SKU 尾号 {item['product_id'][-4:]}，{price_label}）"),
            "reason": f"销量代理 {item['sps']:,.0f}，环比 {item['growth'] * 100:+.1f}%，"
                      f"数据置信度 {item['confidence']:.2f}。",
            "evidence_metric": f"product.sps:{item['product_id']}",
        })
    if brand_focus:
        actions.append({
            "step": f"把「{brand_focus}」作为品牌对标而非直接竞品",
            "reason": "该品牌已进入头部份额序列，正面价格竞争成本高，建议做差异化规格或套装组合。",
            "evidence_metric": f"brand.share:{category_id}:{brand_focus}",
        })
    if risk == "low":
        actions.append({
            "step": "首单按最小起订量试产，2 周看点击转化率再决定加单",
            "reason": "低风险偏好下的测款策略，控制压货。",
            "evidence_metric": f"market.growth:{category_id}",
        })

    risks = []
    if cr5 >= 0.6:
        risks.append(f"头部集中度偏高（CR5={cr5:.2f}），新品冷启动流量成本可能显著高于类目均值。")
    if hhi >= 0.15:
        risks.append(f"HHI={hhi:.3f}，竞争结构集中，价格战风险上升。")
    if snapshot["confidence_dist"]["low"]:
        risks.append(f"{snapshot['confidence_dist']['low']} 个商品数据置信度低于 0.55，未纳入候选。")
    if risk == "high":
        risks.append("高弹性定价会放大促销期的量价波动，需同步监控退货率与库存周转。")
    risks.append("部分商品处于促销周期，价格与销量存在短期扰动，量价关系不稳定。")
    risks.append("本报告基于公开页面采集的真实数据（单日快照口径）。" if stock_only
                 else "本报告基于演示用模拟数据生成，接入真实公开数据源后结论需重新计算。")

    platform_count = len({item["platform_name"] for item in snapshot["top_products"]})
    limitations = [
        "SPS 为公开信号推导的销量代理指标，非平台真实销量，仅用于横向比较。",
        f"当前覆盖 {platform_count} 个公开渠道的公开展示字段，未包含站内广告与私域数据。",
        "评价数据仅做聚合情感与关键词统计，不含任何用户个人信息。",
        f"统计窗口 {period[0]} ~ {period[1]}。",
    ]
    if stock_only:
        limitations.insert(0, (
            "公开页评价数是缓存展示值，本期增量不可观测：指标按「评价存量 ÷ 转化率 ÷ 假设窗口 "
            f"{STOCK_WINDOW_DAYS} 天」估算，环比与趋势不可用（置信度上限 0.40）。"
            if "review_increment_stale_stock_fallback" in modes else
            "当前仅有单日公开快照：指标按「评价存量 ÷ 类目评价转化率 ÷ 假设窗口 "
            f"{STOCK_WINDOW_DAYS} 天」估算，只适合判断量级，环比与趋势暂不可用。"
        ))
    mix_note = source_mix_note(modes)
    if mix_note:
        limitations.insert(0, mix_note)
    if brand_focus:
        limitations.append(f"输入为品牌「{brand_focus}」，已自动落到其主销类目「{category_name}」进行分析。")

    report = {
        "goal": goal,
        "params": {"query": query, "budget": budget, "risk": risk, "goal": goal},
        "category_id": category_id,
        "category_name": category_name,
        "query": query,
        "summary": summary,
        "conclusion": " ".join(conclusions),
        "evidence": evidence,
        "actions": actions,
        "risks": risks,
        "limitations": limitations,
        "confidence": round(confidence_base * 0.7 + (0.25 if candidates else 0.0), 3),
        "knowledge": retrieve_knowledge(category_name),
        "period": period,
    }

    verification = verify_evidence(conn, evidence)
    report["verification"] = verification
    report["generated_by"] = provider.name

    if not verification["passed"]:
        report["degraded"] = True
        report["summary"] = "数据不足：部分引用指标无法在指标层复现，已拒绝输出结论。"
        report["conclusion"] = "请先补全数据后重试。"
        report["actions"] = []
    else:
        report["degraded"] = False
        if provider.available():
            system = ("你是电商市场分析师。只能使用用户提供的指标数值，禁止引入任何新数字，"
                      "禁止修改给定数值，输出 3 句以内的中文行情判断。")
            user = json.dumps({
                "query": query,
                "summary": summary,
                "metrics": {item["metric"]: item["value"] for item in evidence},
            }, ensure_ascii=False)
            polished = provider.complete(system, user)
            if polished:
                report["conclusion"] = polished.strip()
        _persist(conn, report)

    return {
        "query": query,
        "matched": True,
        "resolution": resolution,
        "snapshot": snapshot,
        "report": report,
    }


# ---------------------------------------------------------------------------
# AI 追问：模型作答 + 数字溯源校验
#
# 这是本项目「用架构抑制幻觉」主张的第二层：证据链校验（verify_evidence）管的是
# **报告生成**，这里管的是**自由问答**——让模型真正承担一件模板原理上做不到的事
# （回答任意问题），同时保留"每个数字都能回指标层复现"这条底线。
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _collect_numbers(obj, out: list[float]) -> None:
    """递归收集快照里的所有数值，形成「可溯源数值池」。"""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_numbers(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _collect_numbers(value, out)


def _collect_key_numbers(obj, out: list[float]) -> None:
    """收集**字段名**里的数字（CR3 / CR5 / Top12 这类指标标识符）。

    这些数字是指标名称的一部分，不是模型生成的数据，必须豁免 ——
    否则模型只要规范地提到"CR5"，就会被误判成编造数字。
    这是本校验器唯一的两类豁免之一（另一类是用户提问里的数字），
    都不放宽对"数值型编造"的检查。
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            for raw in _NUM_RE.findall(str(key)):
                try:
                    out.append(float(raw.replace(",", "")))
                except ValueError:
                    pass
            _collect_key_numbers(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _collect_key_numbers(value, out)


def _traceable(value: float, pool: list[float], tol: float = 0.02) -> bool:
    """判断一个数字能否在指标层找到出处（含百分比写法的等价匹配）。

    容差 2%：模型会把 0.8979 写成 0.90 或 89.8%，必须能匹配上；
    同时 0.8979 与 0.95 不能被误判为同一个数。
    """
    for candidate in pool:
        base = max(abs(candidate), 1e-9)
        if abs(value - candidate) / base <= tol:
            return True
        as_percent = candidate * 100
        if 0 <= candidate <= 1 and abs(value - as_percent) / max(abs(as_percent), 1e-9) <= tol:
            return True
    return False


# 指标字段 → 中文名。回答里出现 cr5 / sps / listing_count 这类字段名，对卖家毫无意义，
# 因此**传给模型时就换成中文表述**，并要求它照此表达。
# 括号里标注方向：否则模型会自行解释（实测它曾把 HHI 低说成"更集中"，恰好说反）。
METRIC_LABELS = {
    "total_sps": "销量代理总量",
    "total_gms": "销售额估计",
    "growth": "环比增长",
    "cr5": "前五名商品集中度（越高越集中）",
    "hhi": "竞争集中度指数（越高越集中）",
    "brand_cr3": "前三品牌份额（越高越集中）",
    "avg_confidence": "平均数据置信度（越高越可信）",
    "listing_count": "在售商品数",
    "days": "统计天数",
    "heat_index": "需求热度指数（越高需求越旺）",
    "gap_index": "供需缺口指数（越高缺口越大）",
    "avg_price": "平均价格",
    "price_coverage": "价格覆盖率（越高价格信息越全）",
    "main_band_share": "主力价格带销量占比",
    "negative_keyword_share": "负面评价关键词占比（越高负面越多）",
    "subcategory_count": "细分类目数",
}

# 形如 CR5 / Top12 的指标编号属于标识符，不是数据。抽取数字前先剥离，
# 避免模型规范地写「CR5」反被当成编造数字。
_METRIC_TOKEN_RE = re.compile(r"(?:CR|Top|TOP|cr|top)\s?\d+")


def _metric_notes(snapshot: dict) -> list[str]:
    """把「数据口径」翻译成模型能听懂的话。

    没有这一段，模型看到「销售额估计」为 0 会理解成"没有销售额"、
    看到「环比增长」为 0 会理解成"没有增长"，于是只能回答"无法判断"。
    """
    notes: list[str] = []
    if not snapshot.get("avg_price"):
        notes.append("「销售额估计」「平均价格」为 0 表示该数据源未采集价格，不代表没有销售额")
    if not snapshot.get("growth"):
        notes.append("「环比增长」为 0 表示当前窗口不足以计算环比（例如仅单日快照），不代表没有增长")
    if not snapshot.get("negative_keyword_share"):
        notes.append("「负面评价关键词占比」为 0 表示该数据源未提供评价关键词，不代表没有负面评价")
    if snapshot.get("price_coverage") == 0:
        notes.append("「价格覆盖率」为 0 表示完全没有采到价格")
    if not notes:
        notes.append("各指标均已采集可用")
    return notes


def verify_answer_numbers(payload: dict, question: str, answer: str) -> dict:
    """抽出回答中的所有数字，逐个回「模型看到的数据」溯源。

    溯源基准就是**发给模型的 payload**：凡是模型看得到的数字，答出来都不算命造；
    它看不到却又说出来的数字才会被标红。

    这是本方案的核心校验：**不要求模型不撒谎，但要求它撒的谎能被抓住。**

    两类豁免（都不放宽对"数值型编造"的检查）：
    - 指标编号（CR5 / Top12）：抽取前整体剥离，它是标识符不是数据；
    - 用户提问里的数字（"5 万预算"）：由用户提供，不属于模型生成的内容。
    """
    pool: list[float] = []
    _collect_numbers(payload, pool)
    _collect_key_numbers(payload, pool)
    for raw in _NUM_RE.findall(question or ""):
        try:
            pool.append(float(raw.replace(",", "")))
        except ValueError:
            pass

    citations, unverified = [], []
    # 先剥离「CR5 / Top12」这类指标编号，再抽数字
    for raw in _NUM_RE.findall(_METRIC_TOKEN_RE.sub(" ", answer or "")):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        (citations if _traceable(value, pool) else unverified).append(raw)
    return {
        "citations": citations,          # 可溯源数字
        "unverified": unverified,        # 指标层找不到出处的数字（前端标红）
        "verified": not unverified,
        "metric_pool_size": len(pool),
    }


def answer_question(conn: sqlite3.Connection, query: str, question: str,
                    category_id: str | None = None) -> dict:
    """基于已算好的指标回答用户追问，并对回答中的每个数字做溯源校验。

    与项目整体立场一致：指标快照是唯一事实来源，模型不得引入新数字、不得做预测。
    模型答完后**事后校验**——抽出回答里的所有数字逐个回指标层比对，
    找不到出处的放进 `unverified`，由前端显著标红。
    """
    provider = get_provider()

    # 复用现有分析链路取指标快照，保证"追问的就是用户刚看到的那份数据"
    analysis = analyze_market_query(conn, query, category_id=category_id)
    if not analysis.get("matched"):
        return {
            "matched": False,
            "answer": None,
            "generated_by": provider.name,
            "message": analysis.get("message", "标的未覆盖，无法追问"),
            "candidates": analysis.get("candidates", []),
        }

    snapshot = analysis.get("snapshot") or {}

    # 未配置模型时优雅降级，而不是报错 —— 产品在无 AI 状态下依然完整可用
    if not provider.available():
        return {
            "matched": True,
            "answer": None,
            "generated_by": provider.name,
            "note": ("追问功能需要配置大模型；当前为离线模板模式，"
                     "行情分析与证据链功能不受影响。"),
        }

    # 只给模型标量指标是不够的：它看不到品类、看不到口径，会把"未采集"的 0
    # 误读成"没有市场"，于是只能回答"无法判断"。这里把上下文一并给它，
    # 让回答有判断力，同时保持"不得引入新数字"的硬约束。
    metrics = {key: value for key, value in snapshot.items()
               if isinstance(value, (int, float)) and not isinstance(value, bool)}
    # 键名一律用中文：模型看到英文键名就会照抄，回答里满是 cr5 / listing_count 这类黑话
    payload = {
        "品类": (snapshot.get("category") or {}).get("name"),
        "统计窗口": snapshot.get("period"),
        "窗口天数": snapshot.get("days"),
        "指标": [
            {"名称": METRIC_LABELS.get(key, key), "数值": value}
            for key, value in metrics.items()
        ],
        "口径说明": _metric_notes(snapshot),
        "销量代理前五商品": [
            {"商品": str(item.get("title", ""))[:32], "销量代理值": item.get("sps"),
             "价格": item.get("price"), "环比": item.get("growth")}
            for item in (snapshot.get("top_products") or [])[:5]
        ],
        "主要负面评价关键词": [
            item.get("keyword")
            for item in ((snapshot.get("keywords") or {}).get("negative") or [])[:5]
        ],
        "品牌份额": [
            {"品牌": item.get("brand"), "份额": item.get("share")}
            for item in (snapshot.get("brand_shares") or [])[:5]
        ],
        "卖家的问题": question,
    }
    system = (
        "你是电商选品分析师，正在为一位准备入场的中小卖家做判断。\n"
        "硬约束：只能使用给定数据中的数字，不得引入新数字、不得修改数值、不得预测具体销量。\n"
        "表述要求：**用中文指标名称**（如「前五名商品集中度」「在售商品数」），"
        "绝对不要出现英文字段名（如 cr5、sps、listing_count、growth）。\n"
        "同时要给出有价值的解读：这个类目的竞争格局意味着什么、这位卖家该注意什么、"
        "下一步建议做什么。不要因为「不能预测」就只说「无法判断」。\n"
        "注意「口径说明」解释了口径：某些指标为 0 是因为数据源未提供，"
        "不代表该品类没有市场，不要据此下否定结论。\n"
        "输出 3-4 句中文：先给结论，再给依据（引用具体指标名与数值），最后给一条可执行建议。"
    )
    user = json.dumps(payload, ensure_ascii=False)

    answer = provider.complete(system, user)
    if not answer:
        return {
            "matched": True,
            "answer": None,
            "generated_by": provider.name,
            "note": "模型调用失败，请检查网络或凭据配置。",
        }

    check = verify_answer_numbers(payload, question, answer)

    return {
        "matched": True,
        "answer": answer.strip(),
        "generated_by": provider.name,
        **check,
    }


def _persist(conn: sqlite3.Connection, report: dict) -> str:
    report_id = "rpt_" + uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO ai_report(report_id, user_id, topic, params_json, content_md, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (report_id, "local", report["category_name"],
         json.dumps(report.get("params", {}), ensure_ascii=False),
         report["summary"], datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )

    for item in report["evidence"]:
        conn.execute(
            "INSERT INTO ai_claim(claim_id, report_id, claim_text, metric, value, period,"
            " source_ref, confidence, verified) VALUES (?,?,?,?,?,?,?,?,?)",
            ("clm_" + uuid.uuid4().hex[:10], report_id, item.get("note") or item["metric"],
             item["metric"], float(item["value"]) if item["value"] is not None else None,
             item["period"], item["source"], item["confidence"],
             1 if report["verification"]["passed"] else 0),
        )
    conn.commit()
    return report_id
