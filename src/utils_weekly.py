"""周常（周几以后开始执行）相关工具：周几计算与起始日判断。"""

from datetime import datetime, timedelta


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
