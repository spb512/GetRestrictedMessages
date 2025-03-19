"""
Telethon 消息转发机器人
"""

# 1. 导入模块
import asyncio
import logging
import threading
import time

import psutil
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# 导入数据库模块
from db import (
    init_db, get_db_connection
)
from handlers import (
    cmd_start, cmd_user, cmd_buy, cmd_check, cmd_invite, callback_handler,cmd_invite_code, on_new_link
)

from config import (
    API_ID, API_HASH, BOT_SESSION, USER_SESSION, BOT_TOKEN,
    is_authorized,
    SYSTEM_OVERLOADED, CPU_THRESHOLD, MEMORY_THRESHOLD, DISK_IO_THRESHOLD,
    MONITOR_INTERVAL, TRANSACTION_CHECK_INTERVAL, TRONGRID_API_KEY, USDT_CONTRACT  # 缺少这两个
)

from services import (
    schedule_transaction_checker, schedule_quota_reset
)

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")
# 设置Telethon 内部日志级别，减少日志输出
logging.getLogger('telethon').setLevel(logging.WARNING)

# 初始化数据库
init_db()

bot_client = TelegramClient(StringSession(BOT_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))
user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))


# 注册命令处理器
@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if not is_authorized(event):
        return
    await cmd_start(event, bot_client)

@bot_client.on(events.NewMessage(pattern='/user'))
async def user_handler(event):
    if not is_authorized(event):
        return
    await cmd_user(event)

@bot_client.on(events.NewMessage(pattern='/buy'))
async def buy_handler(event):
    if not is_authorized(event):
        return
    await cmd_buy(event)

@bot_client.on(events.NewMessage(pattern='/check'))
async def check_handler(event):
    if not is_authorized(event):
        return
    await cmd_check(event)

@bot_client.on(events.NewMessage(pattern='/invite'))
async def invite_handler(event):
    if not is_authorized(event):
        return
    await cmd_invite(event, bot_client)

@bot_client.on(events.NewMessage(pattern='/invite_code'))
async def invite_code_handler(event):
    if not is_authorized(event):
        return
    await cmd_invite_code(event, bot_client)

# 注册回调处理器
@bot_client.on(events.CallbackQuery())
async def callback_query_handler(event):
    # 执行回调处理
    await callback_handler(event, bot_client)

# 注册消息处理器
@bot_client.on(events.NewMessage)
async def message_handler(event):
    if not is_authorized(event):
        return
    # 调用链接处理函数
    await on_new_link(event, bot_client, user_client, system_overloaded=False, bot_token=BOT_TOKEN)

# 添加系统监控函数
def monitor_system_resources():
    """监控系统资源使用情况，并在超过阈值时设置系统过载标志"""
    global SYSTEM_OVERLOADED

    while True:
        try:
            # 获取CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)

            # 获取内存使用率
            memory_percent = psutil.virtual_memory().percent

            # 获取磁盘I/O使用率
            disk_io = psutil.disk_io_counters()
            time.sleep(0.1)
            disk_io_new = psutil.disk_io_counters()
            disk_io_percent = 0
            if hasattr(disk_io, 'read_bytes') and hasattr(disk_io_new, 'read_bytes'):
                read_diff = disk_io_new.read_bytes - disk_io.read_bytes
                write_diff = disk_io_new.write_bytes - disk_io.write_bytes
                # 简单估算I/O使用率，实际应根据系统磁盘性能调整基准值
                disk_io_percent = min(100.0, (read_diff + write_diff) / (10 * 1024 * 1024) * 100)

            # 记录资源使用情况
            # log.info(f"系统资源监控 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")

            # 检查是否超过阈值
            if cpu_percent > CPU_THRESHOLD or memory_percent > MEMORY_THRESHOLD or disk_io_percent > DISK_IO_THRESHOLD:
                if not SYSTEM_OVERLOADED:
                    SYSTEM_OVERLOADED = True
                    log.warning(
                        f"系统负载过高 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")
            else:
                if SYSTEM_OVERLOADED:
                    SYSTEM_OVERLOADED = False
                    log.info(
                        f"系统负载恢复正常 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")

            # 等待下一次监控
            time.sleep(MONITOR_INTERVAL)
        except Exception as e:
            log.exception(f"系统监控异常: {e}")
            time.sleep(MONITOR_INTERVAL)


# 6. 主函数定义
async def main():

    # 客户端初始化
    log.info("启动机器人")
    await bot_client.start(bot_token=BOT_TOKEN)
    await user_client.start()
    
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
    monitor_thread = threading.Thread(target=monitor_system_resources, daemon=True)
    monitor_thread.start()
    log.info("已启动系统资源监控线程")
    
    # 启动并等待两个客户端断开连接
    await bot_client.run_until_disconnected()  # 运行 BOT_SESSION


# 7. 程序入口
if __name__ == '__main__':
    asyncio.run(main())
