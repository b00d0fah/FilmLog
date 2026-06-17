from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import TIMEZONE


def _local_timezone():
    try:
        return ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        if TIMEZONE == "Asia/Shanghai":
            return timezone(timedelta(hours=8))
        return datetime.now().astimezone().tzinfo


def local_timestamp() -> str:
    return datetime.now(_local_timezone()).strftime("%Y-%m-%d %H:%M:%S")
