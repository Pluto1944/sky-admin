"""账号状态推断（纯函数，无 IO）。

账号状态是 player 的固有属性，故状态推断规则内聚在 player 模块。
根据"最后报名月份"与"当前月份"推断账号状态，用于长期跟踪人员流动。
"""
from __future__ import annotations

from modules.player.config import MAYBE_LEFT_MONTHS
from shared.config.common import (
    STATUS_ACTIVE,
    STATUS_MAYBE_LEFT,
    STATUS_MISSED,
)


def period_diff(from_period: str, to_period: str) -> int:
    """计算两个 'YYYY-MM' 月份之间相差的月数（to - from）。

    非法或空输入返回 0。
    """
    try:
        fy, fm = (int(x) for x in from_period.split("-"))
        ty, tm = (int(x) for x in to_period.split("-"))
    except (ValueError, AttributeError):
        return 0
    return (ty * 12 + tm) - (fy * 12 + fm)


def infer_status(
    last_reg_period: str | None,
    current_period: str,
    registered_this_period: bool,
    maybe_left_months: int = MAYBE_LEFT_MONTHS,
) -> str:
    """推断账号状态。

    - 本月报名 -> active
    - 未报名，且距最后报名 >= maybe_left_months 个月 -> maybe_left（疑似离开）
    - 未报名，但间隔较短（漏报）-> missed
    - 从未报名过（last_reg_period 为空）且本月也没报名 -> maybe_left
    """
    if registered_this_period:
        return STATUS_ACTIVE

    if not last_reg_period:
        return STATUS_MAYBE_LEFT

    gap = period_diff(last_reg_period, current_period)
    if gap >= maybe_left_months:
        return STATUS_MAYBE_LEFT
    return STATUS_MISSED
