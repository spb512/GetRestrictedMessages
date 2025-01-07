import asyncio
import logging
import os
import tempfile
import time

from decouple import config
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, InputMediaUploadedDocument, InputMediaUploadedPhoto, \
    MessageMediaPhoto, Message

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")

# 从环境变量中获取配置
API_ID = config("API_ID", default=None, cast=int)
API_HASH = config("API_HASH", default=None)
SESSION = config("USER_SESSION", default=None)
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
    global comment_id
    text = event.text
    if not text:
        return

    # 检查消息是否包含有效的Telegram链接
    if not (text.startswith("https://t.me") or text.startswith("http://t.me")):
        return

    # 检查是否包含 '?single' 参数
    is_single = '?single' in text

    # 检查是否包含 '?comment' 参数
    is_comment = '?comment' in text

    if is_comment:
        comment_id = int(text.split('?comment=')[1])
    # 去除链接中的 '?single' 或 '?comment' 参数
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
    else:
        message_id = int(message_id)

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

    # print(message.stringify())

    # 如果链接包含 '?single' 参数，则只处理当前消息
    if is_single:
        await handle_single_message(event, message)
    elif is_comment:
        # 获取频道实体
        channel = await client.get_entity(chat_id)
        comment_message, comment_grouped_id = await get_comment_message(
            client, channel, message_id, comment_id
        )

        if not comment_message:
            await event.reply("未找到指定的评论消息")
        else:
            if not comment_grouped_id:
                await handle_single_message(event, comment_message)
            else:
                # 获取属于同一组的所有消息
                comment_media_group = []
                async for reply in client.iter_messages(
                        entity=channel,
                        reply_to=message_id
                ):
                    if reply.grouped_id == comment_grouped_id:
                        comment_media_group.append(reply)
                await handle_media_group(event, comment_message, comment_media_group)
    else:
        # 获取属于同一组的消息
        media_group = await get_media_group_messages(message, message_id, peer)
        await handle_media_group(event, message, media_group)


async def get_comment_message(client: TelegramClient, channel, message_id, comment_id):
    """从评论中获取指定的评论消息及其 grouped_id"""
    async for reply in client.iter_messages(
            entity=channel,
            reply_to=message_id
    ):
        if reply.id == comment_id:
            return reply, reply.grouped_id  # 返回匹配的评论消息及其 grouped_id
    return None, None  # 如果没有找到，返回 None


async def handle_single_message(event: events.NewMessage.Event, message) -> None:
    try:
        # 发送提示消息
        status_message = await event.reply("转存中，请稍等...")
        if message.media:
            # 判断原始发送方式
            force_document = False
            if isinstance(message.media, MessageMediaDocument) and (
                    message.media.document.mime_type == 'image/jpeg' or (
                    message.media.document.mime_type == 'video/mp4' and not message.media.video) or message.media.document.mime_type == 'image/heic'):
                force_document = True

            # 先下载文件
            file_path = await message.download_media()
            if isinstance(message.media, MessageMediaDocument) and (
                    (
                            message.media.document.mime_type == 'video/mp4' and message.media.document.size > 10 * 1024 * 1024) or message.media.document.mime_type == 'image/heic'):
                # 下载缩略图
                timestamp = int(time.time())
                thumb_filename = f"{message.media.document.id}_{timestamp}_thumbnail.jpg"
                thumb_path = await client.download_media(
                    message.media,
                    file=thumb_filename,
                    thumb=-1  # -1 表示下载最高质量的缩略图
                )
                await client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                       attributes=message.media.document.attributes, thumb=thumb_path,
                                       force_document=force_document)
                os.remove(thumb_path)  # 发送后删除缩略图
            elif isinstance(message.media, MessageMediaDocument) and message.media.document.mime_type == 'audio/mpeg':
                await client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                       attributes=message.media.document.attributes,
                                       force_document=force_document)
            else:
                await client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                       force_document=force_document)
            os.remove(file_path)  # 发送后删除文件
        else:
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
        # 删除提示消息
        await status_message.delete()
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def handle_media_group(event: events.NewMessage.Event, message, media_group) -> None:
    try:
        # 发送提示消息
        status_message = await event.reply("转存中，请稍等...")

        # 收集所有文本作为 caption
        captions = [msg.text if msg.text is not None else '' for msg in media_group]

        # 构造相册的文件对象
        album_files = await asyncio.gather(*[prepare_album_file(msg, client) for msg in media_group if msg.media])
        if album_files:
            await client.send_file(event.chat_id, file=album_files, caption=captions, reply_to=event.message.id)
        else:
            # 如果消息不包含媒体，发送文本消息
            await client.send_message(event.chat_id, message.text, reply_to=event.message.id)
        # 删除提示消息
        await status_message.delete()
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def prepare_album_file(msg: Message, client: TelegramClient):
    """准备相册文件的上传对象"""
    # 为临时文件添加扩展名
    suffix = ".jpg" if isinstance(msg.media,
                                  MessageMediaPhoto) else ".mp4" if "video/mp4" in msg.media.document.mime_type else ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        file_path = await msg.download_media(file=temp_file.name)
        thumb_path = None

        try:
            if isinstance(msg.media, MessageMediaPhoto):
                # print(file_path)
                return InputMediaUploadedPhoto(file=await client.upload_file(file_path))

            elif isinstance(msg.media, MessageMediaDocument):
                if (msg.media.document.mime_type == "video/mp4" and msg.media.document.size > 10 * 1024 * 1024) or (
                        msg.media.document.mime_type == "image/heic"):
                    thumb_path = await client.download_media(
                        msg, file=f"{temp_file.name}_thumb.jpg", thumb=-1
                    )
                return InputMediaUploadedDocument(
                    file=await client.upload_file(file_path),
                    thumb=await client.upload_file(thumb_path) if thumb_path else None,
                    mime_type=msg.media.document.mime_type or "application/octet-stream",
                    attributes=msg.media.document.attributes,
                )
        finally:
            # 删除临时文件
            os.remove(file_path)
            if thumb_path:
                os.remove(thumb_path)


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
