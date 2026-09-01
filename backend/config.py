"""全局配置：从项目根目录 .env 读取，未配置 API Key 时自动进入 Mock 模式。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # --- LLM 配置（OpenAI 兼容 API）---
    # 拿到公司的 API Key 后填到项目根目录 .env 的 OPENAI_API_KEY
    API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1").strip()
    MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat").strip()

    # 没有 Key 时走 Mock 模式（规则模拟，用于演示 Agent 全链路）
    @staticmethod
    def is_mock() -> bool:
        return not Config.API_KEY

    # --- 运行配置 ---
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))

    # Agent 沙箱目录：文件工具只允许操作该目录
    WORKSPACE = BASE_DIR / "workspace"

    # run_command 超时（秒）
    CMD_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "60"))
