"""官方开放平台凭据配置向导。

用法：
    python scripts/setup_openapi.py                      # 交互式，按提示粘贴
    python scripts/setup_openapi.py --show               # 查看当前配置（脱敏）
    python scripts/setup_openapi.py --provider taobao \
        --app-key xxx --app-secret yyy                   # 非交互式（脚本/CI）

它会写入 `config/openapi.env`，凭据只保存在本机，不上传到任何地方。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.collector import openapi_source as api  # noqa: E402


def _force_utf8_console() -> None:
    """Windows 中文控制台默认 GBK，直接输出 ✓/✗ 会抛 UnicodeEncodeError，这里统一兜底。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_console()

PROVIDER_ORDER = ["taobao", "jd", "pdd"]


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return "（未设置）"
    if len(value) <= keep:
        return "****"
    return value[:keep] + "****"


def validate(name: str, value: str, low: int, high: int) -> str | None:
    if not value:
        return f"{name} 不能为空"
    if any(char.isspace() for char in value):
        return f"{name} 不能包含空格（粘贴时注意别带上换行或空格）"
    if not (low <= len(value) <= high):
        return f"{name} 长度异常：当前 {len(value)} 位，预期 {low}-{high} 位"
    return None


def ask(prompt: str, *, secret: bool = False, required: bool = True,
        low: int = 1, high: int = 256) -> str:
    suffix = "" if required else "（可留空，回车跳过）"
    while True:
        try:
            raw = getpass.getpass(f"{prompt}{suffix}: ") if secret else input(f"{prompt}{suffix}: ")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未写入任何内容。")
            sys.exit(1)
        value = raw.strip()
        if not value and not required:
            return ""
        error = validate(prompt, value, low, high)
        if error:
            print(f"  ✗ {error}，请重试")
            continue
        return value


def show_current() -> int:
    config = api.load_config()
    if not config:
        print("尚未配置。运行 python scripts/setup_openapi.py 开始配置。")
        return 0
    print(f"配置文件：{api.CONFIG_PATH}")
    print(f"  PROVIDER    : {config.get('PROVIDER', '（未设置）')}")
    print(f"  APP_KEY     : {mask(config.get('APP_KEY', ''))}")
    print(f"  APP_SECRET  : {mask(config.get('APP_SECRET', ''), 0)}")
    print(f"  SESSION_KEY : {mask(config.get('SESSION_KEY', '') or config.get('ACCESS_TOKEN', ''))}")
    for provider_key in PROVIDER_ORDER:
        missing = api.missing_keys(config, provider_key)
        status = "凭据完整" if not missing else f"缺少 {', '.join(missing)}"
        print(f"  [{provider_key}] {api.PROVIDERS[provider_key]['name']}：{status}")
    return 0


def choose_provider() -> str:
    print("可选平台：")
    for index, key in enumerate(PROVIDER_ORDER, start=1):
        provider = api.PROVIDERS[key]
        print(f"  {index}) {key:<7} {provider['name']:<22} 申请入口：{provider['apply_url']}")
    print()
    while True:
        raw = input("请选择平台 [1/2/3]（回车默认 1）: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(PROVIDER_ORDER):
            return PROVIDER_ORDER[int(raw) - 1]
        if raw in api.PROVIDERS:
            return raw
        print("  ✗ 请输入 1、2、3 或平台代号（taobao/jd/pdd）")


def main() -> int:
    parser = argparse.ArgumentParser(description="官方开放平台凭据配置向导")
    parser.add_argument("--provider", choices=PROVIDER_ORDER, help="平台代号")
    parser.add_argument("--app-key", help="AppKey（非交互模式）")
    parser.add_argument("--app-secret", help="AppSecret（非交互模式）")
    parser.add_argument("--session-key", default="", help="SessionKey / AccessToken（可选）")
    parser.add_argument("--show", action="store_true", help="只查看当前配置（脱敏）")
    args = parser.parse_args()

    if args.show:
        return show_current()

    print("=" * 66)
    print("商情罗盘 MarketCompass — 官方开放平台凭据配置")
    print("凭据只写入本机 config/openapi.env，不会上传到任何地方。")
    print("=" * 66)
    print()

    if args.provider and args.app_key and args.app_secret:
        provider_key = args.provider
        app_key, app_secret, session_key = args.app_key, args.app_secret, args.session_key
    else:
        provider_key = args.provider or choose_provider()
        provider = api.PROVIDERS[provider_key]
        print()
        print(f"已选择：{provider['name']}")
        print(f"申请入口：{provider['apply_url']}")
        print("拿到 AppKey / AppSecret 后，直接粘贴下面的输入框（输入时不回显，粘贴即可）。")
        print()
        app_key = ask("AppKey", low=4, high=64)
        app_secret = ask("AppSecret", secret=True, low=8, high=128)
        session_key = ask("SessionKey / AccessToken", secret=True, required=False)

    for name, value, low, high in (("AppKey", app_key, 4, 64), ("AppSecret", app_secret, 8, 128)):
        error = validate(name, value, low, high)
        if error:
            print(f"✗ {error}")
            return 1

    values = {"PROVIDER": provider_key, "APP_KEY": app_key, "APP_SECRET": app_secret}
    if session_key:
        values["SESSION_KEY"] = session_key
    path = api.save_config(values)

    provider = api.PROVIDERS[provider_key]
    print()
    print(f"✓ 已保存到 {path}")
    print(f"    平台      : {provider['name']}")
    print(f"    AppKey    : {mask(app_key)}")
    print(f"    AppSecret : {mask(app_secret, 0)}")
    if session_key:
        print(f"    SessionKey: {mask(session_key)}")
    print()
    print("下一步：")
    print("  1) python scripts/check_openapi.py            # 配置自检")
    print("  2) python scripts/check_openapi.py --live     # 真实调用一次，确认凭据有效")
    print(f"  3) python scripts/collect_openapi.py --provider {provider_key}")
    print("  4) python scripts/bootstrap.py --sources " + provider["source"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
