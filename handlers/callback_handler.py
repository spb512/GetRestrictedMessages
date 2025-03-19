import asyncio
import logging
from datetime import datetime

from telethon.tl.custom import Button

# 获取全局变量
from config import USDT_WALLET, ADMIN_ID
from db import (
    get_order_by_id, create_new_order
)

# 初始化日志记录器
log = logging.getLogger("CallbackHandler")


async def callback_handler(event, bot_client):
    """处理按钮点击事件"""
    # 获取回调数据
    data = event.data
    user_id = event.sender_id

    # 套餐配置
    packages = {
        b"buy_basic": {"name": "基础包", "price": 1, "quota": 25},
        b"buy_standard": {"name": "标准包", "price": 5, "quota": 150},
        b"buy_premium": {"name": "高级包", "price": 10, "quota": 400}
    }

    # 如果是购买套餐
    if data in packages:
        package = packages[data]
        # 创建新订单
        order_id, unique_amount = create_new_order(user_id, package["name"], package["price"], package["quota"])

        if order_id:
            # 生成付款信息
            payment_text = f"""🛒 您已选择: {package['name']}
💰 价格: {unique_amount}$  (请务必转账此精确到账金额)
🔢 可获得次数: {package['quota']}次

💳 请使用USDT(TRC20)支付至以下地址:
`{USDT_WALLET}`

📝 订单号: `{order_id}`

⚠️ 重要：请务必转账 {unique_amount}$ 精确的到账金额(小数点后要一致)，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""
            # 添加查看订单状态的按钮
            buttons = [
                [Button.inline("查询订单状态", data=f"check_{order_id}".encode())]
            ]
            try:
                await event.edit(payment_text, buttons=buttons, parse_mode='markdown')
            except Exception as e:
                log.error(f"编辑消息失败: {e}")
                await event.answer("消息更新失败，请重试", alert=True)

            # 如果设置了管理员ID，发送订单通知给管理员
            if ADMIN_ID:
                admin_notify = f"📢 新订单通知 📢\n\n用户ID: {user_id}\n套餐: {package['name']}\n金额: {package['price']}$\n订单ID: {order_id}"
                try:
                    await bot_client.send_message(ADMIN_ID, admin_notify)
                except Exception as e:
                    log.error(f"发送管理员通知失败: {e}")
        else:
            try:
                await event.edit("❌ 订单创建失败，请稍后重试或联系管理员。")
            except Exception as e:
                log.error(f"编辑消息失败: {e}")
                await event.answer("消息更新失败，请重试", alert=True)

    # 查询订单状态
    elif data.startswith(b"check_"):
        order_id = data[6:].decode('utf-8')
        order = get_order_by_id(order_id)

        if order:
            # 假设order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
            status = order[5]
            package_name = order[2]
            amount = order[3]
            quota = order[4]
            created_at = order[10]

            status_text = {
                "pending": "⏳ 等待付款",
                "completed": "✅ 已完成",
                "cancelled": "❌ 已取消"
            }.get(status, status)

            order_info = f"""📋 订单详情 📋
            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text}

"""
            if status == "pending":
                order_info += f"""💳 付款地址: `{USDT_WALLET}`

⚠️ 重要：请务必转账 {amount}$ 精确的到账金额(小数点后要一致)，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""

                buttons = [[Button.inline("刷新状态", data=f"check_{order_id}".encode())]]
                try:
                    # 先尝试显示"正在刷新"状态
                    temp_info = f"""📋 订单详情 - 正在刷新... 📋
                    
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} (刷新中...)

"""
                    if status == "pending":
                        temp_info += f"""💳 付款地址: `{USDT_WALLET}`
⚠️ 重要：请务必转账 {amount}$ 精确的到账金额(小数点后要一致)，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""

                    # 先显示刷新中状态
                    await event.edit(temp_info, buttons=buttons, parse_mode='markdown')

                    # 等待半秒，让用户能看到刷新效果
                    await asyncio.sleep(0.5)

                    # 然后显示最终结果
                    await event.edit(order_info, buttons=buttons, parse_mode='markdown')

                except Exception as e:
                    error_str = str(e)
                    if "Content of the message was not modified" in error_str:
                        # 消息内容没变化，尝试显示临时消息
                        log.info(f"订单状态没有变化，尝试显示临时刷新效果")
                        try:
                            # 添加时间戳使消息内容强制变化
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            temp_msg = f"""📋 订单详情 - 刷新于 {timestamp} 📋
                            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} ✓

✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"""

                            # 先显示带时间戳的临时信息
                            await event.edit(temp_msg, parse_mode='markdown')

                            # 等待半秒，让用户能看到刷新效果
                            await asyncio.sleep(0.5)

                            # 然后恢复原始信息
                            await event.edit(order_info, parse_mode='markdown')
                        except Exception as inner_e:
                            log.error(f"显示临时刷新消息失败: {inner_e}")
                    else:
                        log.error(f"编辑消息失败: {error_str}")
            elif status == "completed":
                order_info += "✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"
                try:
                    await event.edit(order_info, parse_mode='markdown')
                except Exception as e:
                    error_str = str(e)
                    if "Content of the message was not modified" in error_str:
                        # 消息内容没变化，尝试显示临时消息
                        log.info(f"订单状态没有变化，尝试显示临时刷新效果")
                        try:
                            # 添加时间戳使消息内容强制变化
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            temp_msg = f"""📋 订单详情 - 刷新于 {timestamp} 📋
                            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} ✓

✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"""

                            # 先显示带时间戳的临时信息
                            await event.edit(temp_msg, parse_mode='markdown')

                            # 等待半秒，让用户能看到刷新效果
                            await asyncio.sleep(0.5)

                            # 然后恢复原始信息
                            await event.edit(order_info, parse_mode='markdown')
                        except Exception as inner_e:
                            log.error(f"显示临时刷新消息失败: {inner_e}")
                    else:
                        log.error(f"编辑消息失败: {error_str}")
            elif status == "cancelled":
                order_info += "⏱️ 此订单已因超时未支付而自动取消。如需继续购买，请重新选择套餐。"
                try:
                    await event.edit(order_info, parse_mode='markdown')
                except Exception as e:
                    log.error(f"编辑消息失败: {e}")
        else:
            try:
                await event.edit("❌ 找不到此订单，请检查订单号是否正确。")
            except Exception as e:
                log.error(f"编辑消息失败: {e}")

    # 其他回调数据
    else:
        await event.answer("未知操作", alert=True)
