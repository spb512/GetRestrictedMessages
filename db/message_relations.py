from datetime import datetime
import logging
from telethon.tl.types import Message
from .database import get_db_connection

# 初始化日志记录器
log = logging.getLogger("MessageRelations")

def save_message_relation(source_chat_id, source_message_id, target_chat_id, target_message_id, grouped_id=None):
    """保存消息转发关系"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            cursor.execute('''
            INSERT INTO message_relations 
            (source_chat_id, source_message_id, target_chat_id, target_message_id, grouped_id, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
            str(source_chat_id), source_message_id, str(target_chat_id), target_message_id, grouped_id, created_at))
            conn.commit()
        except Exception as e:
            if 'UNIQUE constraint failed' in str(e):
                # 如果已存在，则更新
                created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                cursor.execute('''
                UPDATE message_relations 
                SET target_message_id = ?, grouped_id = ?, created_at = ?
                WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ?
                ''', (
                target_message_id, grouped_id, created_at, str(source_chat_id), source_message_id, str(target_chat_id)))
                conn.commit()
            else:
                log.exception(f"保存消息关系失败: {e}")


def save_media_group_relations(source_chat_id, source_messages, target_chat_id, target_messages, grouped_id=None):
    """批量保存媒体组消息关系"""
    with get_db_connection() as conn:
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


def find_forwarded_message(source_chat_id, source_message_id, target_chat_id):
    """查找已转发的消息（针对媒体组）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT target_message_id, grouped_id FROM message_relations
        WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ? and grouped_id != 0
        ''', (str(source_chat_id), source_message_id, str(target_chat_id)))
        result = cursor.fetchone()
    return result


def find_forwarded_message_for_one(source_chat_id, source_message_id, target_chat_id):
    """查找已转发的单条消息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT target_message_id, grouped_id FROM message_relations
        WHERE source_chat_id = ? AND source_message_id = ? AND target_chat_id = ? AND grouped_id = 0
        ''', (str(source_chat_id), source_message_id, str(target_chat_id)))
        result = cursor.fetchone()
    return result


def find_grouped_messages(source_chat_id, grouped_id, target_chat_id):
    """查找相同组ID的所有转发消息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT source_message_id, target_message_id FROM message_relations 
        WHERE source_chat_id = ? AND grouped_id = ? AND target_chat_id = ?
        ''', (str(source_chat_id), grouped_id, str(target_chat_id)))
        results = cursor.fetchall()
    return results 