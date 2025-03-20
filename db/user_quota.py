import logging
from datetime import datetime

from .database import get_db_connection

# 初始化日志记录器
log = logging.getLogger("UserQuota")


def get_user_quota(user_id):
    """获取用户当前的转发次数配额"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        try:
            # 立即开始事务，获取写锁
            cursor.execute('BEGIN IMMEDIATE')
            
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

            return free_quota, paid_quota, current_date
        except Exception as e:
            log.exception(f"获取用户配额失败: {e}")
            conn.rollback()
            return 0, 0, datetime.now().strftime('%Y-%m-%d')


def decrease_user_quota(user_id):
    """减少用户的转发次数，优先使用免费次数"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            # 立即开始事务，获取写锁
            cursor.execute('BEGIN IMMEDIATE')
            
            # 直接从数据库获取最新配额，避免使用可能过时的缓存值
            cursor.execute('SELECT free_quota, paid_quota FROM user_forward_quota WHERE user_id = ?',
                           (str(user_id),))
            result = cursor.fetchone()
            
            if not result:
                # 用户不存在，创建记录
                current_date = datetime.now().strftime('%Y-%m-%d')
                cursor.execute(
                    'INSERT INTO user_forward_quota (user_id, free_quota, paid_quota, last_reset_date) VALUES (?, ?, ?, ?)',
                    (str(user_id), 5, 0, current_date)
                )
                free_quota, paid_quota = 5, 0
            else:
                free_quota, paid_quota = result

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
                conn.rollback()
                return False

            conn.commit()
            return True
        except Exception as e:
            log.exception(f"减少用户配额失败: {e}")
            conn.rollback()
            return False


def add_paid_quota(user_id, amount):
    """为用户添加付费转发次数"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            # 立即开始事务，获取写锁
            cursor.execute('BEGIN IMMEDIATE')
            
            # 直接从数据库获取最新配额
            cursor.execute('SELECT free_quota, paid_quota, last_reset_date FROM user_forward_quota WHERE user_id = ?',
                           (str(user_id),))
            result = cursor.fetchone()
            
            current_date = datetime.now().strftime('%Y-%m-%d')
            
            if not result:
                # 新用户，创建记录
                cursor.execute(
                    'INSERT INTO user_forward_quota (user_id, free_quota, paid_quota, last_reset_date) VALUES (?, ?, ?, ?)',
                    (str(user_id), 5, amount, current_date)
                )
                paid_quota = amount
            else:
                free_quota, paid_quota, last_reset_date = result
                # 增加付费次数
                paid_quota += amount
                cursor.execute(
                    'UPDATE user_forward_quota SET paid_quota = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                    (paid_quota, str(user_id))
                )

            conn.commit()
            return paid_quota
        except Exception as e:
            log.exception(f"增加用户付费配额失败: {e}")
            conn.rollback()
            return 0


def reset_all_free_quotas():
    """重置所有用户的免费次数（定时任务使用）"""
    current_date = datetime.now().strftime('%Y-%m-%d')

    with get_db_connection() as conn:
        cursor = conn.cursor()

        try:
            # 立即开始事务，获取写锁
            cursor.execute('BEGIN IMMEDIATE')
            
            # 查找所有昨天的记录（last_reset_date不等于今天）
            cursor.execute('SELECT user_id FROM user_forward_quota WHERE last_reset_date != ?', (current_date,))
            users = cursor.fetchall()

            if not users:
                log.info("没有需要重置的用户免费次数")
                conn.rollback()
                return 0

            # 更新所有这些用户的免费次数和重置日期
            cursor.execute('''
            UPDATE user_forward_quota 
            SET free_quota = 5, 
                last_reset_date = ?, 
                updated_at = CURRENT_TIMESTAMP
            WHERE last_reset_date != ?
            ''', (current_date, current_date))

            count = cursor.rowcount
            conn.commit()
            log.info(f"已重置 {count} 名用户的免费次数")
            return count
        except Exception as e:
            log.exception(f"重置用户免费次数失败: {e}")
            conn.rollback()
            return 0
