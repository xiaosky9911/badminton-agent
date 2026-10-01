"""集中配置：从 .env / 环境变量加载。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 项目根目录 = src 的上一级。据此定位 .env 与相对路径，使程序与"当前工作目录"无关
# （Windows 计划任务、Linux systemd 等后台方式启动时 cwd 往往不是项目目录）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # dotenv 未安装时也能靠系统环境变量运行
    pass

from .a1 import a1_to_col


def _resolve_path(p: str) -> str:
    """相对路径一律相对项目根目录解析，避免后台服务因工作目录不同而找不到文件。"""
    pp = Path(p)
    return str(pp if pp.is_absolute() else (PROJECT_ROOT / pp))


def _get(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v


def _get_int(name: str, default: int) -> int:
    raw = _get(name, "")
    return int(raw) if raw else default


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name, "").lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


@dataclass
class Config:
    # Google Sheets
    spreadsheet_id: str = ""
    sheet_name: str = "Sheet1"
    credentials_file: str = "./credentials/service_account.json"

    # 表格结构
    player_first_col: str = "E"
    player_count: int = 24
    header_row: int = 2
    data_start_row: int = 3
    max_data_rows: int = 200

    # 报名对象
    register_names: List[str] = field(default_factory=list)

    # 时间
    timezone: str = "Europe/Brussels"
    default_year: Optional[int] = None

    # 轮询
    poll_interval_seconds: int = 20
    poll_jitter_seconds: int = 5

    # 并发/写入
    max_retries: int = 5
    write_retry_jitter_ms_min: int = 50
    write_retry_jitter_ms_max: int = 400

    # 状态与日志
    state_db: str = "./data/state.db"
    log_file: str = "./data/agent.log"
    log_level: str = "INFO"

    # 安全
    dry_run: bool = True

    # 邮件
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    # 派生
    player_first_col_index: int = 5  # 计算得到

    @property
    def player_last_col_index(self) -> int:
        return self.player_first_col_index + self.player_count - 1

    @classmethod
    def from_env(cls) -> "Config":
        default_year_raw = _get("DEFAULT_YEAR", "")
        cfg = cls(
            spreadsheet_id=_get("SPREADSHEET_ID"),
            sheet_name=_get("SHEET_NAME", "Sheet1"),
            credentials_file=_resolve_path(_get("GOOGLE_CREDENTIALS_FILE", "./credentials/service_account.json")),
            player_first_col=_get("PLAYER_FIRST_COL", "E"),
            player_count=_get_int("PLAYER_COUNT", 24),
            header_row=_get_int("HEADER_ROW", 2),
            data_start_row=_get_int("DATA_START_ROW", 3),
            max_data_rows=_get_int("MAX_DATA_ROWS", 200),
            register_names=[n.strip() for n in _get("REGISTER_NAMES", "").split(",") if n.strip()],
            timezone=_get("TIMEZONE", "Europe/Brussels"),
            default_year=int(default_year_raw) if default_year_raw else None,
            poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 20),
            poll_jitter_seconds=_get_int("POLL_JITTER_SECONDS", 5),
            max_retries=_get_int("MAX_RETRIES", 5),
            write_retry_jitter_ms_min=_get_int("WRITE_RETRY_JITTER_MS_MIN", 50),
            write_retry_jitter_ms_max=_get_int("WRITE_RETRY_JITTER_MS_MAX", 400),
            state_db=_resolve_path(_get("STATE_DB", "./data/state.db")),
            log_file=_resolve_path(_get("LOG_FILE", "./data/agent.log")),
            log_level=_get("LOG_LEVEL", "INFO"),
            dry_run=_get_bool("DRY_RUN", True),
            email_enabled=_get_bool("EMAIL_ENABLED", False),
            smtp_host=_get("SMTP_HOST"),
            smtp_port=_get_int("SMTP_PORT", 587),
            smtp_starttls=_get_bool("SMTP_STARTTLS", True),
            smtp_user=_get("SMTP_USER"),
            smtp_password=_get("SMTP_PASSWORD"),
            smtp_from=_get("SMTP_FROM"),
            smtp_to=_get("SMTP_TO"),
        )
        if not cfg.register_names:
            raise ValueError("REGISTER_NAMES 未配置：请在 .env 里填写要报名的名字，逗号分隔，例如 REGISTER_NAMES=alice,bob")
        cfg.player_first_col_index = a1_to_col(cfg.player_first_col)
        return cfg
