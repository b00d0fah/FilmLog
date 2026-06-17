from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
_db_path = os.getenv("FILMLOG_DB_PATH", os.path.join(BASE_DIR, "filmlog.db"))
DB_PATH = _db_path if os.path.isabs(_db_path) else os.path.join(BASE_DIR, _db_path)
SECRET_KEY = os.getenv("FILMLOG_SECRET_KEY", "filmlog-local-demo-secret")
MAX_CONTENT_LENGTH = _int_env("FILMLOG_MAX_CONTENT_MB", 600) * 1024 * 1024
HOST = os.getenv("FILMLOG_HOST", "127.0.0.1")
PORT = _int_env("FILMLOG_PORT", 5000)
DEBUG = os.getenv("FILMLOG_DEBUG", "1").lower() in {"1", "true", "yes", "on"}
TIMEZONE = os.getenv("TZ") or os.getenv("FILMLOG_TIMEZONE", "Asia/Shanghai")
