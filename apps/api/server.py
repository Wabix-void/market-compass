"""商情罗盘 MarketCompass — 后端 API 服务（纯标准库实现）。

无需任何第三方依赖：python apps/api/server.py 即可启动。
启动后访问 http://127.0.0.1:8787 打开看板。
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ai import advisor             # noqa: E402
from services.ai.llm_provider import get_provider  # noqa: E402
from services.analytics import market_analysis, queries      # noqa: E402
from services.etl import pipeline           # noqa: E402

WEB_ROOT = PROJECT_ROOT / "apps" / "web"
DEFAULT_PORT = int(os.environ.get("MARKETCOMPASS_PORT", "8787"))


def _json_default(value):
    return str(value)


class Handler(BaseHTTPRequestHandler):
    server_version = "MarketCompass/0.1"

    # ---------------- 基础工具 ----------------
    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status=status)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_error_json("not found", status=404)
            return
        mime, _ = mimetypes.guess_type(str(path))
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime or 'application/octet-stream'}"
                         + ("; charset=utf-8" if (mime or "").startswith(("text/", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # 保持终端输出简洁
        if os.environ.get("MARKETCOMPASS_VERBOSE") == "1":
            super().log_message(fmt, *args)

    # ---------------- 路由 ----------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}

        if route.startswith("/api/"):
            self._handle_api(route, params)
            return

        # 静态资源
        relative = unquote(route).lstrip("/") or "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self._send_error_json("invalid path", status=403)
            return
        self._send_file(candidate)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_error_json("invalid json body")
            return

        if parsed.path == "/api/diag":
            # 运维诊断：一句话回答"当前跑的是哪个版本 / AI 开没开 / 端口对不对"。
            # （排查端口被残留进程占用时极其有用，故保留为正式端点）
            provider = get_provider()
            self._send_json({
                "module_file": __file__,
                "server_version": self.server_version,
                "port": self.server.server_address[1],
                "has_ask_handler": hasattr(self, "_handle_ask"),
                "llm_provider": provider.name,
                "llm_available": provider.available(),
                "received_path": self.path,
            })
            return
        if parsed.path == "/api/advice":
            self._handle_advice(payload)
            return
        if parsed.path == "/api/market-analysis":
            self._handle_market_analysis(payload)
            return
        if parsed.path == "/api/ask":
            self._handle_ask(payload)
            return
        self._send_error_json("not found", status=404)

    # ---------------- API 实现 ----------------
    def _handle_api(self, route: str, params: dict) -> None:
        category_id = params.get("category_id") or None
        try:
            days = int(params.get("days", 56))
        except ValueError:
            days = 56

        conn = pipeline.connect()
        try:
            if route == "/api/health":
                self._send_json({"status": "ok", "latest_date": queries.latest_date(conn)})

            elif route == "/api/meta":
                self._send_json({
                    "categories": queries.list_categories(conn),
                    "platforms": [dict(row) for row in conn.execute(
                        "SELECT platform_id, name, source_type, compliance_note FROM dim_platform"
                    ).fetchall()],
                    "latest_date": queries.latest_date(conn),
                    "period": queries.window(conn, days),
                    "llm_provider": get_provider().name,
                    "metric_note": "SPS 为公开信号推导的销量代理指标，非平台真实销量",
                })

            elif route == "/api/overview":
                self._send_json(queries.overview(conn, category_id, days))

            elif route == "/api/trend":
                self._send_json(queries.daily_trend(conn, category_id, days))

            elif route == "/api/price-bands":
                self._send_json(queries.price_bands(conn, category_id, days))

            elif route == "/api/subcategories":
                self._send_json(queries.subcategory_ranking(conn, days))

            elif route == "/api/products":
                limit = int(params.get("limit", 30))
                self._send_json(queries.product_ranking(
                    conn, category_id, params.get("q"), params.get("sort", "sps"), limit, days))

            elif route.startswith("/api/products/"):
                product_id = route[len("/api/products/"):]
                detail = queries.product_detail(conn, product_id)
                if detail is None:
                    self._send_error_json("product not found", status=404)
                else:
                    self._send_json(detail)

            elif route == "/api/clusters":
                self._send_json(queries.cluster_list(conn))

            elif route == "/api/resolve":
                text = params.get("q", "")
                if not text:
                    self._send_error_json("缺少参数 q")
                else:
                    self._send_json(market_analysis.resolve(conn, text))

            elif route == "/api/audit":
                self._send_json(queries.audit_log(conn))

            else:
                self._send_error_json("unknown api route", status=404)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(f"{type(exc).__name__}: {exc}", status=500)
        finally:
            conn.close()

    def _handle_advice(self, payload: dict) -> None:
        conn = pipeline.connect()
        try:
            result = advisor.advise(
                conn,
                category_id=payload.get("category_id") or None,
                budget=float(payload.get("budget", 150)),
                risk=str(payload.get("risk", "medium")),
                goal=str(payload.get("goal", "选品")),
            )
            self._send_json(result)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(f"{type(exc).__name__}: {exc}", status=500)
        finally:
            conn.close()

    def _handle_market_analysis(self, payload: dict) -> None:
        query = str(payload.get("query", "")).strip()
        category_id = str(payload.get("category_id") or "").strip() or None
        if not query and not category_id:
            self._send_error_json("query 不能为空")
            return
        conn = pipeline.connect()
        try:
            result = advisor.analyze_market_query(
                conn,
                query,
                budget=float(payload.get("budget", 150)),
                risk=str(payload.get("risk", "medium")),
                goal=str(payload.get("goal", "行情分析")),
                category_id=category_id,
            )
            self._send_json(result)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(f"{type(exc).__name__}: {exc}", status=500)
        finally:
            conn.close()

    def _handle_ask(self, payload: dict) -> None:
        """AI 追问：基于已算好的指标作答，并对回答中的数字做溯源校验。

        未配置模型时返回 note（而非报错），前端会给出友好提示 ——
        行情分析与证据链功能不受影响，AI 是增强而非依赖。
        """
        query = str(payload.get("query") or "").strip()
        question = str(payload.get("question") or "").strip()
        category_id = str(payload.get("category_id") or "").strip() or None
        if not query or not question:
            self._send_error_json("缺少参数 query 或 question")
            return

        conn = pipeline.connect()
        try:
            self._send_json(advisor.answer_question(conn, query, question,
                                                    category_id=category_id))
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(f"{type(exc).__name__}: {exc}", status=500)
        finally:
            conn.close()


def create_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    port = int(os.environ.get("MARKETCOMPASS_PORT", str(DEFAULT_PORT)))
    server = create_server(port)
    print(f"商情罗盘 MarketCompass 已启动 → http://127.0.0.1:{port}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
