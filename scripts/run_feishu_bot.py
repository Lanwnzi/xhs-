#!/usr/bin/env python
"""飞书机器人入口脚本。

从环境变量读取飞书配置并启动机器人长连接。

用法：
    python scripts/run_feishu_bot.py

环境变量：
    FEISHU_BOT_ENABLED      -- 设为 true 启用
    FEISHU_APP_ID           -- 飞书应用 ID
    FEISHU_APP_SECRET       -- 飞书应用 Secret
    PUBLIC_REPORT_BASE_URL  -- 报告公开访问地址（默认 http://127.0.0.1:8000）
"""

from __future__ import annotations

import logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
from src.integrations.feishu_bot import create_bot_from_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    load_dotenv()
    bot = create_bot_from_env()
    if bot is None:
        sys.exit(1)
    print("飞书机器人启动中 ...")
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n收到停止信号，关闭机器人 ...")
        bot.stop()
