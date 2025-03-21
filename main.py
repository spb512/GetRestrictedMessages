"""
Telethon 消息转发机器人
"""

# 1. 导入模块
import asyncio
import logging
from multiprocessing import Value
import functools

from telethon import TelegramClient
from telethon.events import NewMessage, CallbackQuery
from telethon.sessions import StringSession

from config import (
    API_ID, API_HASH, BOT_SESSION, USER_SESSION, BOT_TOKEN,
    is_authorized,
    CPU_THRESHOLD, MEMORY_THRESHOLD, DISK_IO_THRESHOLD,
    MONITOR_INTERVAL, TRANSACTION_CHECK_INTERVAL, TRONGRID_API_KEY, USDT_CONTRACT,
    get_proxy
)
# 导入数据库模块
from db import (
    init_db
)
from handlers import (
    cmd_start, cmd_user, cmd_buy, cmd_check, cmd_invite, callback_handler, on_new_link
)
from services import (
    schedule_transaction_checker, schedule_quota_reset, start_system_monitor
)

log = logging.getLogger("TelethonSnippets")

# 创建共享的系统过载状态变量
system_overloaded_ref = Value('b', False)  # 'b' 表示布尔值

# 初始化数据库
init_db()

# 定义鉴权装饰器
def requires_auth(func):
    """
    鉴权装饰器，用于检查用户是否有权限使用机器人
    """
    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        if not is_authorized(event):
            return
        return await func(event, *args, **kwargs)
    return wrapper

# 获取代理设置
proxy_settings = get_proxy()

bot_client = TelegramClient(StringSession(BOT_SESSION), API_ID, API_HASH, proxy=proxy_settings)
user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH, proxy=proxy_settings)


# 注册命令处理器
@bot_client.on(NewMessage(pattern='/start'))
@requires_auth
async def start_handler(event):
    await cmd_start(event, bot_client)


@bot_client.on(NewMessage(pattern='/user'))
@requires_auth
async def user_handler(event):
    await cmd_user(event)


@bot_client.on(NewMessage(pattern='/buy'))
@requires_auth
async def buy_handler(event):
    await cmd_buy(event)


@bot_client.on(NewMessage(pattern='/check'))
@requires_auth
async def check_handler(event):
    await cmd_check(event)


@bot_client.on(NewMessage(pattern='/invite'))
@requires_auth
async def invite_handler(event):
    await cmd_invite(event, bot_client)


# 注册回调处理器
@bot_client.on(CallbackQuery())
async def callback_query_handler(event):
    # 执行回调处理
    await callback_handler(event, bot_client)


# 注册消息处理器
@bot_client.on(NewMessage())
@requires_auth
async def message_handler(event):
    # 调用链接处理函数
    await on_new_link(event, bot_client, user_client, system_overloaded=system_overloaded_ref.value,
                      bot_token=BOT_TOKEN)


# 6. 主函数定义
async def main():
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

    # 启动并等待两个客户端断开连接
    await bot_client.run_until_disconnected()  # 运行 BOT_SESSION
    await user_client.run_until_disconnected()  # 运行 USER_SESSION


# 7. 程序入口
if __name__ == '__main__':
    asyncio.run(main())
