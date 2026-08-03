"""开发启动脚本。

用法：
    cd sky-admin
    python -m api_server.run

或：
    uvicorn api_server.app:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import uvicorn


def main():
    uvicorn.run(
        "api_server.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
