"""失败脚本邮件通知：先调 collect_log 收集当日失败脚本，有失败则以 SMTP 发送邮件。

本模块是"邮件通知"职责的入口，依赖 collect_log（只做日志收集与打印）来判定哪些游戏失败，
并复用其汇总表格与诊断文本（报错信息 + 日志尾部）。其余仅依赖标准库与 yaml。
发送失败 / 配置缺失时仅告警，不影响脚本链其余环节。
"""

import logging
import os
import smtplib
import sys
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

# 把项目根加入 sys.path，以便 import src.log。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src.log.monitor as collect_log
from ruamel.yaml import YAML

_yaml = YAML()

logger = logging.getLogger(__name__)

# QQ 邮箱 SMTP 服务（收发同号，自己发给自己），参考 OneDragon-ScriptChainer 的服务表。
_SMTP_HOST = "smtp.qq.com"
_SMTP_PORT = 465
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 20
_SENDER_NAME = "OneDragon-Helper"


def _load_mail_config() -> dict | None:
    """读取 config/notify_mail.yml 的 SMTP 配置；缺失或字段为空返回 None（调用方跳过）。

    配置由用户手写且被 .gitignore 忽略，字段缺失属可恢复情况，用告警而非断言。
    """
    config_path = Path(collect_log._get_root_dir()) / "config" / "notify_mail.yml"
    if not config_path.exists():
        logger.warning("[notify_mail] 邮件配置不存在，跳过失败通知: %s", config_path)
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            data = _yaml.load(f) or {}
    except Exception:
        logger.exception(
            "[notify_mail] 读取邮件配置失败，跳过失败通知: %s", config_path
        )
        return None

    email = data.get("email", "")
    password = data.get("password", "")
    if not email or not password:
        logger.warning(
            "[notify_mail] 邮件配置缺少 email/password，跳过失败通知: %s", config_path
        )
        return None

    return {"email": email, "password": password}


def _build_subject(targets: list[str]) -> str:
    """邮件标题：列出全部存在报错日志的游戏名。"""
    return "[OneDragon-Helper] 脚本运行报错: " + "、".join(targets)


def _collapse_repeated_lines(text: str) -> str:
    """折叠连续重复行：连续相同的行只保留一行并标注重复次数（避免日志刷屏占满邮件）。"""
    lines = text.splitlines()
    if not lines:
        return text

    collapsed: list[str] = []
    prev = lines[0]
    count = 1
    for line in lines[1:]:
        if line == prev:
            count += 1
            continue
        collapsed.append(f"{prev}（重复 {count} 次）" if count > 1 else prev)
        prev = line
        count = 1
    collapsed.append(f"{prev}（重复 {count} 次）" if count > 1 else prev)
    return "\n".join(collapsed)


def _build_body(report: str, diagnostic: str) -> str:
    """邮件正文：运行日期 + 整表汇总表格 + 各脚本报错明细与日志尾部（与控制台同结构）。"""
    sections = [
        f"运行日期: {datetime.now():%Y-%m-%d}",
        "",
        "脚本运行状况汇总表格：",
        "",
        report,
        "",
    ]
    if diagnostic:
        sections.append(diagnostic)
    else:
        sections.append("本次无脚本报错。")
    return "\n".join(sections)


def _send_mail(email: str, password: str, subject: str, body: str) -> bool:
    """通过 QQ 邮箱 SMTP（SSL 465）发送邮件；返回是否成功。

    SMTP 连接 / 登录 / 发送属外部 IO，异常为可恢复情况，捕获后告警返回 False。
    """
    message = MIMEText(body, "plain", "utf-8")
    # _SENDER_NAME 为纯 ASCII，可直接作显示名；无需经 Header 编码
    message["From"] = formataddr((_SENDER_NAME, email))
    message["To"] = formataddr((_SENDER_NAME, email))
    message["Subject"] = Header(subject, "utf-8")

    try:
        server = smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS)
        try:
            server.login(email, password)
            server.sendmail(email, email, message.as_bytes())
        finally:
            server.close()
    except Exception:
        logger.exception("[notify_mail] SMTP 发送邮件失败")
        return False

    logger.info("[notify_mail] 邮件发送成功: %s", subject)
    return True


def notify_failed_games() -> None:
    """收集当日存在报错日志的脚本，有报错则 SMTP 发送邮件通知。

    静默调 collect_log.parse_logs 拿到需通知列表，再补取日志详情发送；
    无报错 / 配置缺失 / 发送失败均不抛异常。
    """
    result = collect_log.parse_logs(do_log=False)
    notify_list = result.get("notify", [])
    if not notify_list:
        logger.info("[notify_mail] 无报错脚本，无需发送邮件")
        return

    mail_config = _load_mail_config()
    if mail_config is None:
        return

    # 复用 collect_log 的诊断文本（报错信息在前、日志尾部在后），与控制台同结构；
    # 邮件侧传入 collapse_fn 折叠连续重复行，避免日志刷屏占满邮件。
    entries = result["entries"]
    diagnostic = collect_log._format_diagnostic_sections(
        entries, collapse_fn=_collapse_repeated_lines
    )
    subject = _build_subject(notify_list)
    body = _build_body(result["report"], diagnostic)

    if _send_mail(mail_config["email"], mail_config["password"], subject, body):
        logger.info("[notify_mail] 已发送报错通知邮件: %s", "、".join(notify_list))
    else:
        logger.warning("[notify_mail] 报错通知邮件发送失败")


if __name__ == "__main__":
    notify_failed_games()
