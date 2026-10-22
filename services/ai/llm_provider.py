"""LLM Provider 接口（预留）。

默认使用离线模板（NullProvider），此时 AI 建议由 `advisor.py` 的规则+模板生成。
配置以下环境变量后自动切换到真实模型，无需改动任何业务代码：

    MARKETCOMPASS_LLM_BASE_URL   # 例如 https://api.example.com/v1
    MARKETCOMPASS_LLM_API_KEY
    MARKETCOMPASS_LLM_MODEL      # 例如 deepseek-chat

约束：模型只负责把已算好的指标结果组织成自然语言，禁止生成任何新数字。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol

from services.ai import config_store


def _read_env(name: str) -> str:
    """读取配置项：先查进程环境变量，Windows 下再兜底查用户级注册表。

    为什么需要兜底：环境变量往往是在某些长驻进程（IDE、终端宿主、Agent 运行时）启动之后才
    设置的，由这些进程派生的子进程仍然只继承旧环境，于是出现"明明配好了却显示 offline-template"
    的假故障。注册表 `HKCU\\Environment` 保存的是最新值，查它可以消除这一层不确定性。
    """
    value = os.environ.get(name, "")
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg
        except ImportError:
            return ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                stored, _ = winreg.QueryValueEx(key, name)
                return str(stored or "")
        except OSError:
            return ""
    return ""


class LLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str | None: ...


class NullProvider:
    """离线兜底：不调用任何外部服务，返回 None 让上层走模板。"""

    name = "offline-template"

    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str | None:
        return None


class OpenAICompatProvider:
    """OpenAI 兼容协议的最小实现（仅标准库）。"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int = 60) -> None:
        # 优先级：显式传参 > 界面配置（BYOK）> 环境变量 > 注册表
        stored = config_store.effective()
        self.base_url = (base_url or stored.get("base_url")
                         or _read_env("MARKETCOMPASS_LLM_BASE_URL")).rstrip("/")
        self.api_key = (api_key or stored.get("api_key")
                        or _read_env("MARKETCOMPASS_LLM_API_KEY"))
        self.model = (model or stored.get("model")
                      or _read_env("MARKETCOMPASS_LLM_MODEL")
                      or config_store.DEFAULT_MODEL)
        self.timeout = timeout
        self.name = f"openai-compat:{self.model or 'unset'}"

    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str | None:
        if not self.available():
            return None
        payload = json.dumps({
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError):
            return None


def get_provider() -> LLMProvider:
    provider = OpenAICompatProvider()
    return provider if provider.available() else NullProvider()


# ---------------------------------------------------------------------------
# 连接测试（供 BYOK 接入面板使用）
# ---------------------------------------------------------------------------
def _redact(text: str, api_key: str) -> str:
    """把错误信息里的密钥替换掉，避免随响应回流到前端。"""
    if not text:
        return text
    if api_key and api_key in text:
        text = text.replace(api_key, f"{api_key[:3]}***")
    return text


def test_connection(protocol: str, base_url: str, api_key: str, model: str,
                    timeout: int = 20) -> dict:
    """用最小请求验证「地址 + 密钥 + 模型」是否可用。

    返回 ``{ok, latency_ms, error?, detail?}``；detail 已脱敏。
    """
    if not base_url or not api_key:
        return {"ok": False, "error": "缺少 API 地址或密钥"}

    started = time.perf_counter()
    base = base_url.rstrip("/")

    if protocol == "anthropic":
        url = f"{base}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        url = f"{base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    body = {"model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}]}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latency = round((time.perf_counter() - started) * 1000)
        ok = isinstance(payload, dict) and ("choices" in payload or "content" in payload)
        return {
            "ok": ok,
            "latency_ms": latency,
            "error": None if ok else "响应格式不符合预期",
            "detail": None if ok else _redact(
                json.dumps(payload, ensure_ascii=False)[:400], api_key),
        }
    except urllib.error.HTTPError as exc:
        code_map = {401: "密钥无效", 403: "无权限", 404: "地址或模型不存在", 429: "请求过于频繁"}
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")[:400]
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": False,
            "error": code_map.get(exc.code, f"HTTP {exc.code}"),
            "detail": _redact(detail, api_key),
        }
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "响应不是合法 JSON", "detail": _redact(str(exc), api_key)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": "请检查网络与地址", "detail": _redact(str(exc), api_key)}
