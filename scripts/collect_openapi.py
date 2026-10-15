"""官方开放平台采集入口。

用法：
    python scripts/collect_openapi.py                                  # 用配置里的平台
    python scripts/collect_openapi.py --provider taobao --keywords 保温杯,收纳箱
    python scripts/collect_openapi.py --dump-raw                       # 保存原始响应，便于调字段映射
    python scripts/collect_openapi.py --dry-run                        # 只打印请求

采集完成后：python scripts/bootstrap.py --sources openapi_taobao
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.collector import openapi_source as api  # noqa: E402


def _arg(name: str, default: str | None = None) -> str | None:
    args = sys.argv[1:]
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def main() -> int:
    config = api.load_config()
    provider = _arg("--provider") or config.get("PROVIDER") or "taobao"
    if provider not in api.PROVIDERS:
        print(f"未知平台：{provider}，可选 {', '.join(api.PROVIDERS)}")
        return 1

    keywords_arg = _arg("--keywords")
    keywords = [k.strip() for k in keywords_arg.split(",") if k.strip()] if keywords_arg else None
    interval = max(float(_arg("--interval", "1") or 1), 0.2)
    dry_run = "--dry-run" in sys.argv
    dump_raw = "--dump-raw" in sys.argv

    definition = api.PROVIDERS[provider]
    print(f"平台：{definition['name']}（{provider}）")
    print(f"接口：{definition['search_method']}    网关：{definition['gateway']}")
    print(f"关键词：{keywords or api.DEFAULT_KEYWORDS}    限速：{interval} 秒/请求")
    print("-" * 66)

    result = api.collect(keywords=keywords, provider=provider, config=config,
                         interval=interval, dry_run=dry_run, dump_raw=dump_raw, verbose=True)

    print("-" * 66)
    if result.get("error") and not dry_run:
        print(f"采集未完成：{result['error']}")
        return 1
    if dry_run:
        print("dry-run 结束，未发送任何请求。")
        return 0

    print(f"共解析 {len(result['rows'])} 个商品，已写入 data/raw/{definition['source']}/")
    print(json.dumps({"pages": result["pages"]}, ensure_ascii=False, indent=2))
    print()
    print(f"下一步：python scripts/bootstrap.py --sources {definition['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
