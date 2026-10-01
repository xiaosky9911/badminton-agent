"""入口：python -m src [once]

    python -m src        # 长期运行(轮询)
    python -m src once   # 只扫描一次(适合定时任务/调试)
"""
from __future__ import annotations

import sys

from .agent import run_forever, run_once
from .config import Config
from .logging_setup import setup_logging
from .sheets_client import GoogleSheetsClient
from .state import State


def main() -> int:
    cfg = Config.from_env()
    logger = setup_logging(cfg.log_file, cfg.log_level)

    if not cfg.spreadsheet_id:
        logger.error("SPREADSHEET_ID 未配置，请检查 .env")
        return 2

    logger.info("Connecting to Google Sheets ...")
    client = GoogleSheetsClient(cfg.spreadsheet_id, cfg.credentials_file)
    state = State(cfg.state_db)

    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
    try:
        if mode == "once":
            run_once(client, cfg, state, logger)
        else:
            run_forever(client, cfg, state, logger)
    finally:
        state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
