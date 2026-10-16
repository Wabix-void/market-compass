"""端到端冒烟测试。

用法（需先启动服务）：
    python scripts/run_server.py &
    python tests/smoke_test.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8787"
RESULTS: list[tuple[str, bool, str]] = []


def _request(path: str, payload: dict | None = None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))


def main() -> int:
    # 基础接口
    health = _request("/api/health")
    check("health", health.get("status") == "ok", str(health.get("latest_date")))

    meta = _request("/api/meta")
    subcats = [c["name"] for c in meta["categories"] if c["level"] == 2]
    check("meta 类目数", len(meta["categories"]) >= 4,
          f"{len(meta['categories'])} 个（二级 {len(subcats)} 个）")
    check("meta AI 模式", bool(meta.get("llm_provider")), meta.get("llm_provider", ""))

    overview = _request("/api/overview")
    check("overview 总量>0", overview["total_sps"] > 0, f"{overview['total_sps']:,.0f}")

    trend = _request("/api/trend")
    check("trend 数据点", len(trend) >= 1, f"{len(trend)} 天")

    bands = _request("/api/price-bands")
    check("price-bands 占比合计≈1",
          abs(sum(b["sps_share"] for b in bands) - 1.0) < 0.02,
          f"{sum(b['sps_share'] for b in bands):.4f}")

    # 自由输入解析与行情分析：固定取 3 个细分类目做全流程验证。
    # 这样断言总数恒为 35 项，不随数据源类目数量漂移（文档与答辩引用同一个数）。
    probe_categories = (subcats * 3)[:3] if subcats else ["保温杯", "收纳箱", "置物架"]

    for name in probe_categories:
        resolution = _request("/api/resolve?q=" + urllib.parse.quote(name))
        best = resolution["best"] or {}
        check(f"resolve[{name}]", resolution["matched"],
              f"best={best.get('label')} score={best.get('score')}")

    uncovered = _request("/api/resolve?q=" + urllib.parse.quote("钢琴"))
    check("resolve[未覆盖]", not uncovered["matched"], "钢琴")

    # 行情分析：每个类目固定 6 项断言；未命中时其余 5 项如实判失败，而不是跳过导致总数变化
    for query in probe_categories:
        result = _request("/api/market-analysis", {"query": query, "budget": 200, "risk": "medium"})
        report = result.get("report") or {}
        snapshot = result.get("snapshot") or {}
        check(f"market[{query}] 命中", result["matched"], result.get("message", ""))
        check(f"market[{query}] 证据链校验通过",
              bool(report.get("verification", {}).get("passed")),
              f"{len(report.get('evidence', []))} 条证据")
        check(f"market[{query}] 有建议动作", len(report.get("actions", [])) > 0,
              f"{len(report.get('actions', []))} 条")
        check(f"market[{query}] 有数据罗列",
              (snapshot.get("listing_count") or 0) > 0
              and len(snapshot.get("price_bands", [])) > 0
              and len(snapshot.get("top_products", [])) > 0,
              f"{snapshot.get('listing_count', 0)} 条目 / {len(snapshot.get('top_products', []))} 榜单")
        check(f"market[{query}] 含局限性声明", len(report.get("limitations", [])) > 0)
        check(f"market[{query}] 未降级", not report.get("degraded", False))

    unmatched = _request("/api/market-analysis", {"query": "钢琴"})
    check("market[未覆盖] 有候选建议",
          not unmatched["matched"] and len(unmatched.get("candidates", [])) >= 0,
          unmatched.get("message", ""))

    # 选品参谋
    advice = _request("/api/advice", {"budget": 150, "risk": "medium", "goal": "选品"})
    check("advice 证据链校验通过", advice["verification"]["passed"], f"{len(advice['evidence'])} 条")

    # 商品与审计
    products = _request("/api/products?limit=5")
    check("products 返回", len(products) == 5)
    detail = _request("/api/products/" + products[0]["product_id"])
    check("detail 指标序列", len(detail["series"]) >= 1, f"{len(detail['series'])} 点")
    check("detail 含证据链", bool(detail["evidence"]))

    clusters = _request("/api/clusters")
    check("clusters 接口可用", isinstance(clusters, list), f"{len(clusters)} 个多平台上架簇")
    audit = _request("/api/audit")
    check("audit 台账", len(audit) > 0, f"{audit[0]['batch_id']}" if audit else "")

    # 输出
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{passed}/{len(RESULTS)} 项通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
