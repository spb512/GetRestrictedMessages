import logging
import uuid

from .database import get_db_connection
from .user_quota import add_paid_quota

# 初始化日志记录器
log = logging.getLogger("Invite")


def generate_invite_code():
    """生成唯一的邀请码"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        while True:
            # 生成新的邀请码
            invite_code = str(uuid.uuid4())[:8].upper()
            # 检查是否已存在
            cursor.execute('SELECT COUNT(*) FROM invite_relations WHERE invite_code = ?', (invite_code,))
            if cursor.fetchone()[0] == 0:
                return invite_code


def get_user_invite_code(user_id):
    """获取用户的邀请码"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 检查用户是否已有邀请码
        cursor.execute('SELECT invite_code FROM invite_relations WHERE inviter_id = ?', (str(user_id),))
        result = cursor.fetchone()

        if not result:
            # 生成新的邀请码
            invite_code = generate_invite_code()
            cursor.execute('''
            INSERT INTO invite_relations (inviter_id, invite_code, invitee_id)
            VALUES (?, ?, NULL)
            ''', (str(user_id), invite_code))
            conn.commit()
            return invite_code

    return result[0]


def process_invite(invite_code, invitee_id):
    """处理邀请关系并发放奖励"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        try:
            # 检查邀请码是否有效
            cursor.execute('''
            SELECT inviter_id, created_at 
            FROM invite_relations 
            WHERE invite_code = ? AND invitee_id IS NULL
            ''', (invite_code,))
            result = cursor.fetchone()

            if not result:
                return False, "无效的邀请码"

            inviter_id, created_at = result
            
            # 检查邀请人是否已达到邀请上限
            cursor.execute('SELECT COUNT(*) FROM invite_relations WHERE inviter_id = ? AND invitee_id IS NOT NULL',
                           (inviter_id,))
            invite_count = cursor.fetchone()[0]
            if invite_count >= 20:
                return False, "邀请人已达到20人邀请上限"

            # 检查是否已经被邀请过
            cursor.execute('SELECT inviter_id FROM invite_relations WHERE invitee_id = ?', (str(invitee_id),))
            if cursor.fetchone():
                return False, "您已经被其他用户邀请过了"
                
            # 检查用户是否已经使用过机器人
            # 查询用户配额表，如果存在记录则表示已经使用过机器人
            cursor.execute('SELECT user_id FROM user_forward_quota WHERE user_id = ?', (str(invitee_id),))
            if cursor.fetchone():
                return False, "您已经使用过机器人，无法被邀请"

            # 检查是否自己邀请自己
            if str(inviter_id) == str(invitee_id):
                return False, "不能邀请自己"

            # 添加邀请关系
            cursor.execute('''
            INSERT INTO invite_relations (inviter_id, invitee_id, invite_code)
            VALUES (?, ?, ?)
            ''', (inviter_id, str(invitee_id), invite_code))

            conn.commit()

            # 给邀请人增加奖励次数
            add_paid_quota(inviter_id, 5)

            return True, "邀请成功！邀请人已获得5次付费转发次数"

        except Exception as e:
            log.exception(f"处理邀请失败: {e}")
            conn.rollback()
            return False, "处理邀请时发生错误"


def get_invite_stats(user_id):
    """获取用户的邀请统计信息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 获取成功邀请的人数（invitee_id 不为 NULL 的记录）
        cursor.execute('SELECT COUNT(*) FROM invite_relations WHERE inviter_id = ? AND invitee_id IS NOT NULL',
                       (str(user_id),))
        invite_count = cursor.fetchone()[0]

        # 获取获得的奖励次数
        cursor.execute('SELECT paid_quota FROM user_forward_quota WHERE user_id = ?', (str(user_id),))
        result = cursor.fetchone()
        reward_count = result[0] if result else 0

    return invite_count, reward_count
