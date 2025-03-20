"""
任务调度模块 - 负责各种定时任务的执行
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import aiohttp

from config import TRANSACTION_CHECK_INTERVAL, ADMIN_ID
from db import (
    get_all_pending_orders, update_order_last_checked,
    cancel_expired_order, complete_order, get_order_by_id,
    reset_all_free_quotas
)

# 初始化日志记录器
log = logging.getLogger("TaskScheduler")


async def notify_user_order_completed(order, bot_client):
    """通知用户订单已完成"""
    # 解包订单信息
    # order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
    order_id = order[0]
    user_id = order[1]
    package_name = order[2]
    quota = order[4]

    try:
        notification = f"""🎉 您的订单已完成 🎉

🆔 订单号: {order_id}
📦 套餐: {package_name}
🔢 已增加次数: {quota}次

您可以通过 /user 查看当前可用次数。
"""
        await bot_client.send_message(int(user_id), notification)
    except Exception as e:
        log.error(f"通知用户订单完成失败: {e}")


async def check_trc20_transaction(order_id, wallet_address, bot_client, trongrid_api_key, usdt_contract):
    """
    检查指定钱包地址是否收到了TRC20 USDT转账，通过查询订单ID或金额匹配

    :param order_id: 订单ID，用于检查交易备注
    :param wallet_address: 接收付款的钱包地址
    :param bot_client: Telegram机器人客户端
    :param trongrid_api_key: TronGrid API密钥
    :param usdt_contract: USDT合约地址
    :return: 如果匹配到交易，返回True，否则返回False
    """
    if not trongrid_api_key:
        log.warning("未配置TRONGRID_API_KEY，无法自动检查交易")
        return False

    # 从订单获取详细信息
    order = get_order_by_id(order_id)
    if not order:
        log.error(f"找不到订单 {order_id}")
        return False

    user_id = order[1]
    expected_amount = order[3]  # 订单金额
    status = order[5]

    if status != "pending":
        log.info(f"订单 {order_id} 状态不是pending，无需检查交易")
        return False

    try:
        # 使用TronGrid API查询交易
        url = f"https://api.trongrid.io/v1/accounts/{wallet_address}/transactions/trc20"
        headers = {
            "Accept": "application/json",
            "TRON-PRO-API-KEY": trongrid_api_key
        }
        params = {
            "limit": 20,  # 限制最近的20条交易
            "contract_address": usdt_contract,  # USDT合约地址
            "only_confirmed": True
        }

        # 获取代理设置
        proxy = None
        if os.environ.get('USE_PROXY', 'False').lower() == 'true':
            proxy_type = os.environ.get('PROXY_TYPE', 'socks5')
            proxy_host = os.environ.get('PROXY_HOST', '127.0.0.1')
            proxy_port = int(os.environ.get('PROXY_PORT', '10808'))
            proxy = f"{proxy_type}://{proxy_host}:{proxy_port}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, proxy=proxy) as response:
                if response.status != 200:
                    log.error(f"查询交易失败: {response.status} {await response.text()}")
                    return False

                data = await response.json()

                # 检查是否有符合条件的交易
                if "data" in data:
                    transactions = data["data"]
                    for tx in transactions:
                        # 只检查USDT转入交易
                        if tx["to"] == wallet_address and tx["token_info"]["address"] == usdt_contract:
                            # 获取交易金额（USDT有6位小数）
                            value = float(tx["value"]) / 10 ** 6

                            # 检查金额是否精确匹配
                            if abs(value - expected_amount) < 0.00001:  # 允许0.00001美元的误差，因为我们使用5位小数
                                # 获取交易哈希
                                tx_hash = tx["transaction_id"]

                                # 尝试获取交易的备注信息，但不强制要求
                                memo = ""
                                try:
                                    tx_detail_url = f"https://api.trongrid.io/v1/transactions/{tx_hash}"
                                    async with session.get(tx_detail_url, headers=headers,
                                                           proxy=proxy) as tx_detail_response:
                                        if tx_detail_response.status == 200:
                                            tx_detail = await tx_detail_response.json()
                                            if "data" in tx_detail and tx_detail["data"]:
                                                # 提取备注信息
                                                raw_data = tx_detail["data"][0]["raw_data"]
                                                if "data" in raw_data:
                                                    memo = bytes.fromhex(raw_data["data"][2:]).decode('utf-8',
                                                                                                      errors='ignore')
                                except Exception as e:
                                    log.error(f"获取交易备注失败: {e}")
                                    # 备注获取失败不影响主要流程

                                # 更新订单的交易哈希和备注
                                from db import update_order_tx_info
                                update_order_tx_info(order_id, tx_hash, memo)

                                # 完成订单 - 金额精确匹配即可确认
                                success = complete_order(order_id, tx_hash)
                                if success:
                                    log.info(f"自动确认订单 {order_id} 支付成功，交易哈希: {tx_hash}，金额: {value}$")
                                    # 通知用户订单已完成
                                    order = get_order_by_id(order_id)
                                    await notify_user_order_completed(order, bot_client)

                                    # 通知管理员订单已自动完成
                                    if ADMIN_ID:
                                        admin_msg = f"🤖 自动确认订单 🤖\n\n订单ID: {order_id}\n用户ID: {user_id}\n金额: {expected_amount}$\n交易哈希: {tx_hash}"
                                        try:
                                            await bot_client.send_message(ADMIN_ID, admin_msg)
                                        except Exception as e:
                                            log.error(f"通知管理员失败: {e}")

                                    return True

        # 更新订单最后检查时间
        update_order_last_checked(order_id)
        return False

    except Exception as e:
        log.exception(f"检查交易失败: {e}")
        return False


async def schedule_transaction_checker(bot_client, trongrid_api_key, usdt_contract):
    """定时任务：定期检查待处理订单的交易状态和超时情况"""
    # 支付超时时间（秒）
    payment_timeout = 24 * 60 * 60  # 24小时

    while True:
        try:
            # 获取所有待处理的订单
            pending_orders = get_all_pending_orders()

            if pending_orders:
                log.info(f"开始检查 {len(pending_orders)} 个待处理订单")
                now = datetime.now()

                for order in pending_orders:
                    order_id = order[0]
                    payment_address = order[6]
                    created_at = datetime.strptime(order[10], '%Y-%m-%d %H:%M:%S')

                    # 检查订单是否超时
                    time_elapsed = (now - created_at).total_seconds()
                    if time_elapsed > payment_timeout:
                        # 订单已超时，取消订单
                        cancelled = cancel_expired_order(order_id)
                        if cancelled:
                            # 尝试通知用户订单已取消
                            try:
                                user_id = order[1]
                                package_name = order[2]
                                amount = order[3]

                                cancel_msg = f"""⏱️ 订单已超时取消 ⏱️

🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$

订单因超过24小时未支付已自动取消。
如需继续购买，请重新选择套餐。"""

                                await bot_client.send_message(int(user_id), cancel_msg)
                            except Exception as e:
                                log.error(f"通知用户订单取消失败: {e}")
                        continue

                    # 检查交易
                    await check_trc20_transaction(order_id, payment_address, bot_client, trongrid_api_key,
                                                  usdt_contract)

                    # 每个订单检查后稍微延迟，避免API请求过于频繁
                    await asyncio.sleep(2)

            # 等待下一次检查
            await asyncio.sleep(TRANSACTION_CHECK_INTERVAL)

        except Exception as e:
            log.exception(f"交易检查任务异常: {e}")
            await asyncio.sleep(60)  # 出错后等待1分钟再继续


async def schedule_quota_reset():
    """定时任务：每天0点重置所有用户的免费次数"""
    while True:
        # 计算距离下一个0点的秒数
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        # 等待到0点
        log.info(f"下一次免费次数重置将在 {seconds_until_midnight:.2f} 秒后进行")
        await asyncio.sleep(seconds_until_midnight)

        # 重置所有用户的免费次数
        affected_users = reset_all_free_quotas()
        log.info(f"已在 {datetime.now()} 重置了 {affected_users} 个用户的免费转发次数")
