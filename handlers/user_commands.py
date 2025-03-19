import logging

from telethon.tl.custom import Button

# 获取全局变量
from config import USDT_WALLET
from db import (
    get_db_connection, get_user_quota, process_invite,
    get_user_invite_code, get_invite_stats,
    get_order_by_id
)

# 初始化日志记录器
log = logging.getLogger("UserCommands")


async def cmd_start(event, bot_client):
    """处理 /start 命令，显示使用方法说明"""
    # 检查是否有邀请码参数
    args = event.text.split()
    if len(args) > 1:
        invite_code = args[1].upper()
        success, message = process_invite(invite_code, event.sender_id)
        if success:
            # 获取邀请人信息
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT inviter_id FROM invite_relations WHERE invite_code = ?', (invite_code,))
                inviter_id = cursor.fetchone()[0]

            # 通知邀请人
            try:
                await bot_client.send_message(
                    int(inviter_id),
                    f"🎉 您的好友 @{event.sender.username if event.sender.username else f'用户{event.sender_id}'} 已通过您的邀请链接加入！\n您已获得5次付费转发次数奖励！立即查看 /user"
                )
            except:
                pass

            # 直接显示使用方法
            usage_text = """🤖 使用方法 🤖

1️⃣ 发送需要转发的消息链接
2️⃣ 机器人将帮您保存该消息
3️⃣ 每天免费5次，次日0点重置

❓ 如何获取链接：
- 在消息上点击"分享"
- 选择"复制链接"
- 将链接发送给机器人

📌范围：支持频道、群组、评论区
📄类型：支持视频、图片、音频、文件、文字
⚠️注意：私人频道/群组额外要求:方式一：给机器人发送邀请链接（推荐）;方式二：授权登录你的账号（不推荐）

🎁 邀请系统：
- 使用 /invite 生成您的邀请链接
- 每成功邀请1人获得5次付费转发次数
"""
            await event.reply(usage_text)
            return

    usage_text = """🤖 使用方法 🤖

1️⃣ 发送需要转发的消息链接
2️⃣ 机器人将帮您保存该消息
3️⃣ 每天免费5次，次日0点重置

❓ 如何获取链接：
- 在消息上点击"分享"
- 选择"复制链接"
- 将链接发送给机器人

📌范围：支持频道、群组、评论区
📄类型：支持视频、图片、音频、文件、文字
⚠️注意：私人频道/群组额外要求:方式一：给机器人发送邀请链接（推荐）;方式二：授权登录你的账号（不推荐）

🎁 邀请系统：
- 使用 /invite 生成您的邀请链接
- 每成功邀请1人获得5次付费转发次数
"""
    await event.reply(usage_text)


async def cmd_user(event):
    """处理 /user 命令，显示用户中心信息"""
    user_id = event.sender_id
    free_quota, paid_quota, last_reset_date = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    # 获取用户名
    sender = event.sender
    username = sender.username if sender and sender.username else f"用户{user_id}"

    user_info = f"""👤 用户中心 - @{username}

📊 转发次数统计：
  ├ 剩余次数：{total_quota} 次
  ├ 免费次数：{free_quota} 次
  └ 付费次数：{paid_quota} 次

🔄 免费次数刷新时间：次日0点
📅 上次次数刷新日期：{last_reset_date}

💰 购买更多次数请点击 /buy
"""
    await event.reply(user_info)


async def cmd_buy(event):
    """处理 /buy 命令，显示充值信息"""
    buy_text = """💰 购买转发次数 💰

💳 支付方式：
  ├ 支付宝(暂不支持)
  └ USDT(TRC20)
 
请选择您想购买的套餐："""

    # 定义套餐按钮
    buttons = [
        [Button.inline("基础包: 25次/1$", data=b"buy_basic")],
        [Button.inline("标准包: 150次/5$", data=b"buy_standard")],
        [Button.inline("高级包: 400次/10$", data=b"buy_premium")]
    ]

    await event.respond(buy_text, buttons=buttons)


async def cmd_check(event):
    """处理 /check 命令，查询订单状态"""
    text = event.text.split()
    if len(text) < 2:
        await event.reply("请提供订单号，例如：`/check ORD-12345678`", parse_mode='markdown')
        return

    order_id = text[1]
    order = get_order_by_id(order_id)

    if order:
        # 假设order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
        status = order[5]
        package_name = order[2]
        amount = order[3]
        quota = order[4]
        created_at = order[7]

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
            await event.reply(order_info, buttons=buttons, parse_mode='markdown')
        elif status == "completed":
            order_info += "✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"
            await event.reply(order_info, parse_mode='markdown')
        elif status == "cancelled":
            order_info += "⏱️ 此订单已因超时未支付而自动取消。如需继续购买，请重新选择套餐。"
            await event.reply(order_info, parse_mode='markdown')
    else:
        await event.reply("❌ 找不到此订单，请检查订单号是否正确。")


async def cmd_invite(event, bot_client):
    """处理 /invite 命令，显示邀请信息"""
    user_id = event.sender_id
    invite_code = get_user_invite_code(user_id)
    invite_count, reward_count = get_invite_stats(user_id)

    # 获取机器人信息
    bot_info = await bot_client.get_me()
    bot_username = bot_info.username

    invite_info = f"""🎁 邀请系统 🎁

📊 邀请统计：
  ├ 已邀请人数：{invite_count}/20 人
  └ 获得奖励次数：{reward_count} 次

💡 邀请规则：
  ├ 每成功邀请1人获得5次付费转发次数
  ├ 每个用户只能被邀请一次
  ├ 不能邀请自己
  └ 邀请人数上限20人

📝 使用方法：
1️⃣ 将您的邀请链接分享给好友
2️⃣ 好友点击链接即可完成邀请
3️⃣ 邀请成功后您将获得奖励

🔗 邀请链接：
https://t.me/{bot_username}?start={invite_code}
"""
    await event.reply(invite_info, parse_mode='markdown')


async def cmd_invite_code(event, bot_client):
    """处理 /invite_code 命令，处理邀请码"""
    text = event.text.split()
    if len(text) < 2:
        await event.reply("请提供邀请码，例如：`/invite_code ABC12345`", parse_mode='markdown')
        return

    invite_code = text[1].upper()
    success, message = process_invite(invite_code, event.sender_id)

    if success:
        # 获取邀请人信息
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT inviter_id FROM invite_relations WHERE invite_code = ?', (invite_code,))
            inviter_id = cursor.fetchone()[0]

        # 通知邀请人
        try:
            await bot_client.send_message(
                int(inviter_id),
                f"🎉 您的好友 @{event.sender.username if event.sender.username else f'用户{event.sender_id}'} 已使用您的邀请码！\n您已获得5次付费转发次数奖励！"
            )
        except:
            pass

        # 直接显示使用方法
        usage_text = """🤖 使用方法 🤖

1️⃣ 发送需要转发的消息链接
2️⃣ 机器人将帮您保存该消息
3️⃣ 每天免费5次，次日0点重置

❓ 如何获取链接：
- 在消息上点击"分享"
- 选择"复制链接"
- 将链接发送给机器人

📌范围：支持频道、群组、评论区
📄类型：支持视频、图片、音频、文件、文字
⚠️注意：私人频道/群组额外要求:方式一：给机器人发送邀请链接（推荐）;方式二：授权登录你的账号（不推荐）

🎁 邀请系统：
- 使用 /invite 生成您的邀请链接
- 每成功邀请1人获得5次付费转发次数
"""
        await event.reply(f"✅ {message}\n\n{usage_text}")
    else:
        await event.reply(message)
