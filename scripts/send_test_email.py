"""发一封测试邮件，用来验证 .env 里的 SMTP 配置是否正确。
用法:  ./.venv/bin/python scripts/send_test_email.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config
from src.logging_setup import setup_logging
from src.notifier import _send


def main() -> int:
    cfg = Config.from_env()
    logger = setup_logging(cfg.log_file, cfg.log_level)

    if not cfg.email_enabled:
        logger.error("EMAIL_ENABLED 不是 true，请先在 .env 里打开邮件通知。")
        return 2

    logger.info(f"发送测试邮件: {cfg.smtp_user} -> {cfg.smtp_to} via {cfg.smtp_host}:{cfg.smtp_port}")
    ok = _send(
        cfg,
        subject="羽毛球报名 Agent · 邮件配置测试",
        body="这是一封测试邮件。如果你收到了，说明 SMTP 配置正确，报名成功后就能收到通知了。\n",
        logger=logger,
    )
    if ok:
        logger.info("✅ 已发送。请去收件箱(和垃圾邮件箱)确认收到。")
        return 0
    logger.error("❌ 发送失败，请看上面的错误信息。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
