"""一键初始化：采集（种子适配器）→ ETL → 指标计算 → 生成一份示例 AI 建议。

用法：
    python scripts/bootstrap.py                        # 自动发现全部数据源 + 重新生成演示数据
    python scripts/bootstrap.py --sources suning       # 只用苏宁真实数据（不重新生成演示数据）
    python scripts/bootstrap.py --sources seed,suning  # 模拟 + 真实混合
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ai import advisor            # noqa: E402
from services.collector import seed_source  # noqa: E402
from services.etl import pipeline          # noqa: E402


def _parse_sources() -> list[str] | None:
    args = sys.argv[1:]
    if "--sources" not in args:
        return None
    index = args.index("--sources")
    if index + 1 >= len(args):
        return None
    return [item.strip() for item in args[index + 1].split(",") if item.strip()]


def main() -> None:
    started = time.time()
    sources = _parse_sources()

    if sources is None or "seed" in sources:
        print("[1/4] 生成演示数据（seed_simulator 适配器，无网络请求）…")
        collect_meta = seed_source.collect()
        print("      " + json.dumps(collect_meta["files"], ensure_ascii=False))
    else:
        print("[1/4] 跳过演示数据生成（使用已有原始层数据）…")

    print(f"[2/4] ETL：清洗 → 跨平台同款对齐 → 指标计算 …  数据源={sources or pipeline.discover_sources()}")
    result = pipeline.run_all(verbose=False, sources=sources)
    print("      " + json.dumps(result, ensure_ascii=False))

    print("[3/4] 生成示例 AI 建议并校验证据链 …")
    conn = pipeline.connect()
    try:
        report = advisor.advise(conn, budget=150.0, risk="medium", goal="选品")
    finally:
        conn.close()
    print("      证据链校验：" + ("通过" if report["verification"]["passed"] else "未通过"))
    print("      结论：" + report["summary"])

    print(f"[4/4] 完成，用时 {time.time() - started:.1f}s")
    print("下一步：python scripts/run_server.py  然后浏览器打开 http://127.0.0.1:8787")


if __name__ == "__main__":
    main()
