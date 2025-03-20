import logging
import urllib.parse

import aiohttp
from decouple import config
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import (
    BOT_TOKEN, RANGE
)

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")

# 从环境变量中获取配置
API_ID = config("API_ID", default=None, cast=int)
API_HASH = config("API_HASH", default=None)
SESSION = config("BOT_SESSION", default=None)
BOT_TOKEN = config("BOT_TOKEN", default=None)
AUTHS = config("AUTHS", default="")
# 消息范围±10
RANGE = 10

# 代理设置
USE_PROXY = config("USE_PROXY", default=False, cast=bool)
PROXY_TYPE = config("PROXY_TYPE", default="socks5")
PROXY_HOST = config("PROXY_HOST", default="127.0.0.1")
PROXY_PORT = config("PROXY_PORT", default=10808, cast=int)


# 获取代理配置
def get_proxy_settings():
    """返回代理设置，如果USE_PROXY为False则返回None"""
    if USE_PROXY:
        return (PROXY_TYPE, PROXY_HOST, PROXY_PORT)
    return None


if not all([API_ID, API_HASH, SESSION]):
    log.error("缺少一个或多个必要环境变量: API_ID、API_HASH、SESSION")
    exit(1)

log.info("连接机器人。")
try:
    # 使用会话字符串初始化Telegram客户端
    proxy_settings = get_proxy_settings()
    client = TelegramClient(
        StringSession(SESSION), api_id=API_ID, api_hash=API_HASH, proxy=proxy_settings
    ).start()
except Exception as e:
    log.exception("启动客户端失败")
    log.exception(f"Error: {e}")
    exit(1)


# 定义处理新消息的函数
async def on_new_link(event: events.NewMessage.Event) -> None:
    text = event.text
    if not text:
        return

    # 检查消息是否包含有效的Telegram链接
    if not text.startswith(("https://t.me", "http://t.me")):
        return

    # 检查是否包含 '?single' 参数
    is_single = 'single' in text

    try:
        chat_id, message_id = await parse_url(text.split('?')[0])
    except ValueError:
        await event.reply("无效链接")
        return

    if chat_id.isdigit():
        peer = int(chat_id)
    elif chat_id.startswith("-100"):
        peer = int(chat_id)
    else:
        peer = chat_id

    try:
        # 获取指定聊天中的消息
        message = await client.get_messages(peer, ids=message_id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")
        return

    if not message:
        await event.reply("找不到聊天记录！要么无效，要么先以此帐户加入！")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
    params = {"chat_id": f"@{chat_id}"}
    has_protected_content = False

    # 获取代理设置
    proxy = None
    if USE_PROXY:
        proxy = f"{PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, proxy=proxy) as response:
            if response.status == 200:
                result = await response.json()
                if result and result.get("ok"):
                    channel = result.get("result")
                    has_protected_content = channel.get("has_protected_content", False)

    # 如果链接包含 '?single' 参数，则只处理当前消息
    if is_single:
        if has_protected_content:
            await handle_single_message(event, message)
        else:
            # 如果 has_protected_content 为 False，直接转发消息
            await client.forward_messages(event.chat_id, message)
            await client.send_message(event.chat_id, "转发完成，此消息允许直接转发哦", reply_to=event.message.id)
    else:
        if has_protected_content:
            media_group = await get_media_group_messages(message, message_id, peer)
            await handle_media_group(event, message, media_group)
        else:
            # 如果 has_protected_content 为 False，直接转发消息
            media_group = await get_media_group_messages(message, message_id, peer)
            await client.forward_messages(event.chat_id, media_group)
            await client.send_message(event.chat_id, "转发完成，此消息允许直接转发哦", reply_to=event.message.id)


async def parse_url(text: str):
    """解析链接，提取 chat_id 和 message_id"""
    parsed_url = urllib.parse.urlparse(text)
    path_parts = parsed_url.path.strip('/').split('/')
    if len(path_parts) < 2:
        raise ValueError("无效的URL")
    chat_id = path_parts[1] if path_parts[0] in ['c', 's'] else path_parts[0]
    message_id = path_parts[-1]
    if not message_id.isdigit():
        raise ValueError("无效的message_id")
    return chat_id, int(message_id)


async def handle_single_message(event: events.NewMessage.Event, message) -> None:
    try:
        if message.media:
            await client.send_file(event.chat_id, message.media, caption=message.text, reply_to=event.message.id)
        else:
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def handle_media_group(event: events.NewMessage.Event, message, media_group) -> None:
    try:
        media_files = [msg.media for msg in media_group if msg.media]

        if media_files:
            caption = media_group[0].text
            await client.send_file(event.chat_id, media_files, caption=caption, reply_to=event.message.id)
        else:
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def get_media_group_messages(initial_message, message_id, peer) -> list:
    media_group = [initial_message]
    grouped_id = initial_message.grouped_id

    if not grouped_id:
        # 如果初始消息没有 grouped_id，则返回初始消息本身
        return media_group

    # 获取前后10条消息的范围
    start_id = max(1, message_id - RANGE)
    end_id = message_id + RANGE

    try:
        # 转换 range 为列表
        ids = list(range(start_id, end_id + 1))
        # 一次性获取指定范围内的消息
        messages = await client.get_messages(peer, ids=ids)

        # 按照 grouped_id 筛选属于同一组的消息
        media_group = [msg for msg in messages if msg and msg.grouped_id == grouped_id]
    except Exception as e:
        log.exception(f"Error: {e}")

    return media_group


# 在配置加载时解析授权用户列表
AUTH_USERS = set()
if AUTHS:
    try:
        # 解析授权用户字符串，支持整数和 @username
        AUTH_USERS = set(int(x) if x.isdigit() else x for x in AUTHS.split())
    except ValueError:
        log.error("AUTHS 配置中包含无效的用户格式，确保是 user_id 或 username")
        exit(1)


# 添加事件处理器
def is_authorized(event: events.NewMessage.Event) -> bool:
    # 如果未设置 AUTH_USERS，则默认允许所有私聊
    if not AUTH_USERS:
        return event.is_private
    # 如果设置了 AUTH_USERS，则校验是否在授权列表中
    sender_id = event.sender_id
    sender = event.sender

    # 获取用户名（可能为 None）
    sender_name = sender.username if sender else None

    # 调试日志
    # log.info(f"收到来自用户 {sender_id} 的消息，用户名：{sender_name}")
    # log.info(f"是否在授权用户列表 (ID)：{sender_id in AUTH_USERS}")
    # log.info(f"是否在授权用户列表 (用户名)：{sender_name in AUTH_USERS if sender_name else False}")

    # 校验 ID 或用户名是否在授权列表中
    return (sender_id in AUTH_USERS or (sender_name in AUTH_USERS if sender_name else False)) and event.is_private


client.add_event_handler(on_new_link, events.NewMessage(func=is_authorized))


async def main():
    # 获取机器人的用户信息并开始运行客户端
    ubot_self = await client.get_me()
    log.info("客户端已启动为 %d。", ubot_self.id)
    await client.run_until_disconnected()


client.loop.run_until_complete(main())
