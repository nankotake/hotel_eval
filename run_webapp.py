"""run_webapp.py —— 启动 hotel_eval 可视化界面（FastAPI）

用法：
    python run_webapp.py
然后浏览器打开 http://127.0.0.1:8000

可选环境变量：
    WEBAPP_HOST   默认 127.0.0.1
    WEBAPP_PORT   默认 8000
"""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("WEBAPP_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBAPP_PORT", "8000"))
    uvicorn.run("hotel_eval.webapp.app:app", host=host, port=port, reload=False)
