"""邮件通知 (SMTP + STARTTLS)。

report_registration 会根据结果自动选择:
  - complete : “已自动报名”成功邮件(两人)
  - partial  : 成功邮件但说明只报到一人
  - failed / no_slot : “发现新场地但报名失败”异常通知
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formatdate

from .config import Config
from .models import RegistrationResult


def _send(cfg: Config, subject: str, body: str, logger) -> bool:
    if not cfg.email_enabled:
        logger.info(f"Email disabled; would send: {subject}")
        return True
    try:
        recipients = [a.strip() for a in cfg.smtp_to.split(",") if a.strip()]

        # 用 EmailMessage：自动以 UTF-8 正确编码中文标题与正文
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Date"] = formatdate(localtime=True)
        msg.set_content(body)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
            s.ehlo()
            if cfg.smtp_starttls:
                s.starttls()
                s.ehlo()
            if cfg.smtp_user:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg, from_addr=cfg.smtp_from, to_addrs=recipients)
        logger.info(f"Email sent successfully: {subject}")
        return True
    except Exception as e:  # 邮件失败不得影响报名主流程
        logger.error(f"Email send failed: {e}")
        return False


def report_registration(cfg: Config, result: RegistrationResult, logger) -> bool:
    v = result.venue
    names_line = "\n".join(f"- {n}（{result.name_status.get(n)}）" for n in cfg.register_names)

    if result.status == "complete":
        subject = "羽毛球场地已自动报名"
        body = (
            "已有新的羽毛球场地预约，系统已经自动完成报名。\n\n"
            f"日期：{v.date}（{v.day_of_week}）\n"
            f"时间：{v.start}-{v.end}\n"
            f"场地：{v.field}\n\n"
            "已报名：\n"
            + "\n".join(f"- {n}" for n in cfg.register_names)
            + "\n\n如果当天无法参加，请记得提前进入报名表删除自己的名字，以免占用其他人的名额。\n"
        )
        return _send(cfg, subject, body, logger)

    if result.status == "partial":
        got = [n for n in cfg.register_names if result.name_status.get(n) in ("registered", "already")]
        miss = [n for n in cfg.register_names if result.name_status.get(n) not in ("registered", "already")]
        subject = "羽毛球场地已自动报名（部分成功）"
        body = (
            "已有新的羽毛球场地预约，系统已尝试自动报名。\n\n"
            f"日期：{v.date}（{v.day_of_week}）\n"
            f"时间：{v.start}-{v.end}\n"
            f"场地：{v.field}\n\n"
            f"{got[0]} 已报名成功，但由于剩余位置不足，{'、'.join(miss)} 未能报名。\n\n"
            "如果当天无法参加，请记得提前进入报名表删除自己的名字，以免占用其他人的名额。\n"
        )
        return _send(cfg, subject, body, logger)

    # failed / no_slot
    subject = "发现新羽毛球场地但报名失败"
    body = (
        "检测到新的羽毛球场地，但自动报名未成功（可能已满或发生并发冲突）。\n\n"
        f"日期：{v.date}（{v.day_of_week}）\n"
        f"时间：{v.start}-{v.end}\n"
        f"场地：{v.field}\n"
        f"原因：{result.message}\n\n"
        "请手动检查报名表。\n"
    )
    return _send(cfg, subject, body, logger)
