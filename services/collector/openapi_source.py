"""官方开放平台 API 适配器骨架（淘宝 / 京东 / 拼多多）。

为什么走官方 API
----------------
公开页面抓不到真实销量与价格（京东搜索页返回空壳、价格异步加载），而官方开放平台能直接返回
**真实销量与价格**，且完全合规。代价是需要申请凭据（AppKey / AppSecret），门槛如下：

| 平台 | 申请入口 | 门槛 |
|---|---|---|
| 淘宝开放平台 | https://open.taobao.com/ | 企业或个人开发者认证，部分接口需应用审核 |
| 京东宙斯 | https://jos.jd.com/ | 企业资质，部分接口需签约 |
| 拼多多开放平台 | https://open.pinduoduo.com/ | 开发者认证，多多客类接口门槛较低 |

**凭据不需要你改代码**：运行 `python scripts/setup_openapi.py`，按提示把值粘进去即可，
它会写入 `config/openapi.env`。之后用 `python scripts/check_openapi.py` 自检。

没有凭据时本适配器**不会崩溃**，而是返回清晰的缺失字段清单与申请入口。

字段映射说明
------------
各平台返回结构不同且会随接口版本变化，因此这里采用**候选字段名 + 自动定位列表**的方式做容错映射。
若拿到真实响应后字段对不上，用 `dry_run` 确认请求，再用 `dump_raw=True` 保存原始响应，
然后只调整本文件顶部的 `*_FIELDS` 常量即可，无需改动下游任何代码。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from services.collector import raw_store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "openapi.env"

TIMEOUT = 20
DEFAULT_INTERVAL = 1.0        # 官方接口按 QPS 配额限速，默认 1 秒/请求
DEFAULT_KEYWORDS = ["保温杯", "收纳箱", "置物架"]

# ---------------------------------------------------------------------------
# 平台定义
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "taobao": {
        "name": "淘宝天猫（开放平台）",
        "source": "openapi_taobao",
        "platform_id": "p_taobao_api",
        "prefix": "tb_",
        "gateway": "https://eco.taobao.com/router/rest",
        "apply_url": "https://open.taobao.com/",
        "key_param": "app_key",
        "session_param": "session_key",
        "session_required": False,
        "method_param": "method",
        "timestamp": "datetime",
        "public": {"format": "json", "v": "2.0", "sign_method": "md5"},
        "search_method": "taobao.tbk.item.get",
        "sales_semantics": "rolling_30d",
        "price_divisor": 1,
        "required": ["app_key", "app_secret"],
        "optional": ["session_key"],
    },
    "jd": {
        "name": "京东（宙斯开放平台）",
        "source": "openapi_jd",
        "platform_id": "p_jd_api",
        "prefix": "jd_",
        "gateway": "https://api.jd.com/routerjson",
        "apply_url": "https://jos.jd.com/",
        "key_param": "app_key",
        "session_param": "access_token",
        "session_required": False,
        "method_param": "method",
        "timestamp": "datetime",
        "public": {"format": "json", "v": "1.0", "sign_method": "md5"},
        "search_method": "jingdong.ware.list.get",
        "sales_semantics": "rolling_30d",
        "price_divisor": 1,
        "required": ["app_key", "app_secret"],
        "optional": ["access_token"],
    },
    "pdd": {
        "name": "拼多多（开放平台）",
        "source": "openapi_pdd",
        "platform_id": "p_pdd_api",
        "prefix": "pdd_",
        "gateway": "https://gw-api.pinduoduo.com/api/router",
        "apply_url": "https://open.pinduoduo.com/",
        "key_param": "client_id",
        "session_param": None,
        "session_required": False,
        "method_param": "type",
        "timestamp": "unix",
        "public": {"data_type": "JSON", "version": "1.0", "sign_method": "md5"},
        "search_method": "pdd.ddk.goods.search",
        "sales_semantics": "rolling_30d",
        "price_divisor": 100,     # 拼多多价格单位为分
        "required": ["app_key", "app_secret"],
        "optional": [],
    },
}

# 候选字段名（按优先级排序）——拿到真实响应后若对不上，只需调整这里
ID_FIELDS = ["num_iid", "item_id", "itemId", "ware_id", "wareId", "sku_id", "goods_id", "goodsId"]
TITLE_FIELDS = ["title", "item_name", "ware_title", "goods_name", "sku_name", "name"]
PRICE_FIELDS = ["zk_price", "price", "jd_price", "min_group_price", "reserve_price", "promotion_price"]
SALES_FIELDS = ["volume", "sold_quantity", "sales_tip", "sales", "sold", "comment_count", "comments"]
URL_FIELDS = ["item_url", "detail_url", "ware_url", "goods_url", "url", "click_url"]
SHOP_FIELDS = ["shop_title", "nick", "mall_name", "shop_name", "store_name"]


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """读取 config/openapi.env（KEY=VALUE 形式，支持 # 注释）。"""
    config_path = Path(path)
    config: dict[str, str] = {}
    if not config_path.exists():
        return config
    for line in config_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        config[key.strip().upper()] = value.strip()
    return config


def save_config(values: dict, path: Path | str = CONFIG_PATH) -> Path:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 商情罗盘 MarketCompass — 官方开放平台凭据",
        "# 由 scripts/setup_openapi.py 生成；请勿提交到版本库。",
        "",
    ]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def missing_keys(config: dict, provider_key: str) -> list[str]:
    provider = PROVIDERS[provider_key]
    missing = [key for key in provider["required"] if not config.get(key.upper())]
    if provider.get("session_required") and not config.get("SESSION_KEY"):
        missing.append("session_key")
    return missing


def config_hint(provider_key: str) -> str:
    provider = PROVIDERS[provider_key]
    return (
        f"缺少凭据，无法调用 {provider['name']} 接口。\n"
        f"  1) 到 {provider['apply_url']} 申请应用，拿到 AppKey / AppSecret；\n"
        f"  2) 运行 python scripts/setup_openapi.py --provider {provider_key}，按提示粘贴；\n"
        f"  3) 运行 python scripts/check_openapi.py 自检。"
    )


# ---------------------------------------------------------------------------
# 签名与请求构造
# ---------------------------------------------------------------------------
def sign_params(params: dict, secret: str) -> str:
    """通用签名：md5(secret + 按 key 升序拼接的 k1v1k2v2… + secret)，大写。

    淘宝 / 京东 / 拼多多的签名规则在这一形式上是等价的，差异只在公共参数名。
    """
    items = sorted(
        (key, value) for key, value in params.items()
        if key != "sign" and value is not None and value != ""
    )
    raw = secret + "".join(f"{key}{value}" for key, value in items) + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def _timestamp(provider: dict) -> str:
    now = datetime.now(timezone.utc)
    if provider["timestamp"] == "unix":
        return str(int(now.timestamp()))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def build_request(provider_key: str, config: dict, business_params: dict | None = None
                  ) -> tuple[str, dict]:
    """构造 (gateway, params)，params 已含签名。不发送请求，便于 dry-run 与单测。"""
    provider = PROVIDERS[provider_key]
    secret = config.get("APP_SECRET", "")
    params: dict[str, str] = dict(provider["public"])
    params[provider["method_param"]] = provider["search_method"]
    params[provider["key_param"]] = config.get("APP_KEY", "")
    params["timestamp"] = _timestamp(provider)

    session_param = provider.get("session_param")
    session_value = config.get("SESSION_KEY") or config.get("ACCESS_TOKEN")
    if session_param and session_value:
        params[session_param] = session_value

    for key, value in (business_params or {}).items():
        params[key] = value

    params["sign"] = sign_params(params, secret)
    return provider["gateway"], params


def call_api(provider_key: str, config: dict, business_params: dict | None = None
             ) -> tuple[bool, dict | str]:
    """调用接口，返回 (成功, 响应字典 或 错误说明)。"""
    gateway, params = build_request(provider_key, config, business_params)
    body = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        gateway, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        return False, f"HTTPError {exc.code} {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    try:
        return True, json.loads(text)
    except json.JSONDecodeError:
        return False, f"响应不是 JSON：{text[:200]}"


# ---------------------------------------------------------------------------
# 响应解析（容错映射）
# ---------------------------------------------------------------------------
def _looks_like_item(node) -> bool:
    return isinstance(node, dict) and any(field in node for field in TITLE_FIELDS)


def extract_items(payload, max_depth: int = 6) -> list[dict]:
    """在任意嵌套结构中定位商品列表（各平台包装层不同，且会随版本变化）。"""
    queue: list[tuple[object, int]] = [(payload, 0)]
    while queue:
        node, depth = queue.pop(0)
        if depth > max_depth:
            continue
        if isinstance(node, list) and node and _looks_like_item(node[0]):
            return [item for item in node if isinstance(item, dict)]
        if isinstance(node, dict):
            queue.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            queue.extend((value, depth + 1) for value in node)
    return []


def _pick(raw: dict, fields: list[str]):
    for field in fields:
        value = raw.get(field)
        if value not in (None, ""):
            return value
    return None


def parse_count(value) -> int | None:
    """'1万+' / '9000' / 1234 → 整数。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace("+", "").replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*(万)?", text)
    if not match:
        return None
    number = float(match.group(1))
    return int(number * 10000) if match.group(2) else int(number)


def _to_float(value, divisor: int = 1) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return round(number / divisor, 2) if divisor != 1 else round(number, 2)


def normalize_item(raw: dict, provider_key: str) -> dict | None:
    provider = PROVIDERS[provider_key]
    product_id = _pick(raw, ID_FIELDS)
    title = _pick(raw, TITLE_FIELDS)
    if product_id in (None, "") or not title:
        return None
    return {
        "product_id": f"{provider['prefix']}{product_id}",
        "title": str(title).strip(),
        "price": _to_float(_pick(raw, PRICE_FIELDS), provider["price_divisor"]),
        "sales": parse_count(_pick(raw, SALES_FIELDS)),
        "url": _pick(raw, URL_FIELDS),
        "shop": _pick(raw, SHOP_FIELDS),
    }


def parse_response(payload, provider_key: str) -> list[dict]:
    items = extract_items(payload)
    normalized = [normalize_item(item, provider_key) for item in items]
    return [item for item in normalized if item]


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------
def collect(keywords: list[str] | None = None, provider: str = "taobao",
            config: dict | None = None, interval: float = DEFAULT_INTERVAL,
            dry_run: bool = False, dump_raw: bool = False, verbose: bool = True) -> dict:
    keywords = keywords or DEFAULT_KEYWORDS
    if provider not in PROVIDERS:
        return {"error": f"未知平台 {provider}，可选：{', '.join(PROVIDERS)}"}

    definition = PROVIDERS[provider]
    config = config if config is not None else load_config()
    result: dict = {
        "source": definition["source"],
        "provider": provider,
        "provider_name": definition["name"],
        "gateway": definition["gateway"],
        "method": definition["search_method"],
        "keywords": keywords,
        "interval_seconds": interval,
        "dry_run": dry_run,
        "robots_allowed": 1,          # 官方授权接口，不受 robots 约束
        "pages": [],
        "rows": [],
    }

    missing = missing_keys(config, provider)
    if missing and not dry_run:
        result["error"] = config_hint(provider)
        result["missing_keys"] = missing
        if verbose:
            print(result["error"])
        return result

    stat_date = datetime.now(timezone.utc).date().isoformat()
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for index, keyword in enumerate(keywords):
        business = {"q": keyword, "keyword": keyword, "page": "1", "page_size": "40"}
        gateway, params = build_request(provider, config, business)
        if dry_run:
            masked = {**params, "sign": params["sign"][:8] + "…"}
            if verbose:
                print(f"[dry-run] POST {gateway}")
                print("          " + json.dumps(masked, ensure_ascii=False))
            result["pages"].append({"keyword": keyword, "status": 0,
                                    "request_preview": masked, "items": 0})
            continue

        if index > 0:
            time.sleep(interval)
        ok, payload = call_api(provider, config, business)
        if not ok:
            result["pages"].append({"keyword": keyword, "status": -1, "error": str(payload), "items": 0})
            if verbose:
                print(f"[{provider}] {keyword}: 调用失败 {payload}")
            continue

        if dump_raw:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            raw_store.save_snapshot(definition["source"], [payload], f"{stamp}_{keyword}")

        items = parse_response(payload, provider)
        result["pages"].append({"keyword": keyword, "status": 200, "items": len(items)})
        if verbose:
            print(f"[{provider}] {keyword}: 解析出 {len(items)} 个商品")
        for position, item in enumerate(items, start=1):
            result["rows"].append({**item, "keyword": keyword, "rank": position,
                                   "captured_at": captured_at, "stat_date": stat_date})

    if result["rows"] and not dry_run:
        _persist(result, definition)
    elif not dry_run and not result["rows"]:
        result["error"] = result.get("error") or "接口返回中未解析到商品数据（可能是字段映射需调整，试试 dump_raw=True）"
    return result


def _persist(result: dict, definition: dict) -> None:
    source = definition["source"]
    rows = result["rows"]
    by_id: dict[str, dict] = {}
    for row in rows:
        by_id.setdefault(row["product_id"], row)

    categories: list[dict] = []
    root_id = f"c_{source}_root"
    root_name = definition["name"]
    categories.append({"category_id": root_id, "parent_id": None,
                       "name": root_name, "level": 1, "aliases": [root_name]})
    keyword_ids: dict[str, str] = {}
    for keyword in result["keywords"]:
        category_id = "c_" + hashlib.md5(f"{source}{keyword}".encode("utf-8")).hexdigest()[:6]
        keyword_ids[keyword] = category_id
        categories.append({"category_id": category_id, "parent_id": root_id,
                           "name": keyword, "level": 2, "aliases": [keyword]})

    listings = [{
        "product_id": row["product_id"],
        "platform_id": definition["platform_id"],
        "title": row["title"],
        "brand": None,
        "category_id": keyword_ids[row["keyword"]],
        "attrs": {"店铺": row["shop"], "关键词": row["keyword"], "数据来源": definition["name"]},
        "url": row["url"] or "",
        "first_seen": row["stat_date"],
    } for row in by_id.values()]

    group_size: dict[str, int] = {}
    for row in by_id.values():
        category_id = keyword_ids[row["keyword"]]
        group_size[category_id] = group_size.get(category_id, 0) + 1

    signals = [{
        "product_id": row["product_id"],
        "stat_date": row["stat_date"],
        "sold_cumulative": row["sales"],
        "sales_semantics": definition["sales_semantics"],
        "review_cumulative": None,
        "rank": row["rank"],
        "list_size": group_size.get(keyword_ids[row["keyword"]], len(by_id)),
        "price": row["price"],
        "promo_price": None,
        "platform_id": definition["platform_id"],
    } for row in by_id.values()]

    platform = {
        "platform_id": definition["platform_id"],
        "name": definition["name"],
        "source_type": "openapi",
        "compliance_note": f"官方开放平台授权接口（{definition['apply_url']}），数据使用遵守平台协议",
    }

    meta = {key: value for key, value in result.items() if key != "rows"}
    raw_store.persist(source, meta, platform=platform, categories=categories,
                      listings=listings, signals=signals, reviews=[])


if __name__ == "__main__":
    print(json.dumps(collect(dry_run=True), ensure_ascii=False, indent=2))
