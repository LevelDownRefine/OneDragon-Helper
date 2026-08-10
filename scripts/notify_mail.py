"""失败脚本邮件通知：先调 collect_log 收集当日失败脚本，有失败则以 SMTP 发送邮件。

本模块是"邮件通知"职责的入口，依赖 collect_log（只做日志收集与打印）来判定哪些游戏失败。
与 collect_log / rerun 一致，本模块本身不 import 任何项目（src/）模块，仅依赖标准库与 yaml。
发送失败 / 配置缺失时仅告警，不影响脚本链其余环节。
"""

import logging
import smtplib
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

import collect_log
import yaml

logger = logging.getLogger(__name__)

# QQ 邮箱 SMTP 服务（收发同号，自己发给自己），参考 OneDragon-ScriptChainer 的服务表。
_SMTP_HOST = "smtp.qq.com"
_SMTP_PORT = 465
# socket 超时：防止 SMTP 连接挂起时脚本无限阻塞、被 runner 按 run_timeout 强杀
_SMTP_TIMEOUT_SECONDS = 20
_SENDER_NAME = "OneDragon-Helper"


def _load_mail_config() -> dict | None:
    """读取 config/notify_mail.yml 的 SMTP 配置；缺失或字段为空时返回 None（调用方跳过）。

    notify_mail.yml 已被 .gitignore 忽略，授权码仅存本机。字段缺失属可恢复情况，
    用告警而非断言（配置文件由用户手写，可能未填）。
    """
    config_path = Path(collect_log._get_root_dir()) / "config" / "notify_mail.yml"
    if not config_path.exists():
        logger.warning("[notify_mail] 邮件配置不存在，跳过失败通知: %s", config_path)
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        logger.exception("[notify_mail] 读取邮件配置失败，跳过失败通知: %s", config_path)
        return None

    email = data.get("email", "")
    password = data.get("password", "")
    if not email or not password:
        logger.warning("[notify_mail] 邮件配置缺少 email/password，跳过失败通知: %s", config_path)
        return None

    return {"email": email, "password": password}


def _collect_failed_details(targets: list[str]) -> list[dict]:
    """对每个失败游戏补取日志路径与尾部内容（collect_log.parse_logs 只返回名字列表）。

    从 config.yml 反查 script_path 后调用 collect_log.parse_log，解析到的内容
    与 rerun 重跑时面对的是同一份当日日志。config.yml 读取失败属可恢复情况，
    告警后返回空列表（通知环节保证不中断脚本链）。
    """
    config_path = Path(collect_log._get_root_dir()) / "config" / "config.yml"
    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception:
        logger.exception("[notify_mail] 读取 config.yml 失败，本次仅通知失败名单: %s", config_path)
        return []

    script_list = config_data.get("script_list", [])
    details: list[dict] = []
    for name in targets:
        script_path = ""
        for script in script_list:
            if script.get("display_name") == name:
                script_path = script.get("script_path", "")
                break
        result = collect_log.parse_log(name, script_path)
        assert "status" in result and "log_path" in result
        log_content = ""
        if "log_content" in result:
            log_content = result["log_content"]
        details.append(
            {
                "display_name": name,
                "status": result["status"],
                "log_path": result["log_path"],
                "log_content": log_content,
            }
        )
    return details


def _build_subject(targets: list[str]) -> str:
    """邮件标题：列出全部失败游戏名。"""
    return "[OneDragon-Helper] 脚本运行失败: " + "、".join(targets)


def _collapse_repeated_lines(text: str) -> str:
    """折叠连续重复行：连续相同的行只保留一行并标注重复次数。

    游戏日志尾部常有海量重复行（如 ok 系列的 FeatureSet:read_from_json 刷屏），
    原样进邮件会占满 2000 字符、淹没有效信息。仅折叠"连续"重复，保留顺序与其余行。
    """
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


def _build_body(details: list[dict]) -> str:
    """邮件正文：运行日期 + 每个失败游戏的名称、状态、日志路径与日志尾部内容。"""
    sections = [f"运行日期: {datetime.now():%Y-%m-%d}", "", "以下脚本运行失败，请检查：", ""]
    for detail in details:
        sections.append(f"【{detail['display_name']}】状态: {detail['status']}")
        if detail["log_path"]:
            sections.append(f"日志: {detail['log_path']}")
        if detail["log_content"]:
            sections.append("--- 日志尾部 ---")
            sections.append(_collapse_repeated_lines(detail["log_content"]))
        sections.append("")
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
    """收集当日失败 / 无日志游戏，有失败则发送邮件通知。

    先调 collect_log.parse_logs(do_log=False) 静默拿到需通知列表（FAILED + NO_LOG），
    再补取日志详情并 SMTP 发送。无失败 / 配置缺失 / 发送失败均不抛异常。
    """
    targets = collect_log.parse_logs(do_log=False)
    if not targets:
        logger.info("[notify_mail] 无失败脚本，无需发送邮件")
        return

    mail_config = _load_mail_config()
    if mail_config is None:
        return

    details = _collect_failed_details(targets)
    subject = _build_subject(targets)
    body = _build_body(details)

    if _send_mail(mail_config["email"], mail_config["password"], subject, body):
        logger.info("[notify_mail] 已发送失败通知邮件: %s", "、".join(targets))
    else:
        logger.warning("[notify_mail] 失败通知邮件发送失败")


if __name__ == "__main__":
    notify_failed_games()
