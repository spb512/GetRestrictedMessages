"""
Telethon 消息转发机器人
"""

# 1. 导入模块
import asyncio
import logging
import threading
import time
from multiprocessing import Value

from telethon import TelegramClient
from telethon.events import NewMessage, CallbackQuery
from telethon.sessions import StringSession

from config import (
    API_ID, API_HASH, BOT_SESSION, USER_SESSION, BOT_TOKEN,
    is_authorized,
    CPU_THRESHOLD, MEMORY_THRESHOLD, DISK_IO_THRESHOLD,
    MONITOR_INTERVAL, TRANSACTION_CHECK_INTERVAL, TRONGRID_API_KEY, USDT_CONTRACT
)
# 导入数据库模块
from db import (
    init_db
)
from handlers import (
    cmd_start, cmd_user, cmd_buy, cmd_check, cmd_invite, callback_handler, cmd_invite_code, on_new_link
)
from services import (
    schedule_transaction_checker, schedule_quota_reset, start_system_monitor
)

log = logging.getLogger("TelethonSnippets")

# 定义系统过载标志
SYSTEM_OVERLOADED = False

# 创建共享的系统过载状态变量
system_overloaded_ref = Value('b', False)  # 'b' 表示布尔值

# 初始化数据库
init_db()

bot_client = TelegramClient(StringSession(BOT_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))
user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))


# 注册命令处理器
@bot_client.on(NewMessage(pattern='/start'))
async def start_handler(event):
    if not is_authorized(event):
        return
    await cmd_start(event, bot_client)


@bot_client.on(NewMessage(pattern='/user'))
async def user_handler(event):
    if not is_authorized(event):
        return
    await cmd_user(event)


@bot_client.on(NewMessage(pattern='/buy'))
async def buy_handler(event):
    if not is_authorized(event):
        return
    await cmd_buy(event)


@bot_client.on(NewMessage(pattern='/check'))
async def check_handler(event):
    if not is_authorized(event):
        return
    await cmd_check(event)


@bot_client.on(NewMessage(pattern='/invite'))
async def invite_handler(event):
    if not is_authorized(event):
        return
    await cmd_invite(event, bot_client)


@bot_client.on(NewMessage(pattern='/invite_code'))
async def invite_code_handler(event):
    if not is_authorized(event):
        return
    await cmd_invite_code(event, bot_client)


# 注册回调处理器
@bot_client.on(CallbackQuery())
async def callback_query_handler(event):
    # 执行回调处理
    await callback_handler(event, bot_client)


# 注册消息处理器
@bot_client.on(NewMessage())
async def message_handler(event):
    if not is_authorized(event):
        return
    # 调用链接处理函数
    await on_new_link(event, bot_client, user_client, system_overloaded=SYSTEM_OVERLOADED, bot_token=BOT_TOKEN)


# 6. 主函数定义
async def main():
    # 声明全局变量
    global SYSTEM_OVERLOADED

    # 客户端初始化
    log.info("启动机器人")
    await bot_client.connect()
    await user_client.connect()

    # 获取机器人的用户信息
    ubot_self = await bot_client.get_me()
    log.info("机器人已启动为 %s", ubot_self.username or ubot_self.id)

    # 获取 user_client 的用户信息
    u_user = await user_client.get_me()
    log.info("用户客户端已启动为 %s", u_user.username or u_user.id)

    # 启动定时重置任务
    asyncio.create_task(schedule_quota_reset())
    log.info("已启动每日0点自动重置免费转发次数的定时任务")

    # 启动定时交易检查任务
    asyncio.create_task(schedule_transaction_checker(
        bot_client=bot_client,
        trongrid_api_key=TRONGRID_API_KEY,
        usdt_contract=USDT_CONTRACT
    ))
    log.info(f"已启动自动检查交易状态的定时任务，间隔 {TRANSACTION_CHECK_INTERVAL} 秒")

    # 启动系统资源监控线程
    start_system_monitor(
        cpu_threshold=CPU_THRESHOLD,
        memory_threshold=MEMORY_THRESHOLD,
        disk_io_threshold=DISK_IO_THRESHOLD,
        monitor_interval=MONITOR_INTERVAL,
        system_overloaded_var=system_overloaded_ref
    )

    # 更新全局过载标志的监控钩子
    def update_global_overloaded():
        global SYSTEM_OVERLOADED
        while True:
            SYSTEM_OVERLOADED = bool(system_overloaded_ref.value)
            time.sleep(3)

    # 启动全局变量更新线程
    update_thread = threading.Thread(target=update_global_overloaded, daemon=True)
    update_thread.start()

    # 启动并等待两个客户端断开连接
    await bot_client.run_until_disconnected()  # 运行 BOT_SESSION
    await user_client.run_until_disconnected()  # 运行 USER_SESSION


# 7. 程序入口
if __name__ == '__main__':
    asyncio.run(main())
