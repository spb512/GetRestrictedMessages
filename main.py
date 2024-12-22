import logging

from decouple import config
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")

# 从环境变量中获取配置
API_ID = config("API_ID", default=None, cast=int)
API_HASH = config("API_HASH", default=None)
SESSION = config("SESSION", default=None)
AUTHS = config("AUTHS", default="")
# 消息范围±10
RANGE = 10

if not all([API_ID, API_HASH, SESSION]):
    log.error("缺少一个或多个必要环境变量: API_ID、API_HASH、SESSION")
    exit(1)

log.info("连接机器人。")
try:
    # 使用会话字符串初始化Telegram客户端
    client = TelegramClient(
        StringSession(SESSION), api_id=API_ID, api_hash=API_HASH
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
    if not (text.startswith("https://t.me") or text.startswith("http://t.me")):
        return

    # 检查是否包含 '?single' 参数
    is_single = '?single' in text

    # 去除链接中的 '?single' 参数
    text = text.split('?')[0]

    try:
        # 解析链接以提取 chat_id 和 message_id
        parts = text.lstrip('https://').lstrip('http://').split('/')
        chat_id = parts[2 if parts[1] in ['c', 's'] else 1]
        message_id = parts[-1]
    except IndexError:
        await event.reply("无效链接")
        return

    if not message_id.isdigit():
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
        message = await client.get_messages(peer, ids=int(message_id))
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")
        return

    if not message:
        await event.reply("找不到聊天记录！要么无效，要么先以此帐户加入！")
        return

    # 如果链接包含 '?single' 参数，则只处理当前消息
    if is_single:
        await handle_single_message(event, message)
    else:
        await handle_media_group(event, message, message_id, peer)


async def handle_single_message(event: events.NewMessage.Event, message) -> None:
    try:
        if message.media:
            await client.send_file(event.chat_id, message.media, caption=message.text, reply_to=event.message.id)
        else:
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def handle_media_group(event: events.NewMessage.Event, message, message_id: str, peer) -> None:
    try:
        media_group = await get_media_group_messages(message, message_id, peer)
        media_files = [msg.media for msg in media_group if msg.media]

        if media_files:
            caption = media_group[0].text
            await client.send_file(event.chat_id, media_files, caption=caption, reply_to=event.message.id)
        else:
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def get_media_group_messages(initial_message, message_id: str, peer) -> list:
    media_group = [initial_message]
    grouped_id = initial_message.grouped_id

    if not grouped_id:
        # 如果初始消息没有 grouped_id，则返回初始消息本身
        return media_group

    # 获取前后10条消息的范围
    start_id = max(1, int(message_id) - RANGE)
    end_id = int(message_id) + RANGE

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
