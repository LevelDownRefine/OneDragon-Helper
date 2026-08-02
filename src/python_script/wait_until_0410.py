"""等待至下一个凌晨 4:10，再结束（由 ScriptChainer 作为脚本链的一项调用）。

作为 config.yml 的一个脚本项时，它会在启动时阻塞，直到当天或次日的 04:10，
之后脚本链继续执行后续项。仅依赖标准库，不 import 任何项目模块，可独立运行。

用法：
    python src/python_script/wait_until_0410.py
"""

import datetime
import logging
import time

logger = logging.getLogger(__name__)

TARGET_HOUR = 4
TARGET_MINUTE = 10


def next_trigger() -> datetime.datetime:
    """返回下一个 04:10 的时间点：今天未到则今天，已过则明天"""
    now = datetime.datetime.now()
    today = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    if now < today:
        return today
    return today + datetime.timedelta(days=1)


def wait_until_target() -> None:
    """阻塞直到下一个 04:10，然后返回（脚本链继续执行后续项）

    每 30 秒轮询一次，兼容系统休眠：唤醒后会立即判断是否已到点。
    """
    target = next_trigger()
    logger.info(f"等待至 {target:%Y-%m-%d %H:%M:%S}")
    while datetime.datetime.now() < target:
        time.sleep(30)
    logger.info("已到 04:10，继续")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    wait_until_target()
