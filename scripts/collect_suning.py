"""苏宁公开搜索页采集入口。

用法：
    python scripts/collect_suning.py                                  # 默认关键词
    python scripts/collect_suning.py --keywords 保温杯,猫爬架,收纳箱
    python scripts/collect_suning.py --interval 5                     # 自定义限速（秒/请求，最小 1）

合规：遵守 robots.txt、默认限速 3 秒/请求、只取公开展示字段、不采集个人信息。
采集完成后请执行 `python scripts/bootstrap.py --sources suning` 重新计算指标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.collector import suning_search  # noqa: E402


def _arg(name: str, default: str | None = None) -> str | None:
    args = sys.argv[1:]
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def main() -> int:
    keywords_arg = _arg("--keywords")
    keywords = ([k.strip() for k in keywords_arg.split(",") if k.strip()]
                if keywords_arg else None)
    interval = float(_arg("--interval", "3") or 3)
    interval = max(interval, 1.0)

    print(f"关键词：{keywords or suning_search.DEFAULT_KEYWORDS}")
    print(f"限速：{interval} 秒/请求   目标：{suning_search.SEARCH_URL.format(keyword='<关键词>')}")
    print("-" * 60)

    meta = suning_search.collect(keywords=keywords, interval=interval, verbose=True)

    print("-" * 60)
    print(f"robots 判定：{'允许' if meta['robots_allowed'] else '拒绝'} —— {meta['robots_note']}")
    if meta.get("error"):
        print(f"采集失败：{meta['error']}")
        return 1

    print(f"共解析 {len(meta['rows'])} 条商品，已写入 data/raw/suning/")
    print("下一步：python scripts/bootstrap.py --sources suning")
    print(json.dumps({"rows": len(meta["rows"]), "pages": meta["pages"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
