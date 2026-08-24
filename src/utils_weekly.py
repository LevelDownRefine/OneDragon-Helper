"""周常（周几以后开始执行）相关工具：周几计算与起始日判断。"""

from datetime import datetime, timedelta


def next_target_datetime(target_time: str, now: datetime | None = None) -> datetime:
    """返回下一个等于 target_time 的时刻：今天未到取今天，已过取明天（跨午夜）。

    Args:
        target_time: ``"HH:MM"`` 形式的目标时刻。
        now: 基准时间，默认当前时间（可注入以便测试）。

    Returns:
        下一个 ``target_time`` 对应的 ``datetime``。
    """
    hours, minutes = (int(x) for x in target_time.split(":"))
    now = now or datetime.now()
    candidate = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if now < candidate:
        return candidate
    return candidate + timedelta(days=1)


def get_week_num() -> int:
    """返回星期数字：0周一 ~ 6周日（凌晨 4 点为界，4 点前归前一天）。

    周常「周几以后开始执行」与 weekly_timeouts 的「当天」判定共用此规则，
    各脚本统一以凌晨 4 点为新一天起点。
    """
    return (datetime.now() - timedelta(hours=4)).weekday()


def is_weekly_start_reached(start_day: int) -> bool:
    """判断今天是否已到周常起始日（今天周几 >= 起始日）。

    Args:
        start_day: 周常起始日（1=周一 ~ 7=周日）。

    Returns:
        True 表示今天起可以执行周常。
    """
    assert 1 <= start_day <= 7, f"[utils_weekly] 非法周常起始日: {start_day}"
    return get_week_num() + 1 >= start_day
