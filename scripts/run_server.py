"""启动后端服务与看板。

用法：
    python scripts/run_server.py
默认地址 http://127.0.0.1:8787 ，可用环境变量 MARKETCOMPASS_PORT 覆盖端口。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.server import main  # noqa: E402

if __name__ == "__main__":
    main()
