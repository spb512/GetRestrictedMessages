"""
支付处理模块 - 负责处理支付相关功能
"""

import logging
import random
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

from db import create_new_order as db_create_new_order
from config import USDT_WALLET

# 初始化日志记录器
log = logging.getLogger("PaymentHandler")

# USDT支付相关常量
USDT_DECIMAL_PLACES = 5  # USDT支付时使用的小数位数

def generate_unique_amount(base_amount):
    """
    生成带有随机小数的唯一金额
    
    :param base_amount: 基础金额
    :return: 带有随机小数的金额
    """
    # 基础金额向下取整到小数点后两位
    base = Decimal(base_amount).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    
    # 生成3位随机小数
    random_decimal = Decimal(random.randint(0, 999)) / Decimal(1000)
    
    # 组合基础金额和随机小数
    unique_amount = base + random_decimal
    
    # 格式化为指定的小数位数
    formatted_amount = unique_amount.quantize(Decimal(f'0.{USDT_DECIMAL_PLACES * "0"}'), rounding=ROUND_DOWN)
    
    return formatted_amount

def create_new_order(user_id, package_name, amount, quota_amount):
    """
    创建新的支付订单
    
    :param user_id: 用户ID
    :param package_name: 套餐名称
    :param amount: 金额
    :param quota_amount: 额度数量
    :return: (订单ID, 唯一金额)
    """
    try:
        # 生成唯一的支付金额
        unique_amount = generate_unique_amount(amount)
        
        # 创建订单
        order_id = db_create_new_order(
            user_id=user_id,
            package_name=package_name,
            amount=float(unique_amount),
            quota_amount=quota_amount,
            payment_address=USDT_WALLET
        )
        
        if order_id:
            log.info(f"创建新订单: ID={order_id}, 用户={user_id}, 套餐={package_name}, 金额={unique_amount}")
            return order_id, unique_amount
        else:
            log.error(f"创建订单失败: 用户={user_id}, 套餐={package_name}")
            return None, None
    
    except Exception as e:
        log.exception(f"创建订单时出错: {e}")
        return None, None

def format_payment_instructions(order_id, amount, package_name, quota_amount):
    """
    格式化支付说明
    
    :param order_id: 订单ID
    :param amount: 金额
    :param package_name: 套餐名称
    :param quota_amount: 额度数量
    :return: 格式化的支付说明
    """
    return f"""💰 支付信息 💰

🛒 套餐: {package_name}
🔢 额度: {quota_amount} 次
💲 金额: {amount} USDT
🆔 订单号: {order_id}

💳 支付地址 (USDT-TRC20):
`{USDT_WALLET}`

⚠️ 重要提示:
1. 必须发送准确金额 ({amount} USDT)
2. 必须使用TRC20网络
3. 支付完成后系统将自动处理

✅ 支付成功后，您可以使用 /check {order_id} 命令查询订单状态。
""" 