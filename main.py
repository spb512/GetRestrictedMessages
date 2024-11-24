import logging
import os
from decouple import config
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")

# 从环境变量中获取配置
API_ID = config("API_ID", cast=int)
API_HASH = config("API_HASH")
SESSION = config("SESSION")
AUTHS = config("AUTHS")

if not API_ID or not API_HASH or not SESSION:
    log.error("Missing one or more environment variables: API_ID, API_HASH, SESSION")
    exit(1)

log.info("Connecting bot.")
try:
    # 使用会话字符串初始化Telegram客户端
    client = TelegramClient(
        StringSession(SESSION), api_id=API_ID, api_hash=API_HASH
    ).start()
except Exception as e:
    log.exception("Failed to start client")
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
        await event.reply("Invalid link?")
        return

    if not message_id.isdigit():
        await event.reply("Invalid link?")
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
    except ValueError:
        await event.reply("I can't find the chat! Either it is invalid, or join it first from this account!")
        return
    except Exception as e:
        log.exception("Failed to get messages")
        await event.reply(f"Error: {e}")
        return

    if not message:
        await event.reply("Message not found.")
        return

    # 如果链接包含 '?single' 参数，则只处理当前消息
    if is_single:
        await handle_single_message(event, message)
    else:
        await handle_media_group(event, message, message_id, peer)

async def handle_single_message(event: events.NewMessage.Event, message) -> None:
    try:
        if message.media:
            await client.send_file(event.chat_id, message.media, caption=message.text or "")
        else:
            await client.send_message(event.chat_id, message.text or "No media found.")
    except Exception as e:
        log.exception("Failed to handle single message")
        await event.reply(f"Error: {e}")

async def handle_media_group(event: events.NewMessage.Event, message, message_id: str, peer) -> None:
    try:
        media_group = await get_media_group_messages(message, message_id, peer)
        media_files = [msg.media for msg in media_group if msg.media]
        combined_caption = "\n".join([msg.text for msg in media_group if msg.text])

        if media_files:
            await client.send_file(event.chat_id, media_files, caption=combined_caption)
    except Exception as e:
        log.exception("Failed to handle media group")
        await event.reply(f"Error: {e}")

async def get_media_group_messages(initial_message, message_id: str, peer) -> list:
    media_group = [initial_message]
    grouped_id = initial_message.grouped_id

    if not grouped_id:
        # 如果初始消息没有 grouped_id，则返回初始消息本身
        return media_group

    # 获取前面的消息
    previous_message_id = int(message_id) - 1
    while True:
        try:
            prev_message = await client.get_messages(peer, ids=previous_message_id)
            if prev_message.grouped_id == grouped_id:
                media_group.insert(0, prev_message)
                previous_message_id -= 1
            else:
                break
        except Exception:
            break

    # 获取后面的消息
    next_message_id = int(message_id) + 1
    while True:
        try:
            next_message = await client.get_messages(peer, ids=next_message_id)
            if next_message.grouped_id == grouped_id:
                media_group.append(next_message)
                next_message_id += 1
            else:
                break
        except Exception:
            break

    return media_group

# 根据 AUTHS 设置监听器
if not AUTHS:
    client.add_event_handler(on_new_link, events.NewMessage(func=lambda e: e.is_private))
else:
     # 将授权用户列表转换为整数列表
    AUTH_USERS = [int(x) for x in AUTHS.split()]
    client.add_event_handler(on_new_link, events.NewMessage(from_users=AUTH_USERS, func=lambda e: e.is_private))

# 获取机器人的用户信息并开始运行客户端
ubot_self = client.loop.run_until_complete(client.get_me())
log.info(
    "\nClient has started as %d.\n\nJoin @BotzHub [ https://t.me/BotzHub ] for more cool bots :)",
    ubot_self.id,
)
client.run_until_disconnected()
