"""
消息处理模块 - 负责处理和转发消息
"""

import logging

from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    MessageMediaGeo, MessageMediaContact, MessageMediaPoll,
    MessageMediaGame, MessageMediaDice, MessageMediaUnsupported,
    PeerUser, PeerChannel, PeerChat
)

from services.user_manager import check_user_quota

# 初始化日志记录器
log = logging.getLogger("MessageProcessor")

# 定义支持的媒体类型
SUPPORTED_MEDIA_TYPES = (
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage
)

# 不支持的媒体类型
UNSUPPORTED_MEDIA_TYPES = (
    MessageMediaGeo,
    MessageMediaContact,
    MessageMediaPoll,
    MessageMediaGame,
    MessageMediaDice,
    MessageMediaUnsupported
)


async def process_message(event):
    """
    处理接收到的消息并决定是否转发
    
    :param event: 消息事件
    :return: 处理结果
    """
    # 确保是私聊消息
    if not event.is_private:
        return False

    # 获取发送者信息
    sender = await event.get_sender()
    user_id = sender.id

    # 检查用户配额
    paid_quota, free_quota = await check_user_quota(user_id)
    total_quota = paid_quota + free_quota

    # 如果用户没有配额，则提醒并返回
    if total_quota <= 0:
        await event.reply(
            "❌ 您的转发次数已用完\n\n"
            "每天可获得免费转发额度，或通过购买套餐增加转发次数。\n"
            "使用 /buy 命令查看可用套餐。"
        )
        return False

    # 提示用户正确使用机器人
    await event.reply(
        "❓ 请发送Telegram消息链接\n\n"
        "例如：https://t.me/channel_name/123\n\n"
        "使用 /start 命令查看详细使用说明。"
    )
    return False


async def forward_message(message, user_client, target_chat_id):
    """
    使用用户客户端转发消息到目标聊天
    
    :param message: 要转发的消息
    :param user_client: 用户客户端
    :param target_chat_id: 目标聊天ID
    :return: 转发的消息
    """
    try:
        # 使用Telethon的转发功能
        result = await user_client(ForwardMessagesRequest(
            from_peer=message.chat_id,  # 消息的来源聊天
            id=[message.id],  # 消息ID列表
            to_peer=target_chat_id,  # 目标聊天
            with_my_score=False,
            silent=False,
            random_id=[],  # 让Telethon自动生成随机ID
        ))

        log.info(f"消息转发成功: message_id={message.id}, target={target_chat_id}")
        return result
    except Exception as e:
        log.exception(f"转发消息时发生错误: {e}")
        raise


def extract_entity_id(entity):
    """
    从Telegram实体提取ID
    
    :param entity: Telegram实体（PeerUser、PeerChannel等）
    :return: 实体ID
    """
    if isinstance(entity, PeerUser):
        return entity.user_id
    elif isinstance(entity, PeerChannel):
        return entity.channel_id
    elif isinstance(entity, PeerChat):
        return entity.chat_id
    elif isinstance(entity, int):
        return entity
    else:
        return None


async def resolve_chat_id(client, chat_input):
    """
    解析聊天输入为聊天ID
    
    :param client: Telethon客户端
    :param chat_input: 聊天输入（用户名、ID等）
    :return: 聊天ID
    """
    try:
        # 尝试将输入解析为整数ID
        if isinstance(chat_input, str) and chat_input.lstrip('-').isdigit():
            return int(chat_input)

        # 处理用户名格式（@username）
        if isinstance(chat_input, str) and chat_input.startswith('@'):
            username = chat_input[1:]
            entity = await client.get_entity(username)
            return extract_entity_id(entity)

        # 直接尝试获取实体
        entity = await client.get_entity(chat_input)
        return extract_entity_id(entity)

    except Exception as e:
        log.exception(f"解析聊天ID失败: {e}")
        return None
