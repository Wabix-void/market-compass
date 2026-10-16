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
import urllib.error
import urllib.request
from typing import Protocol


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
        self.base_url = (base_url or _read_env("MARKETCOMPASS_LLM_BASE_URL")).rstrip("/")
        self.api_key = api_key or _read_env("MARKETCOMPASS_LLM_API_KEY")
        self.model = model or _read_env("MARKETCOMPASS_LLM_MODEL")
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
