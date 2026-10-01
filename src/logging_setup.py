"""日志配置：同时输出到控制台和文件，时间格式与需求示例一致 [HH:MM:SS]。"""
from __future__ import annotations

import logging
import os
import sys


class _BracketTime(logging.Formatter):
    default_time_format = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.default_time_format)
        return f"[{ts}] {record.getMessage()}"


def setup_logging(log_file: str = "./data/agent.log", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("badminton")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = _BracketTime()

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.propagate = False
    return logger
