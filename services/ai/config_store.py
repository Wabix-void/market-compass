"""AI 接入配置的持久化（BYOK：用户自带密钥，不改代码接入模型）。

安全边界（务必守住）：
- 密钥只存在于服务端文件，任何接口只返回**掩码**，绝不回传明文；
- 前端不写 localStorage / sessionStorage，不打印到控制台；
- 文件权限尽量收紧到当前用户；
- 已知限制：这是轻量方案，生产环境应换用系统凭据库（Windows DPAPI / macOS Keychain）。

配置优先级（由 llm_provider 消费）：
    config/llm.json  >  环境变量 MARKETCOMPASS_LLM_*  >  注册表 HKCU\\Environment  >  离线模板
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "llm.json"

PROTOCOLS = ("openai", "anthropic")

# 协议默认地址（与文档一致）
DEFAULT_BASE_URL = {
    "openai": "https://api.deepseek.com/v1",
    "anthropic": "https://api.deepseek.com/anthropic",
}
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_DISPLAY = "DeepSeek-Chat"


def mask_key(key: str) -> str:
    """sk-abcdef1234567890 → sk-••••••••••••7890（只露头 3 尾 4）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * 8
    return f"{key[:3]}{'•' * 12}{key[-4:]}"


def _blank_config() -> dict:
    return {
        "protocol": "openai",
        "base_url": "",
        "api_key": "",
        "models": [],
        "updated_at": None,
    }


def load() -> dict:
    """读取完整配置（含明文密钥，仅供服务端内部使用）。"""
    if not CONFIG_PATH.exists():
        return _blank_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank_config()
    config = _blank_config()
    config.update({k: v for k, v in data.items() if k in config})
    config["models"] = [m for m in config.get("models") or [] if isinstance(m, dict)]
    return config


def primary_model(config: dict | None = None) -> str:
    """取第一个模型的 id 作为运行模型；未配置时返回空串，由调用方决定回落。"""
    config = config or load()
    for model in config.get("models") or []:
        model_id = str(model.get("id") or "").strip()
        if model_id:
            return model_id
    return ""


def effective() -> dict:
    """当前生效的接入参数（供 llm_provider 使用）。"""
    config = load()
    return {
        "protocol": config.get("protocol") or "openai",
        "base_url": str(config.get("base_url") or "").strip(),
        "api_key": str(config.get("api_key") or "").strip(),
        "model": primary_model(config),
    }


def public_view() -> dict:
    """给前端的视图：**不含明文密钥**。"""
    config = load()
    key = str(config.get("api_key") or "")
    return {
        "protocol": config.get("protocol") or "openai",
        "base_url": config.get("base_url") or DEFAULT_BASE_URL.get(config.get("protocol") or "openai", ""),
        "models": [
            {
                "id": str(model.get("id") or ""),
                "display": str(model.get("display") or ""),
            }
            for model in config.get("models") or []
        ],
        "has_key": bool(key),
        "key_masked": mask_key(key),
        "updated_at": config.get("updated_at"),
        "defaults": {"base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL},
    }


def _tighten_permissions(path: Path) -> None:
    """尽力收紧文件权限；失败不阻断保存（沙箱/受管环境可能不允许）。"""
    try:
        if os.name == "nt":
            import subprocess

            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", f"{os.environ.get('USERNAME', '')}:F"],
                capture_output=True, timeout=10, check=False,
            )
        else:
            path.chmod(0o600)
    except (OSError, ImportError, Exception):  # noqa: BLE001
        pass


def save(payload: dict) -> dict:
    """保存配置。

    规则：
    - `api_key` 为空字符串表示「沿用旧密钥」；显式清除请调用 clear_credentials()；
    - 协议非法时回落到 openai；
    - 模型列表去重、丢弃空 id。
    """
    config = load()

    protocol = str(payload.get("protocol") or config.get("protocol") or "openai").strip()
    if protocol not in PROTOCOLS:
        protocol = "openai"
    config["protocol"] = protocol

    base_url = str(payload.get("base_url") or "").strip()
    config["base_url"] = base_url or DEFAULT_BASE_URL.get(protocol, "")

    new_key = payload.get("api_key")
    if isinstance(new_key, str) and new_key.strip():
        config["api_key"] = new_key.strip()

    raw_models = payload.get("models")
    if isinstance(raw_models, list):
        seen: set[str] = set()
        models: list[dict] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append({
                "id": model_id,
                "display": str(item.get("display") or "").strip() or model_id,
            })
        config["models"] = models
    elif not config.get("models"):
        config["models"] = []

    config["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _tighten_permissions(CONFIG_PATH)
    return public_view()


def clear_credentials() -> dict:
    """清除密钥，保留协议、地址与模型列表。"""
    config = load()
    config["api_key"] = ""
    config["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _tighten_permissions(CONFIG_PATH)
    return public_view()
