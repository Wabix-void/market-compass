"""官方开放平台配置自检。

用法：
    python scripts/check_openapi.py                 # 只检查本地配置（不发请求）
    python scripts/check_openapi.py --live          # 真实调用一次，验证凭据是否有效
    python scripts/check_openapi.py --dry-run       # 打印将要发送的请求（签名脱敏）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.collector import openapi_source as api  # noqa: E402


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return "（未设置）"
    return "****" if len(value) <= keep else value[:keep] + "****"


def main() -> int:
    parser = argparse.ArgumentParser(description="开放平台配置自检")
    parser.add_argument("--provider", choices=list(api.PROVIDERS), help="平台代号")
    parser.add_argument("--keyword", default="保温杯", help="测试用关键词")
    parser.add_argument("--live", action="store_true", help="真实调用一次接口")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求，不发送")
    args = parser.parse_args()

    config = api.load_config()
    print(f"配置文件：{api.CONFIG_PATH}")
    if not config:
        print("状态：✗ 尚未配置")
        print()
        print("请先运行：python scripts/setup_openapi.py")
        return 1

    provider_key = args.provider or config.get("PROVIDER", "taobao")
    if provider_key not in api.PROVIDERS:
        print(f"状态：✗ 配置里的 PROVIDER={provider_key} 不是支持的平台")
        return 1
    provider = api.PROVIDERS[provider_key]

    print(f"平台    ：{provider['name']}（{provider_key}）")
    print(f"AppKey  ：{mask(config.get('APP_KEY', ''))}")
    print(f"AppSecret：{mask(config.get('APP_SECRET', ''), 0)}")

    missing = api.missing_keys(config, provider_key)
    if missing:
        print(f"状态：✗ 缺少 {', '.join(missing)}")
        print()
        print(api.config_hint(provider_key))
        return 1
    print("状态：✓ 凭据字段完整")
    print()

    business = {"q": args.keyword, "keyword": args.keyword, "page": "1", "page_size": "20"}
    gateway, params = api.build_request(provider_key, config, business)

    if args.dry_run or not args.live:
        preview = {**params, "sign": params["sign"][:10] + "…"}
        print("将要发送的请求（签名已脱敏）：")
        print(f"  POST {gateway}")
        for key, value in preview.items():
            print(f"    {key} = {value}")
        if not args.live:
            print()
            print("提示：加 --live 才会真正调用接口。")
        return 0

    print(f"正在调用 {provider['search_method']}（keyword={args.keyword}）…")
    ok, payload = api.call_api(provider_key, config, business)
    if not ok:
        print(f"调用失败：{payload}")
        print()
        print("常见原因：AppKey/AppSecret 错误、应用未审核通过、接口未签约、IP 白名单未配置、QPS 超限。")
        return 1

    items = api.parse_response(payload, provider_key)
    print(f"调用成功，解析出 {len(items)} 个商品")
    if not items:
        print()
        print("响应里没有解析到商品，可能是字段映射需要调整。原始响应顶层键：")
        print("  " + ", ".join(list(payload)[:10]) if isinstance(payload, dict) else str(payload)[:200])
        print()
        print("排查方式：python scripts/collect_openapi.py --dump-raw，然后调整")
        print("services/collector/openapi_source.py 顶部的 *_FIELDS 常量。")
        return 1

    for item in items[:3]:
        print(f"  - [{item['product_id']}] {item['title'][:40]} | "
              f"销量 {item['sales']} | 价格 {item['price']}")
    print()
    print(f"下一步：python scripts/collect_openapi.py --provider {provider_key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
