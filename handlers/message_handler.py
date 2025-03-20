import asyncio
import logging
import os
import tempfile
import time
import urllib.parse

import requests
import aiohttp
import aiofiles
import aiofiles.os
from aiohttp_socks import ProxyConnector
from telethon import events, utils
from telethon.errors import ChannelPrivateError, InviteHashInvalidError, UserAlreadyParticipantError, \
    UserBannedInChannelError, InviteRequestSentError, UserRestrictedError, InviteHashExpiredError, FloodWaitError
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import MessageMediaDocument, PeerChannel, Message, MessageMediaPhoto, InputMediaUploadedPhoto, \
    InputMediaUploadedDocument

from db import (
    get_user_quota, decrease_user_quota, save_message_relation, save_media_group_relations,
    find_forwarded_message, find_forwarded_message_for_one, find_grouped_messages
)

# 初始化日志记录器
log = logging.getLogger("MessageHandler")

# 获取全局变量
from config import PRIVATE_CHAT_ID, RANGE

# 附加信息
addInfo = "\n\n♋[91转发|机器人](https://t.me/91_zf_bot)👉：@91_zf_bot\n♍[91转发|聊天👉：](https://t.me/91_zf_bot)@91_zf_group\n🔯[91转发|通知👉：](https://t.me/91_zf_channel)@91_zf_channel"

# 用户锁字典，防止并发请求
USER_LOCKS = {}


async def create_temp_file(suffix=""):
    """创建临时文件的异步封装"""
    try:
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temp_name = temp_file.name
        temp_file.close()
        return temp_name
    except Exception as e:
        log.exception(f"创建临时文件失败: {e}")
        raise


async def process_forward_quota(event):
    """处理转发次数减少并发送提示消息的公共方法"""
    # 减少用户转发次数
    user_id = event.sender_id
    decrease_user_quota(user_id)

    # 获取用户剩余次数
    free_quota, paid_quota, _ = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    # 在转发成功后告知用户剩余次数
    await event.reply(f"转发成功！您剩余次数 {total_quota} 次转发机会（免费 {free_quota} 次，付费 {paid_quota} 次）")


async def replace_message(message: Message, bot_token):
    if message.fwd_from and message.fwd_from.from_id and message.fwd_from.channel_post:
        peer_id = utils.get_peer_id(message.fwd_from.from_id)
        message_id = message.fwd_from.channel_post
        url = f"https://api.telegram.org/bot{bot_token}/getChat"
        req_params = {"chat_id": peer_id}
        
        # 获取代理设置
        proxy = None
        if os.environ.get('USE_PROXY', 'False').lower() == 'true':
            proxy_type = os.environ.get('PROXY_TYPE', 'socks5')
            proxy_host = os.environ.get('PROXY_HOST', '127.0.0.1')
            proxy_port = int(os.environ.get('PROXY_PORT', '10808'))
            proxy = f"{proxy_type}://{proxy_host}:{proxy_port}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=req_params, proxy=proxy) as response:
                peer_type = "channel"
                channel_username = None
                if response.status == 200:
                    result = await response.json()
                    if result and result.get("ok"):
                        channel = result.get("result")
                        peer_type = channel.get("type", "channel")
                        channel_username = channel.get("username")
                if peer_type == "channel" and channel_username:
                    return channel_username, message_id
    return None


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


async def prepare_album_file(msg: Message, user_client, bot_client):
    """准备相册文件的上传对象"""
    # 为临时文件添加扩展名
    suffix = ".jpg" if isinstance(msg.media,
                                  MessageMediaPhoto) else ".mp4" if "video/mp4" in msg.media.document.mime_type else ""
    temp_name = None
    thumb_path = None
    file_path = None

    try:
        temp_name = await create_temp_file(suffix=suffix)
        file_path = await user_client.download_media(msg, file=temp_name)
        if isinstance(msg.media, MessageMediaPhoto):
            return InputMediaUploadedPhoto(file=await bot_client.upload_file(file_path))
        elif isinstance(msg.media, MessageMediaDocument):
            if (msg.media.document.mime_type == "video/mp4" and msg.media.document.size > 10 * 1024 * 1024) or (
                    msg.media.document.mime_type == "image/heic"):
                thumb_path = await user_client.download_media(
                    msg, file=f"{temp_name}_thumb.jpg", thumb=-1
                )
            # 对于文档类型，返回带有特殊标记的对象，以便后续处理
            return InputMediaUploadedDocument(
                file=await bot_client.upload_file(file_path),
                thumb=await bot_client.upload_file(thumb_path) if thumb_path else None,
                mime_type=msg.media.document.mime_type or "application/octet-stream",
                attributes=msg.media.document.attributes,
                nosound_video=True
            )
    finally:
        # 删除临时文件
        if file_path and os.path.exists(file_path):
            await aiofiles.os.remove(file_path)
        if thumb_path and os.path.exists(thumb_path):
            await aiofiles.os.remove(thumb_path)
        if temp_name and os.path.exists(temp_name):
            await aiofiles.os.remove(temp_name)


async def get_comment_message(client, channel, message_id, comment_id):
    """从评论中获取指定的评论消息及其 grouped_id"""
    async for reply in client.iter_messages(
            entity=channel,
            reply_to=message_id
    ):
        if reply.id == comment_id:
            return reply, reply.grouped_id  # 返回匹配的评论消息及其 grouped_id
    return None, None  # 如果没有找到，返回 None


async def single_forward_message(event, relation, bot_client):
    # 如果有记录，直接转发保存的消息
    target_message_id = relation[0]
    # await event.reply("该消息已经转发过，正在重新发送...")
    message = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_message_id)
    if message.media:
        await bot_client.send_file(event.chat_id, message.media, caption=message.text + addInfo,
                                   buttons=message.buttons,
                                   reply_to=event.message.id)
    else:
        await bot_client.send_message(event.chat_id, message.text + addInfo, buttons=message.buttons,
                                      reply_to=event.message.id)

    # 处理转发次数并发送提示消息
    await process_forward_quota(event)


async def group_forward_message(event, grouped_messages, bot_client):
    target_ids = [target_id for _, target_id in grouped_messages]
    messages = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_ids)
    media_files = [msg.media for msg in messages if msg.media]
    # 检查媒体组中是否有文档类型的媒体
    has_document = any(isinstance(msg.media, MessageMediaDocument) for msg in messages if msg.media)
    if has_document:
        media_captions = [msg.text if msg.text else "" for msg in messages]
        media_captions[-1] = media_captions[-1] + addInfo  # 只在最后一个媒体添加caption和附加信息
        await bot_client.send_file(event.chat_id, media_files, caption=media_captions, reply_to=event.message.id)
    else:
        caption = messages[0].text
        # 按钮信息追加到原 caption 后面
        await bot_client.send_file(event.chat_id, media_files, caption=caption + addInfo, reply_to=event.message.id)
    # 处理转发次数并发送提示消息
    await process_forward_quota(event)


async def get_media_group_messages(initial_message, message_id, peer, client) -> list:
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


async def user_handle_media_group(event: events.NewMessage.Event, message, media_group, source_chat_id, bot_client,
                                  user_client) -> None:
    try:
        # 先检查数据库中是否有该消息组的转发记录
        if message.grouped_id:
            grouped_messages = find_grouped_messages(source_chat_id, message.grouped_id, PRIVATE_CHAT_ID)
            if grouped_messages:
                await group_forward_message(event, grouped_messages, bot_client)
                return
            # 发送提示消息
            status_message = await event.reply("转存中，请稍等...")

            # 构造相册的文件对象
            album_files = await asyncio.gather(
                *[prepare_album_file(msg, user_client, bot_client) for msg in media_group if msg.media])

            # 检查媒体组中是否有文档类型的媒体
            has_document = any(isinstance(msg.media, MessageMediaDocument) for msg in media_group if msg.media)
            if has_document:
                media_captions = [msg.text if msg.text else "" for msg in media_group]
                sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file=album_files,
                                                           caption=media_captions)
            else:
                captions = media_group[0].text
                sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file=album_files,
                                                           caption=captions)
            # 保存媒体组消息关系到数据库
            save_media_group_relations(
                source_chat_id, media_group,
                PRIVATE_CHAT_ID, sent_messages,
                message.grouped_id
            )

            messages = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=sent_messages)
            media_files = [msg.media for msg in messages if msg.media]

            # 按钮信息追加到原 caption 后面，如果有文档类型媒体则使用列表形式的caption
            if has_document:
                media_captions = [msg.text if msg.text else "" for msg in messages]
                media_captions[-1] = media_captions[-1] + addInfo  # 只在最后一个媒体添加caption和附加信息
                await bot_client.send_file(event.chat_id, media_files, caption=media_captions,
                                           reply_to=event.message.id)
            else:
                caption = messages[0].text
                await bot_client.send_file(event.chat_id, media_files, caption=caption + addInfo,
                                           reply_to=event.message.id)

            # 删除提示消息
            await status_message.delete()
            # 处理转发次数并发送提示消息
            await process_forward_quota(event)
        else:
            await user_handle_single_message(event, message, source_chat_id, bot_client, user_client)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请联系管理员")
    finally:
        # 清理其他资源（如果有的话）
        pass


async def user_handle_single_message(event: events.NewMessage.Event, message, source_chat_id, bot_client,
                                     user_client) -> None:
    try:
        # 检查数据库中是否有该消息的转发记录
        relation = find_forwarded_message_for_one(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if not relation:
            relation = find_forwarded_message(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if relation:
            await single_forward_message(event, relation, bot_client)
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
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          thumb=thumb_path,
                                                          buttons=message.buttons,
                                                          force_document=force_document)
                await aiofiles.os.remove(thumb_path)  # 发送后删除缩略图
            elif isinstance(message.media, MessageMediaDocument) and message.media.document.mime_type == 'audio/mpeg':
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          buttons=message.buttons,
                                                          force_document=force_document)
            else:
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text, nosound_video=True,
                                                          buttons=message.buttons,
                                                          force_document=force_document)
            await aiofiles.os.remove(file_path)  # 发送后删除文件
        else:
            sent_message = await bot_client.send_message(PeerChannel(PRIVATE_CHAT_ID), message.text,
                                                         buttons=message.buttons)
        # 保存消息关系到数据库
        save_message_relation(
            source_chat_id, message.id,
            PRIVATE_CHAT_ID, sent_message.id,
            0
        )
        message = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=sent_message)
        if message.media:
            await bot_client.send_file(event.chat_id, message.media, caption=message.text + addInfo,
                                       buttons=message.buttons,
                                       reply_to=event.message.id)
        else:
            await bot_client.send_message(event.chat_id, message.text + addInfo, buttons=message.buttons,
                                          reply_to=event.message.id)

        # 删除提示消息
        await status_message.delete()

        # 处理转发次数并发送提示消息
        await process_forward_quota(event)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请联系管理员")
    finally:
        # 清理其他资源（如果有的话）
        pass


async def bot_handle_media_group(event: events.NewMessage.Event, message, media_group, source_chat_id,
                                 bot_client) -> None:
    try:
        # 检查数据库中是否有该消息组的转发记录
        if message.grouped_id:
            grouped_messages = find_grouped_messages(source_chat_id, message.grouped_id, PRIVATE_CHAT_ID)
            if grouped_messages:
                await group_forward_message(event, grouped_messages, bot_client)
                return
            media_files = [msg.media for msg in media_group if msg.media]
            caption = media_group[0].text
            sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), media_files,
                                                       caption=caption)
            await bot_client.send_file(event.chat_id, media_files, caption=caption + addInfo, reply_to=event.message.id)
            # 保存媒体组消息关系到数据库
            save_media_group_relations(
                source_chat_id, media_group,
                PRIVATE_CHAT_ID, sent_messages,
                message.grouped_id
            )
            # 处理转发次数并发送提示消息
            await process_forward_quota(event)
        else:
            await bot_handle_single_message(event, message, source_chat_id, bot_client)
    except Exception as e:
        log.exception(f"Error: {e}")
        await event.reply("服务器内部错误，请联系管理员")
    finally:
        # 清理其他资源（如果有的话）
        pass


async def bot_handle_single_message(event: events.NewMessage.Event, message, source_chat_id, bot_client) -> None:
    try:
        # 检查数据库中是否有该消息的转发记录
        relation = find_forwarded_message_for_one(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if not relation:
            relation = find_forwarded_message(source_chat_id, message.id, PRIVATE_CHAT_ID)
        if relation:
            await single_forward_message(event, relation, bot_client)
            return
        if message.media:
            sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), message.media,
                                                      buttons=message.buttons,
                                                      caption=message.text)
            await bot_client.send_file(event.chat_id, message.media, caption=message.text + addInfo,
                                       buttons=message.buttons,
                                       reply_to=event.message.id)
        else:
            sent_message = await bot_client.send_message(PeerChannel(PRIVATE_CHAT_ID), message.text)
            await bot_client.send_message(event.chat_id, message.text + addInfo, reply_to=event.message.id)
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
        await event.reply("服务器内部错误，请联系管理员")
    finally:
        # 清理其他资源（如果有的话）
        pass


async def on_new_link(event: events.NewMessage.Event, bot_client, user_client, system_overloaded=False,
                      bot_token=None) -> None:
    """处理新的链接消息"""
    text = event.text
    if not text:
        return

    # 检查是否是邀请链接 (t.me/+)
    if "t.me/+" in text:
        try:
            # 提取邀请链接哈希部分
            invite_hash = text.split("/")[-1].replace("+", "")
            await user_client(ImportChatInviteRequest(invite_hash))
            await event.reply("已成功加入该群组/频道！现在请发送你需要转发的消息链接。")
            return
        except InviteHashInvalidError:
            await event.reply("邀请链接无效或已过期。")
            return
        except InviteHashExpiredError:  # 这里新增捕获
            log.info("邀请链接已过期或被封禁")
            await event.reply("邀请链接已过期或被封禁，请联系管理员获取新的链接。")
            return
        except UserAlreadyParticipantError:
            log.info("已经该群中,继续")
            await event.reply("已成功加入该群组/频道！现在请发送你需要转发的消息链接。")
            return
        except UserBannedInChannelError:
            log.info("被该群封禁，无法加入")
            await event.reply("加入群组/频道失败,请联系管理员。")
            return
        except InviteRequestSentError:
            log.info("等待管理员审核")
            await event.reply("等待管理员审核,请过段时间再发送消息链接")
            return
        except UserRestrictedError:
            log.info("账号受限")
            await event.reply("加入群组/频道失败,请联系管理员。")
            return
        except FloodWaitError:
            log.info("触发滥用限制")
            await event.reply("加入群组/频道失败,请联系管理员。")
            return
        except Exception as e:
            log.exception(f"加入群组/频道失败: {e}")
            await event.reply("加入群组/频道失败,请联系管理员。")
            return

    # 检查消息是否包含有效的Telegram链接
    if not text.startswith(("https://t.me", "http://t.me")):
        return
    # 检查系统负载
    if system_overloaded:
        await event.reply("系统当前负载较高，请稍后再试...")
        return
    user_id = event.sender_id
    # 检查用户是否已经有正在处理的请求
    if user_id not in USER_LOCKS:
        USER_LOCKS[user_id] = asyncio.Lock()
    
    # 检查锁是否已被占用
    if USER_LOCKS[user_id].locked():
        await event.reply("您有一个正在处理的转发请求，请等待完成后再发送新的请求。")
        return

    # 检查用户转发次数
    free_quota, paid_quota, _ = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    if total_quota <= 0:
        await event.reply("您今日的转发次数已用完！每天0点重置免费次数，或通过支付购买更多次数。")
        return

    try:
        # 使用 async with 获取锁
        async with USER_LOCKS[user_id]:
            # 处理消息转发逻辑
            query = urllib.parse.urlparse(text).query
            params = dict(urllib.parse.parse_qsl(query))
            try:
                chat_id, message_id = await parse_url(text.split('?')[0])
            except ValueError:
                await event.reply("无效链接")
                return
            source_chat_id = chat_id
            is_single = 'single' in text
            is_digit = chat_id.isdigit()

            import requests
            url = f"https://api.telegram.org/bot{bot_token}/getChat"
            if is_digit:  # 私有频道和私有群组
                peer = PeerChannel(int(chat_id))
                is_thread = 'thread' in params
                try:
                    # 获取指定聊天中的消息
                    message = await user_client.get_messages(peer, ids=message_id)
                except ValueError as e:
                    if is_thread:
                        await event.reply("请先发送频道里任意一条消息的链接，再发送评论区消息的链接")
                    else:
                        await event.reply("私人频道/私人群组，请先发送入群邀请链接，然后再发送消息链接。")
                    return
                except ChannelPrivateError as e:
                    await event.reply("此群组/频道无法访问，或你已被拉黑(踢了)")
                    return
                except Exception as e:
                    log.exception(f"Error: {e}")
                    await event.reply("服务器内部错误，请联系管理员")
                    return
                entity = await user_client.get_entity(peer)
                from telethon.tl.types import Channel
                if isinstance(entity, Channel) and not entity.megagroup:  # 频道
                    if is_single:
                        await user_handle_single_message(event, message, source_chat_id, bot_client, user_client)
                    else:
                        media_group = await get_media_group_messages(message, message_id, peer, user_client)
                        await user_handle_media_group(event, message, media_group, source_chat_id, bot_client, user_client)
                else:
                    if is_thread:  # 评论消息
                        if is_single:
                            await user_handle_single_message(event, message, source_chat_id, bot_client, user_client)
                        else:
                            media_group = await get_media_group_messages(message, message_id, peer, user_client)
                            await user_handle_media_group(event, message, media_group, source_chat_id, bot_client, user_client)
                    else:
                        result = await replace_message(message, bot_token)
                        if result:
                            peer, message_id = result
                            message = await bot_client.get_messages(peer, ids=message_id)
                            if is_single:
                                await bot_handle_single_message(event, message, source_chat_id, bot_client)
                            else:
                                media_group = await get_media_group_messages(message, message_id, peer, bot_client)
                                await bot_handle_media_group(event, message, media_group, source_chat_id, bot_client)
                        else:
                            if is_single:
                                await user_handle_single_message(event, message, source_chat_id, bot_client, user_client)
                            else:
                                media_group = await get_media_group_messages(message, message_id, peer, user_client)
                                await user_handle_media_group(event, message, media_group, source_chat_id, bot_client,
                                                              user_client)

            else:  # 公开频道和公开群组
                peer = chat_id
                req_params = {"chat_id": f"@{chat_id}"}
                
                # 获取代理设置
                proxy = None
                if os.environ.get('USE_PROXY', 'False').lower() == 'true':
                    proxy_type = os.environ.get('PROXY_TYPE', 'socks5')
                    proxy_host = os.environ.get('PROXY_HOST', '127.0.0.1')
                    proxy_port = int(os.environ.get('PROXY_PORT', '10808'))
                    proxy = f"{proxy_type}://{proxy_host}:{proxy_port}"
                    
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=req_params, proxy=proxy) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result and result.get("ok"):
                                channel = result.get("result")
                                has_protected_content = channel.get("has_protected_content", False)
                                peer_type = channel.get("type")
                        else:
                            await event.reply("服务器内部错误，请联系管理员")
                            return
                is_channel = peer_type == "channel"
                if is_channel:  # 公开频道
                    try:
                        # 获取指定聊天中的消息
                        message = await bot_client.get_messages(peer, ids=message_id)
                    except Exception as e:
                        log.exception(f"Error: {e}")
                        await event.reply("服务器内部错误，请联系管理员")
                        return
                    is_comment = 'comment' in params
                    if is_comment:
                        comment_id = int(params.get('comment'))
                        # 获取频道实体
                        channel = await user_client.get_entity(chat_id)
                        comment_message, comment_grouped_id = await get_comment_message(
                            user_client, channel, message_id, comment_id
                        )
                        # 1、有评论-单个
                        if is_single:
                            await user_handle_single_message(event, comment_message, source_chat_id, bot_client, user_client)
                        # 2、有评论-多个
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
                            await user_handle_media_group(event, comment_message, comment_media_group, source_chat_id,
                                                          bot_client, user_client)
                    else:
                        if not has_protected_content:
                            await event.reply("此消息允许转发！无需使用本机器人")
                            return
                        # 3、无评论-单个
                        if is_single:
                            await bot_handle_single_message(event, message, source_chat_id, bot_client)
                        # 4、无评论-多个
                        else:
                            media_group = await get_media_group_messages(message, message_id, peer, bot_client)
                            await bot_handle_media_group(event, message, media_group, source_chat_id, bot_client)
                else:  # 公开群组
                    if not has_protected_content:
                        await event.reply("此消息允许转发！无需使用本机器人")
                        return
                    try:
                        # 获取指定聊天中的消息
                        message = await user_client.get_messages(peer, ids=message_id)
                    except Exception as e:
                        log.exception(f"Error: {e}")
                        await event.reply("服务器内部错误，请联系管理员")
                        return
                    result = await replace_message(message, bot_token)
                    if result:
                        peer, message_id = result
                        message = await bot_client.get_messages(peer, ids=message_id)
                        # await event.reply("替换频道消息，免下载转发")
                        # 5、有替代-单个
                        if is_single:
                            await bot_handle_single_message(event, message, source_chat_id, bot_client)
                        # 6、有替代-多个
                        else:
                            media_group = await get_media_group_messages(message, message_id, peer, bot_client)
                            await bot_handle_media_group(event, message, media_group, source_chat_id, bot_client)
                    else:
                        # 7、无替代-单个
                        if is_single:
                            await user_handle_single_message(event, message, source_chat_id, bot_client, user_client)
                        # 8、无替代-多个
                        else:
                            media_group = await get_media_group_messages(message, message_id, peer, user_client)
                            await user_handle_media_group(event, message, media_group, source_chat_id, bot_client, user_client)

    except Exception as e:
        log.exception(f"处理消息时发生错误: {e}")
        await event.reply("服务器内部错误，请联系管理员")
    finally:
        # 清理其他资源（如果有的话）
        pass
