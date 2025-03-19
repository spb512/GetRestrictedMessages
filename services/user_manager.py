"""
用户管理模块 - 负责用户相关的功能
"""

import logging
from datetime import datetime

from config import RANGE
from db import (
    get_user_quota, decrease_user_quota, add_paid_quota
)

# 初始化日志记录器
log = logging.getLogger("UserManager")

async def check_user_quota(user_id):
    """
    检查用户的剩余配额
    
    :param user_id: 用户ID
    :return: (剩余付费配额, 剩余免费配额)
    """
    free_quota, paid_quota, _ = get_user_quota(user_id)
    return paid_quota, free_quota

async def get_user_info(user_id):
    """
    获取用户信息
    
    :param user_id: 用户ID
    :return: 用户信息字符串
    """
    free_quota, paid_quota, total_used = get_user_quota(user_id)
    
    info = f"""📊 用户信息 📊

🆔 用户ID: {user_id}

💰 付费次数: {paid_quota}
🎁 免费次数: {free_quota}
📈 已用总数: {total_used}

每条消息消耗1次转发额度。
免费用户每天可获得{RANGE}次免费转发机会。
"""
    return info

async def add_user_quota(user_id, quota_amount, is_paid=True):
    """
    增加用户的付费配额
    
    :param user_id: 用户ID
    :param quota_amount: 配额数量
    :param is_paid: 是否是付费配额
    :return: 成功返回True，失败返回False
    """
    try:
        if is_paid:
            add_paid_quota(user_id, quota_amount)
            log.info(f"增加用户 {user_id} 的付费配额: +{quota_amount}")
            return True
        else:
            log.warning(f"不支持增加免费配额，免费配额每日重置")
            return False
    except Exception as e:
        log.exception(f"增加用户配额时出错: {e}")
        return False

async def use_quota(user_id, amount=1):
    """
    使用用户配额，优先使用免费配额
    
    :param user_id: 用户ID
    :param amount: 使用数量，默认为1
    :return: (成功使用配额数量, 使用的免费配额数量, 使用的付费配额数量, 是否有足够配额)
    """
    free_quota, paid_quota, _ = get_user_quota(user_id)
    total_available = paid_quota + free_quota
    
    if total_available < amount:
        log.warning(f"用户 {user_id} 配额不足: 需要 {amount}，可用 {total_available}")
        return 0, 0, 0, False
    
    # 优先使用免费配额
    used_free = min(free_quota, amount)
    used_paid = amount - used_free
    
    decrease_user_quota(user_id)
    log.info(f"用户 {user_id} 使用了 {used_free} 免费配额和 {used_paid} 付费配额")
    return amount, used_free, used_paid, True 