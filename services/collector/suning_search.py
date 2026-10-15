"""苏宁易购公开搜索页采集适配器（真实数据源）。

数据来源与合规
--------------
- 目标：`https://search.suning.com/{关键词}/` 的**公开搜索结果页**（无需登录即可访问）；
- robots：采集前读取 `https://www.suning.com/robots.txt`。实测返回 404（无规则），
  此时按"无明确禁止"处理并记录到审计台账；若返回规则且禁止该路径，则拒绝采集；
- 限速：默认每个请求间隔 3 秒（`REQUEST_INTERVAL`），不并发、不重试轰炸；
- 字段：只取公开展示的 SKU、标题、卖点、评价数、店铺类型、榜单排名；
  **不采集任何个人信息**（无用户 ID、无评论正文、无联系方式）；
- 价格：搜索结果页的价格为异步加载，静态页面取不到，因此留空（`price=None`）。

产出与 `seed_source` 完全相同的原始层格式，下游 ETL / 指标 / AI / 看板无需改动。
多次采集会按 (product_id, stat_date) 累积，形成可比较的时间序列。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "suning"
SNAPSHOT_DIR = RAW_DIR / "snapshots"

SOURCE_NAME = "suning_search"
PLATFORM_ID = "p_suning"
PLATFORM_NAME = "苏宁易购"
ROOT_CATEGORY_ID = "c_sn_root"
ROOT_CATEGORY_NAME = "苏宁在售"

ROBOTS_URL = "https://www.suning.com/robots.txt"
SEARCH_URL = "https://search.suning.com/{keyword}/"
REQUEST_INTERVAL = 3.0
TIMEOUT = 20
DEFAULT_KEYWORDS = ["保温杯", "收纳箱", "置物架"]

USER_AGENT = (
    "MarketCompassBot/0.1 (+public-commerce-research; robots-compliant; "
    "rate-limit-3s; no-personal-data)"
)

BLOCK_MARKER = 'class="item-bg"'
RE_SKU = re.compile(r"prdid':'(\d+)'")
RE_SKU_FALLBACK = re.compile(r"dataPro=\"\|\|(\d+)\|\|")
RE_TITLE = re.compile(r'class="title-selling-point">\s*<a[^>]*>(.*?)(?:<em|</a>)', re.S)
RE_SELL_POINT = re.compile(r'<em style="display:none"[^>]*>(.*?)</em>', re.S)
RE_REVIEW = re.compile(r'class="info-evaluate">.*?<i>(.*?)</i>', re.S)
RE_SHOP = re.compile(r'class="store-class[^"]*">(.*?)</a>', re.S)
RE_BRAND_ID = re.compile(r'brand_id="(\d+)"')


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_count(text: str) -> int | None:
    """把 '9000+' / '1.2万+' / '356' 这类展示值解析为整数。"""
    if not text:
        return None
    raw = _strip_tags(text).replace("+", "").strip()
    match = re.search(r"([\d.]+)\s*(万)?", raw)
    if not match:
        return None
    value = float(match.group(1))
    return int(value * 10000) if match.group(2) else int(value)


def _http_get(url: str) -> tuple[int, str, str]:
    """返回 (状态码, 响应体, 错误说明)。状态码 -1 表示请求本身失败。"""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="ignore"), ""
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTPError {exc.code} {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"{type(exc).__name__}: {exc}"


def check_robots(path: str = "/search") -> tuple[bool, str]:
    """读取 robots.txt 判定是否允许采集。

    注意：部分站点会把 /robots.txt 请求重定向成首页 HTML，此时不能当作"允许"。
    """
    status, body, error = _http_get(ROBOTS_URL)
    if status == 404:
        return True, "robots.txt 返回 404（无规则），按无明确禁止处理"
    if status != 200 or not body.strip():
        detail = error or f"HTTP {status}"
        return False, f"robots.txt 无法确认规则（{detail}），保守放弃"
    head = body.lstrip()[:20].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return False, "robots.txt 返回的是 HTML 页面而非规则，视为不可判定，保守放弃"

    disallow_all = re.search(r"User-agent:\s*\*\s*\n(?:.*\n)*?Disallow:\s*/\s*$", body, re.M)
    if disallow_all:
        return False, "robots.txt 禁止全站抓取"
    if re.search(rf"Disallow:\s*{re.escape(path)}", body):
        return False, f"robots.txt 明确 Disallow {path}"
    return True, f"robots.txt 未禁止 {path}（{len(body)} 字节规则）"


def _category_id(keyword: str) -> str:
    return "c_sn_" + hashlib.md5(keyword.encode("utf-8")).hexdigest()[:6]


def relevance_level(text: str, keyword: str) -> int:
    """判断商品与搜索关键词的相关性。

    搜索结果页常混入"相关推荐"等无关商品，必须过滤，否则行情数据会被污染。

    2 = 包含完整关键词；1 = 包含关键词的**尾部 2-gram**（通常是品类核心词）；
    0 = 无关。用尾部而不是任意 2-gram，是为了避免"宠物窝 → 宠物粮"这类误判。
    """
    if not text or not keyword:
        return 0
    if keyword in text:
        return 2
    return 1 if keyword[-2:] in text else 0


# ---------------------------------------------------------------------------
# 抓取与解析
# ---------------------------------------------------------------------------
def fetch_keyword(keyword: str) -> tuple[int, str, str]:
    url = SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
    return _http_get(url)


def parse_search_page(html: str, keyword: str, captured_at: str,
                      filter_irrelevant: bool = True) -> tuple[list[dict], int]:
    """解析搜索结果页，抽出每个商品的公开展示字段。

    返回 (相关商品列表, 被过滤掉的无关条数)。`filter_irrelevant=False` 时全部保留。
    """
    blocks = html.split(BLOCK_MARKER)[1:]
    category_id = _category_id(keyword)
    rows: list[dict] = []
    seen: set[str] = set()
    filtered = 0

    for position, block in enumerate(blocks[:60], start=1):
        sku_match = RE_SKU.search(block) or RE_SKU_FALLBACK.search(block)
        if not sku_match:
            continue
        sku = sku_match.group(1)
        if sku in seen:
            continue
        seen.add(sku)

        title_match = RE_TITLE.search(block)
        title = _strip_tags(title_match.group(1)) if title_match else ""
        if not title:
            continue

        sell_match = RE_SELL_POINT.search(block)
        sell_point = _strip_tags(sell_match.group(1)) if sell_match else ""

        if filter_irrelevant and relevance_level(f"{title} {sell_point}", keyword) == 0:
            filtered += 1
            continue

        review_match = RE_REVIEW.search(block)
        shop_match = RE_SHOP.search(block)
        brand_match = RE_BRAND_ID.search(block)

        rows.append({
            "sku": sku,
            "product_id": f"sn_{sku}",
            "title": title,
            "sell_point": sell_point,
            "review_count": _parse_count(review_match.group(1)) if review_match else None,
            "shop_type": _strip_tags(shop_match.group(1)) if shop_match else "",
            "brand_id": brand_match.group(1) if brand_match else None,
            "rank": position,
            "relevance": relevance_level(f"{title} {sell_point}", keyword),
            "category_id": category_id,
            "keyword": keyword,
            "url": f"https://product.suning.com/0000000000/{sku}.html",
            "captured_at": captured_at,
        })
    return rows, filtered


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _merge_by_key(path: Path, rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """按主键合并旧数据，避免重复采集产生重复行。"""
    merged: dict[tuple, dict] = {}
    for row in _read_jsonl(path):
        merged[tuple(row.get(key) for key in keys)] = row
    for row in rows:
        merged[tuple(row.get(key) for key in keys)] = row
    return list(merged.values())


def collect(keywords: list[str] | None = None, interval: float = REQUEST_INTERVAL,
            verbose: bool = True, filter_irrelevant: bool = True) -> dict:
    """执行一次真实采集，写出原始层文件与快照归档。"""
    keywords = keywords or DEFAULT_KEYWORDS
    allowed, robots_note = check_robots("/search")
    started = datetime.now(timezone.utc)
    captured_at = started.isoformat(timespec="seconds")
    stat_date = date.today().isoformat()

    result = {
        "source": SOURCE_NAME,
        "platform": PLATFORM_NAME,
        "url": SEARCH_URL.format(keyword="<关键词>"),
        "robots_allowed": 1 if allowed else 0,
        "robots_note": robots_note,
        "captured_at": captured_at,
        "stat_date": stat_date,
        "keywords": keywords,
        "interval_seconds": interval,
        "pages": [],
        "rows": [],
    }

    if not allowed:
        result["error"] = f"robots 判定不允许采集：{robots_note}"
        if verbose:
            print(f"[suning] 放弃采集：{robots_note}")
        return result

    for index, keyword in enumerate(keywords):
        if index > 0:
            time.sleep(interval)
        status, html, error = fetch_keyword(keyword)
        if status == 200:
            rows, filtered = parse_search_page(html, keyword, captured_at,
                                               filter_irrelevant=filter_irrelevant)
        else:
            rows, filtered = [], 0
        result["pages"].append({
            "keyword": keyword, "status": status, "error": error,
            "html_bytes": len(html), "items": len(rows), "filtered_out": filtered,
        })
        if verbose:
            detail = f" {error}" if error else ""
            print(f"[suning] {keyword}: HTTP {status}{detail}, {len(html)}B, "
                  f"相关商品 {len(rows)} 个（过滤无关 {filtered} 个）")
        if rows:
            # 写入原始快照归档（不可变，保留可追溯性）
            stamp = started.strftime("%Y%m%dT%H%M%S")
            _write_jsonl(SNAPSHOT_DIR / f"snapshot_{stamp}_{_category_id(keyword)}.jsonl", rows)
            result["rows"].extend(rows)

    if not result["rows"]:
        result["error"] = "未解析到任何商品数据"
        return result

    result["filtered_out"] = sum(page["filtered_out"] for page in result["pages"])
    _persist(result)
    return result


def _persist(result: dict) -> None:
    rows = result["rows"]
    by_sku: dict[str, dict] = {}
    for row in rows:
        by_sku.setdefault(row["product_id"], row)

    # 维度：平台
    _write_jsonl(RAW_DIR / "platforms.jsonl", [{
        "platform_id": PLATFORM_ID,
        "name": PLATFORM_NAME,
        "source_type": "public_page",
        "compliance_note": ("公开搜索结果页；遵守 robots；限速 3 秒/请求；"
                            "只取公开展示字段，不采集个人信息"),
    }])

    # 维度：类目（根 + 每个关键词）
    categories = [{
        "category_id": ROOT_CATEGORY_ID, "parent_id": None,
        "name": ROOT_CATEGORY_NAME, "level": 1, "aliases": ["苏宁"],
    }]
    for keyword in result["keywords"]:
        categories.append({
            "category_id": _category_id(keyword),
            "parent_id": ROOT_CATEGORY_ID,
            "name": keyword,
            "level": 2,
            "aliases": [keyword],
        })
    _write_jsonl(RAW_DIR / "categories.jsonl", categories)

    # 维度：商品
    listings = [{
        "product_id": row["product_id"],
        "platform_id": PLATFORM_ID,
        "title": row["title"],
        "brand": None,
        "category_id": row["category_id"],
        "attrs": {
            "卖点": row["sell_point"],
            "店铺类型": row["shop_type"],
            "品牌ID": row["brand_id"],
            "关键词": row["keyword"],
        },
        "url": row["url"],
        "first_seen": result["stat_date"],
    } for row in by_sku.values()]
    _write_jsonl(RAW_DIR / "listings.jsonl",
                 _merge_by_key(RAW_DIR / "listings.jsonl", listings, ("product_id",)))

    # 事实：日信号（评价数为公开存量信号；已售件数与价格在公开页面不可得）
    group_size: dict[str, int] = {}
    for row in by_sku.values():
        group_size[row["category_id"]] = group_size.get(row["category_id"], 0) + 1
    signals = [{
        "product_id": row["product_id"],
        "stat_date": result["stat_date"],
        "sold_cumulative": None,
        "review_cumulative": row["review_count"],
        "rank": row["rank"],
        "list_size": group_size.get(row["category_id"], len(by_sku)),
        "price": None,
        "promo_price": None,
        "platform_id": PLATFORM_ID,
        "captured_at": row["captured_at"],
    } for row in by_sku.values()]
    _write_jsonl(RAW_DIR / "signals.jsonl",
                 _merge_by_key(RAW_DIR / "signals.jsonl", signals, ("product_id", "stat_date")))

    # 事实：评价聚合（只统计数量，不采集评论正文与任何用户信息）
    reviews = [{
        "product_id": row["product_id"],
        "review_cnt": row["review_count"] or 0,
        "sentiment_pos": None,
        "sentiment_neg": None,
        "top_keywords": [],
    } for row in by_sku.values()]
    _write_jsonl(RAW_DIR / "reviews.jsonl",
                 _merge_by_key(RAW_DIR / "reviews.jsonl", reviews, ("product_id",)))

    # 需求热度：用搜索结果的商品数作为弱信号占位（真实搜索指数需官方接口）
    heat = []
    for keyword in result["keywords"]:
        count = len([r for r in by_sku.values() if r["keyword"] == keyword])
        heat.append({
            "keyword_id": f"kw_{_category_id(keyword)}",
            "stat_date": result["stat_date"],
            "heat_index": float(count) * 100.0,
            "source": "public_page:result_count_proxy",
        })
    if heat:
        _write_jsonl(RAW_DIR / "search_heat.jsonl",
                     _merge_by_key(RAW_DIR / "search_heat.jsonl", heat, ("keyword_id", "stat_date")))


if __name__ == "__main__":
    meta = collect()
    print(json.dumps({k: v for k, v in meta.items() if k != "rows"}, ensure_ascii=False, indent=2))
