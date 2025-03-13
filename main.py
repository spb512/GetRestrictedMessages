"""
Telethon 消息转发机器人
"""

# 1. 导入模块
import asyncio
import logging
import os
import sqlite3
import tempfile
import time
import urllib.parse
from datetime import datetime

import requests
from decouple import config
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, PeerChannel, Message, MessageMediaPhoto, InputMediaUploadedPhoto, \
    InputMediaUploadedDocument

# 2. 全局配置与常量
# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("TelethonSnippets")
# 设置Telethon 内部日志级别，减少日志输出
logging.getLogger('telethon').setLevel(logging.WARNING)

# 从环境变量中获取配置
API_ID = config("API_ID", default=None, cast=int)
API_HASH = config("API_HASH", default=None)
BOT_SESSION = config("BOT_SESSION", default=None)
USER_SESSION = config("USER_SESSION", default=None)
BOT_TOKEN = config("BOT_TOKEN", default=None)
PRIVATE_CHAT_ID = config("PRIVATE_CHAT_ID", default=None, cast=int)
AUTHS = config("AUTHS", default="")
# 消息范围±10
RANGE = 10
# SQLite 数据库文件
DB_FILE = "message_forward.db"
# 在配置加载时解析授权用户列表
AUTH_USERS = set()
if AUTHS:
    try:
        # 解析授权用户字符串，支持整数、@username和username
        AUTH_USERS = set()
        for x in AUTHS.split():
            if x.isdigit():
                AUTH_USERS.add(int(x))
            else:
                # 去掉可能存在的@前缀，保存原始格式和无@前缀的格式
                if x.startswith('@'):
                    AUTH_USERS.add(x)  # 保留原始格式 @username
                    AUTH_USERS.add(x[1:])  # 添加无@格式 username
                else:
                    AUTH_USERS.add(x)  # 添加原始格式 username
                    AUTH_USERS.add(f"@{x}")  # 添加带@格式 @username
    except ValueError:
        log.error("AUTHS 配置中包含无效的用户格式，确保是 user_id 或 username")
        exit(1)
if not all([API_ID, API_HASH, BOT_SESSION, USER_SESSION]):
    log.error("缺少一个或多个必要环境变量: API_ID、API_HASH、BOT_SESSION、USER_SESSION")
    exit(1)


# 3.数据库操作相关函数
# 创建并初始化数据库
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS message_relations (
        source_chat_id TEXT NOT NULL,
        source_message_id INTEGER NOT NULL,
        target_chat_id TEXT NOT NULL,
        target_message_id INTEGER NOT NULL,
        grouped_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source_chat_id, source_message_id, target_chat_id, grouped_id)
    )
    ''')

    # 创建用户转发次数表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_forward_quota (
        user_id TEXT PRIMARY KEY,
        free_quota INTEGER DEFAULT 5,
        paid_quota INTEGER DEFAULT 0,
        last_reset_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    log.info("数据库初始化完成")


# 保存消息转发关系
def save_message_relation(source_chat_id, source_message_id, target_chat_id, target_message_id, grouped_id=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        cursor.execute('''
        INSERT INTO message_relations 
        (source_chat_id, source_message_id, target_chat_id, target_message_id, grouped_id, created_at) 
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (str(source_chat_id), source_message_id, str(target_chat_id), target_message_id, grouped_id, created_at))
        conn.commit()
    except sqlite3.IntegrityError:
        # 如果已存在，则更新
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        cursor.execute('''
        UPDATE message_relations 
        SET target_message_id = ?, grouped_id = ?, created_at = ?
        WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ?
        ''', (target_message_id, grouped_id, created_at, str(source_chat_id), source_message_id, str(target_chat_id)))
        conn.commit()
    finally:
        conn.close()


# 批量保存媒体组消息关系
def save_media_group_relations(source_chat_id, source_messages, target_chat_id, target_messages, grouped_id=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        for i in range(len(source_messages)):
            if i < len(target_messages):
                source_msg = source_messages[i]
                target_msg = target_messages[i] if isinstance(target_messages[i], Message) else target_messages
                created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                cursor.execute('''
                INSERT INTO message_relations 
                (source_chat_id, source_message_id, target_chat_id, target_message_id, grouped_id, created_at) 
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (str(source_chat_id), source_msg.id, str(target_chat_id),
                      target_msg.id if isinstance(target_msg, Message) else target_msg,
                      grouped_id, created_at))
        conn.commit()
    except Exception as e:
        log.exception(f"保存媒体组关系失败: {e}")
    finally:
        conn.close()


# 查找已转发的消息
def find_forwarded_message(source_chat_id, source_message_id, target_chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT target_message_id, grouped_id FROM message_relations
    WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ? and grouped_id != 0
    ''', (str(source_chat_id), source_message_id, str(target_chat_id)))
    result = cursor.fetchone()
    conn.close()
    return result


# 查找已转发的消息
def find_forwarded_message_for_one(source_chat_id, source_message_id, target_chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT target_message_id, grouped_id FROM message_relations
    WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ? AND grouped_id = 0
    ''', (str(source_chat_id), source_message_id, str(target_chat_id)))
    result = cursor.fetchone()
    conn.close()
    return result


# 查找相同组ID的所有转发消息
def find_grouped_messages(source_chat_id, grouped_id, target_chat_id):
    # if not grouped_id:
    #     return []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT source_message_id, target_message_id FROM message_relations 
    WHERE source_chat_id = ? AND grouped_id = ? AND target_chat_id = ?
    ''', (str(source_chat_id), grouped_id, str(target_chat_id)))
    results = cursor.fetchall()
    conn.close()
    return results


# 用户转发次数管理相关函数
def get_user_quota(user_id):
    """获取用户当前的转发次数配额"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 检查用户是否已有记录
    cursor.execute('SELECT free_quota, paid_quota, last_reset_date FROM user_forward_quota WHERE user_id = ?',
                   (str(user_id),))
    result = cursor.fetchone()

    current_date = datetime.now().strftime('%Y-%m-%d')

    if not result:
        # 新用户，创建记录
        cursor.execute(
            'INSERT INTO user_forward_quota (user_id, free_quota, paid_quota, last_reset_date) VALUES (?, ?, ?, ?)',
            (str(user_id), 5, 0, current_date)
        )
        conn.commit()
        conn.close()
        return 5, 0, current_date

    free_quota, paid_quota, last_reset_date = result

    # 检查是否需要重置免费次数（每日0点重置）
    if last_reset_date != current_date:
        free_quota = 5  # 重置免费次数
        cursor.execute(
            'UPDATE user_forward_quota SET free_quota = ?, last_reset_date = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (free_quota, current_date, str(user_id))
        )
        conn.commit()

    conn.close()
    return free_quota, paid_quota, current_date


def decrease_user_quota(user_id):
    """减少用户的转发次数，优先使用免费次数"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    free_quota, paid_quota, _ = get_user_quota(user_id)

    if free_quota > 0:
        # 优先使用免费次数
        free_quota -= 1
        cursor.execute(
            'UPDATE user_forward_quota SET free_quota = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (free_quota, str(user_id))
        )
    elif paid_quota > 0:
        # 然后使用付费次数
        paid_quota -= 1
        cursor.execute(
            'UPDATE user_forward_quota SET paid_quota = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (paid_quota, str(user_id))
        )
    else:
        # 没有可用次数
        conn.close()
        return False

    conn.commit()
    conn.close()
    return True


def add_paid_quota(user_id, amount):
    """为用户添加付费转发次数"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 确保用户记录存在
    free_quota, paid_quota, _ = get_user_quota(user_id)

    # 增加付费次数
    paid_quota += amount
    cursor.execute(
        'UPDATE user_forward_quota SET paid_quota = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
        (paid_quota, str(user_id))
    )

    conn.commit()
    conn.close()
    return paid_quota


async def process_forward_quota(event):
    """处理转发次数减少并发送提示消息的公共方法"""
    # 减少用户转发次数
    user_id = event.sender_id
    decrease_user_quota(user_id)

    # 获取用户剩余次数
    free_quota, paid_quota, _ = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    # 在转发成功后告知用户剩余次数
    await event.reply(f"转发成功！您今日剩余 {total_quota} 次转发机会（免费 {free_quota} 次，付费 {paid_quota} 次）")


# 4. 辅助函数
async def message_search(message: Message):
    if message.fwd_from:
        peer_id = utils.get_peer_id(message.fwd_from.from_id)
        message_id = message.fwd_from.channel_post
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        req_params = {"chat_id": peer_id}
        result = requests.get(url, params=req_params)
        has_protected_content = False
        peer_type = "channel"
        channel_username = None
        if result and result.json().get("ok"):
            channel = result.json().get("result")
            has_protected_content = channel.get("has_protected_content", False)
            peer_type = channel.get("type", "channel")
            channel_username = channel.get("username")

        if peer_type == "channel" and channel_username:
            return channel_username, message_id
        else:
            temp_message = await user_client.get_messages(message.fwd_from.from_id, ids=message_id)
            return await message_search(temp_message)  # 确保返回递归结果
    return None  # 如果没有满足条件，返回 None


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


async def prepare_album_file(msg: Message):
    """准备相册文件的上传对象"""
    # 为临时文件添加扩展名
    suffix = ".jpg" if isinstance(msg.media,
                                  MessageMediaPhoto) else ".mp4" if "video/mp4" in msg.media.document.mime_type else ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        file_path = await user_client.download_media(msg, file=temp_file.name)
        temp_file.close()  # 先关闭文件
        thumb_path = None

        try:
            if isinstance(msg.media, MessageMediaPhoto):
                # print(file_path)
                return InputMediaUploadedPhoto(file=await bot_client.upload_file(file_path))

            elif isinstance(msg.media, MessageMediaDocument):
                if (msg.media.document.mime_type == "video/mp4" and msg.media.document.size > 10 * 1024 * 1024) or (
                        msg.media.document.mime_type == "image/heic"):
                    thumb_path = await user_client.download_media(
                        msg, file=f"{temp_file.name}_thumb.jpg", thumb=-1
                    )
                return InputMediaUploadedDocument(
                    file=await bot_client.upload_file(file_path),
                    thumb=await bot_client.upload_file(thumb_path) if thumb_path else None,
                    mime_type=msg.media.document.mime_type or "application/octet-stream",
                    attributes=msg.media.document.attributes,
                )
        finally:
            # 删除临时文件
            os.remove(file_path)
            if thumb_path:
                os.remove(thumb_path)


async def get_comment_message(client: TelegramClient, channel, message_id, comment_id):
    """从评论中获取指定的评论消息及其 grouped_id"""
    async for reply in client.iter_messages(
            entity=channel,
            reply_to=message_id
    ):
        if reply.id == comment_id:
            return reply, reply.grouped_id  # 返回匹配的评论消息及其 grouped_id
    return None, None  # 如果没有找到，返回 None


async def single_forward_message(event, relation):
    # 如果有记录，直接转发保存的消息
    target_message_id = relation[0]
    await event.reply("该消息已经转发过，正在重新发送...")
    message = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_message_id)
    if message.media:
        await bot_client.send_file(event.chat_id, message.media, caption=message.text, reply_to=event.message.id)
    else:
        await bot_client.send_message(event.chat_id, message.text, reply_to=event.message.id)

    # 处理转发次数并发送提示消息
    await process_forward_quota(event)


async def group_forward_message(event, grouped_messages):
    await event.reply("该消息组已经转发过，正在重新发送...")
    try:
        target_ids = [target_id for _, target_id in grouped_messages]
        messages = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_ids)
        media_files = [msg.media for msg in messages if msg.media]
        caption = messages[0].text
        await bot_client.send_file(event.chat_id, media_files, caption=caption, reply_to=event.message.id)

        # 处理转发次数并发送提示消息
        await process_forward_quota(event)
    except Exception as e:
        log.exception(f"批量转发媒体组消息失败: {e}")


async def get_media_group_messages(initial_message, message_id, peer, client: TelegramClient) -> list:
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


async def user_handle_media_group(event: events.NewMessage.Event, message, media_group, source_chat_id) -> None:
    try:
        # 先检查数据库中是否有该消息组的转发记录
        if message.grouped_id:
            grouped_messages = find_grouped_messages(source_chat_id, message.grouped_id, PRIVATE_CHAT_ID)
            if grouped_messages:
                await group_forward_message(event, grouped_messages)
                return
            # 发送提示消息
            status_message = await event.reply("转存中，请稍等...")
            # 收集所有文本作为 caption
            captions = [msg.text if msg.text is not None else '' for msg in media_group]
            # 构造相册的文件对象
            album_files = await asyncio.gather(*[prepare_album_file(msg) for msg in media_group if msg.media])
            await bot_client.send_file(event.chat_id, file=album_files, caption=captions, reply_to=event.message.id)
            sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file=album_files, caption=captions)
            # 保存媒体组消息关系到数据库
            save_media_group_relations(
                source_chat_id, media_group,
                PRIVATE_CHAT_ID, sent_messages,
                message.grouped_id
            )
            # 删除提示消息
            await status_message.delete()

            # 处理转发次数并发送提示消息
            await process_forward_quota(event)
        else:
            await user_handle_single_message(event, message, source_chat_id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def user_handle_single_message(event: events.NewMessage.Event, message, source_chat_id) -> None:
    try:
        # 检查数据库中是否有该消息的转发记录
        relation = find_forwarded_message_for_one(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if not relation:
            relation = find_forwarded_message(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if relation:
            await single_forward_message(event, relation)
            return
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
                thumb_path = await user_client.download_media(
                    message,
                    file=thumb_filename,
                    thumb=-1  # -1 表示下载最高质量的缩略图
                )
                await bot_client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                           attributes=message.media.document.attributes, thumb=thumb_path,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          thumb=thumb_path,
                                                          force_document=force_document)
                os.remove(thumb_path)  # 发送后删除缩略图
            elif isinstance(message.media, MessageMediaDocument) and message.media.document.mime_type == 'audio/mpeg':
                await bot_client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                           attributes=message.media.document.attributes,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          force_document=force_document)
            else:
                await bot_client.send_file(event.chat_id, file_path, caption=message.text, reply_to=event.message.id,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text, force_document=force_document)
            os.remove(file_path)  # 发送后删除文件
        else:
            await bot_client.send_message(event.chat_id, message.text, reply_to=event.message.id)
            sent_message = await bot_client.send_message(PeerChannel(PRIVATE_CHAT_ID), message.text)
        # 保存消息关系到数据库
        save_message_relation(
            source_chat_id, message.id,
            PRIVATE_CHAT_ID, sent_message.id,
            0
        )
        # 删除提示消息
        await status_message.delete()

        # 处理转发次数并发送提示消息
        await process_forward_quota(event)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def bot_handle_media_group(event: events.NewMessage.Event, message, media_group, source_chat_id) -> None:
    try:
        # 检查数据库中是否有该消息组的转发记录
        if message.grouped_id:
            grouped_messages = find_grouped_messages(source_chat_id, message.grouped_id, PRIVATE_CHAT_ID)
            if grouped_messages:
                await group_forward_message(event, grouped_messages)
                return
            media_files = [msg.media for msg in media_group if msg.media]
            caption = media_group[0].text
            await bot_client.send_file(event.chat_id, media_files, caption=caption, reply_to=event.message.id)
            sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), media_files, caption=caption)
            # 保存媒体组消息关系到数据库
            save_media_group_relations(
                source_chat_id, media_group,
                PRIVATE_CHAT_ID, sent_messages,
                message.grouped_id
            )
            # 处理转发次数并发送提示消息
            await process_forward_quota(event)
        else:
            await bot_handle_single_message(event, message, source_chat_id)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


async def bot_handle_single_message(event: events.NewMessage.Event, message, source_chat_id) -> None:
    try:
        # 检查数据库中是否有该消息的转发记录
        relation = find_forwarded_message_for_one(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if not relation:
            relation = find_forwarded_message(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if relation:
            await single_forward_message(event, relation)
            return
        if message.media:
            await bot_client.send_file(event.chat_id, message.media, caption=message.text, reply_to=event.message.id)
            sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), message.media,
                                                      caption=message.text)
        else:
            await bot_client.send_message(event.chat_id, message.text, reply_to=event.message.id)
            sent_message = await bot_client.send_message(PeerChannel(PRIVATE_CHAT_ID), message.text)
        # 保存消息关系到数据库
        save_message_relation(
            source_chat_id, message.id,
            PRIVATE_CHAT_ID, sent_message.id,
            0
        )

        # 处理转发次数并发送提示消息
        await process_forward_quota(event)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请过段时间重试")


# 5、业务逻辑与事件处理
# 定义处理新消息的函数
async def on_new_link(event: events.NewMessage.Event) -> None:
    text = event.text
    if not text:
        return
    # 检查消息是否包含有效的Telegram链接
    if not text.startswith(("https://t.me", "http://t.me")):
        return

    # 检查用户转发次数
    user_id = event.sender_id
    free_quota, paid_quota, _ = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    if total_quota <= 0:
        await event.reply("您今日的转发次数已用完！每天0点重置免费次数，或通过支付购买更多次数。")
        return

    query = urllib.parse.urlparse(text).query
    params = dict(urllib.parse.parse_qsl(query))
    is_single = 'single' in text
    is_comment = 'comment' in params
    try:
        chat_id, message_id = await parse_url(text.split('?')[0])
    except ValueError:
        await event.reply("无效链接")
        return
    source_chat_id = chat_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
    if chat_id.isdigit():
        peer = PeerChannel(int(chat_id))
        req_params = {"chat_id": utils.get_peer_id(peer)}
    else:
        peer = chat_id
        req_params = {"chat_id": f"@{chat_id}"}
    result = requests.get(url, params=req_params)
    has_protected_content = False
    peer_type = "channel"
    if result and result.json().get("ok"):
        channel = result.json().get("result")
        has_protected_content = channel.get("has_protected_content", False)
        peer_type = channel.get("type", "channel")
    if not has_protected_content:
        await bot_client.send_message(event.chat_id, "此消息允许转发！无需使用本机器人", reply_to=event.message.id)
        return
    if peer_type == "channel":  # 频道消息处理
        try:
            # 获取指定聊天中的消息
            message = await bot_client.get_messages(peer, ids=message_id)
        except Exception as e:
            log.exception(f"Error: {e}")
            await event.reply("服务器内部错误，请过段时间重试")
            return
        if not message:
            await event.reply("找不到聊天记录！要么无效，要么先以此帐户加入！")
            return
        # 如果链接包含 'single' 参数，则只处理当前消息
        if is_single:
            await bot_handle_single_message(event, message, source_chat_id)
        else:
            media_group = await get_media_group_messages(message, message_id, peer, bot_client)
            await bot_handle_media_group(event, message, media_group, source_chat_id)
    else:  # 群组消息处理
        try:
            # 获取指定聊天中的消息
            message = await user_client.get_messages(peer, ids=message_id)
        except Exception as e:
            log.exception(f"Error: {e}")
            await event.reply("服务器内部错误，请过段时间重试")
            return
        if not message:
            await event.reply("找不到聊天记录！要么无效，要么先以此帐户加入！")
            return
        if is_comment:
            comment_id = int(params.get('comment'))
            # 获取频道实体
            channel = await user_client.get_entity(chat_id)
            comment_message, comment_grouped_id = await get_comment_message(
                user_client, channel, message_id, comment_id
            )
            if is_single:
                await user_handle_single_message(event, comment_message, source_chat_id)
            else:
                # 获取属于同一组的所有消息
                comment_media_group = []
                async for reply in user_client.iter_messages(
                        entity=channel,
                        reply_to=message_id
                ):
                    if reply.grouped_id == comment_grouped_id:
                        comment_media_group.append(reply)
                # 反转列表
                comment_media_group.reverse()
                await user_handle_media_group(event, comment_message, comment_media_group, source_chat_id)
        else:
            result = await message_search(message)
            if result:  # 有结果替换为频道消息
                peer, message_id = result
                message = await bot_client.get_messages(peer, ids=message_id)
                if is_single:
                    await bot_handle_single_message(event, message, source_chat_id)
                else:
                    media_group = await get_media_group_messages(message, message_id, peer, bot_client)
                    await bot_handle_media_group(event, message, media_group, source_chat_id)
            else:
                if is_single:
                    await user_handle_single_message(event, message, source_chat_id)
                else:
                    # 获取属于同一组的消息
                    media_group = await get_media_group_messages(message, message_id, peer, user_client)
                    await user_handle_media_group(event, message, media_group, source_chat_id)


# 事件处理器
def is_authorized(event: events.NewMessage.Event) -> bool:
    # 如果未设置 AUTH_USERS，则默认允许所有私聊
    if not AUTH_USERS:
        return event.is_private
    # 如果设置了 AUTH_USERS，则校验是否在授权列表中
    sender_id = event.sender_id
    sender = event.sender
    # 获取用户名（可能为 None）
    sender_name = sender.username if sender else None

    # 校验 ID 或用户名是否在授权列表中
    # 由于在配置加载时已经添加了带@和不带@的格式，这里直接检查即可
    return (sender_id in AUTH_USERS or (sender_name in AUTH_USERS if sender_name else False)) and event.is_private


# 6. 主函数定义
async def main():
    # 初始化数据库
    init_db()
    #  客户端初始化
    log.info("连接机器人。")
    try:
        # 确保在函数内部可以使用全局变量
        global bot_client, user_client
        # 使用会话字符串初始化Telegram客户端
        bot_client = TelegramClient(
            StringSession(BOT_SESSION), api_id=API_ID, api_hash=API_HASH
        )
        user_client = TelegramClient(
            StringSession(USER_SESSION), api_id=API_ID, api_hash=API_HASH
        )
        # 启动客户端
        await bot_client.start()
        await user_client.start()
    except Exception as e:
        log.exception("启动客户端失败")
        log.exception(f"Error: {e}")
        exit(1)
    # 注册消息处理器
    bot_client.add_event_handler(on_new_link, events.NewMessage(func=is_authorized))
    # 获取机器人的用户信息并开始运行客户端
    ubot_self = await bot_client.get_me()
    log.info("客户端已启动为 %d。", ubot_self.id)
    # 获取 user_client 的用户信息并启动
    u_user = await user_client.get_me()
    log.info("USER_SESSION 已启动为 %d。", u_user.id)
    # 启动并等待两个客户端断开连接
    await bot_client.run_until_disconnected()  # 运行 BOT_SESSION
    await user_client.run_until_disconnected()  # 运行 USER_SESSION


# 7. 程序入口
if __name__ == '__main__':
    asyncio.run(main())
