import logging
import random
import uuid
from datetime import datetime
from .database import get_db_connection
from .user_quota import add_paid_quota

# 初始化日志记录器
log = logging.getLogger("Orders")

# USDT钱包地址 - 应从环境变量获取
USDT_WALLET = "TM9tn28zug456sMkd5AZp9cDCRMFxrH7EG"  # 这是一个示例，实际应从配置中获取

def generate_order_id():
    """生成唯一的订单ID"""
    return str(uuid.uuid4())[:12].upper()

def update_order_tx_info(order_id, tx_hash, memo=""):
    """更新订单的交易信息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
            UPDATE orders 
            SET tx_hash = ?, memo = ?, updated_at = ? 
            WHERE order_id = ?
            ''', (tx_hash, memo, updated_at, order_id))
            
            conn.commit()
            log.info(f"订单 {order_id} 交易信息已更新，交易哈希: {tx_hash}")
            return True
        except Exception as e:
            log.exception(f"更新订单交易信息失败: {e}")
            return False

def update_order_last_checked(order_id):
    """更新订单的最后检查时间"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            last_checked = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
            UPDATE orders 
            SET last_checked = ?, updated_at = ? 
            WHERE order_id = ?
            ''', (last_checked, last_checked, order_id))
            
            conn.commit()
            return True
        except Exception as e:
            log.exception(f"更新订单检查时间失败: {e}")
            return False

def cancel_expired_order(order_id):
    """取消过期订单"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            # 检查订单是否存在且状态为pending
            cursor.execute('SELECT status FROM orders WHERE order_id = ?', (order_id,))
            result = cursor.fetchone()
            
            if not result:
                log.warning(f"找不到订单 {order_id}")
                return False
                
            status = result[0]
            if status != "pending":
                log.warning(f"订单 {order_id} 状态不是pending，当前状态: {status}")
                return False
            
            # 更新订单状态为canceled
            updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
            UPDATE orders 
            SET status = "canceled", updated_at = ? 
            WHERE order_id = ?
            ''', (updated_at, order_id))
            
            conn.commit()
            log.info(f"订单 {order_id} 已取消")
            return True
        except Exception as e:
            log.exception(f"取消订单失败: {e}")
            conn.rollback()
            return False

def get_all_pending_orders():
    """获取所有待处理的订单"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE status = "pending"')
        orders = cursor.fetchall()
    return orders

def create_new_order(user_id, package_name, amount, quota_amount):
    """创建新订单，并生成独特的金额"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        order_id = generate_order_id()
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 为订单生成独特金额：基础金额 + 0.00001-0.00099的随机小数
        unique_cents = random.randint(1, 99) / 100000
        unique_amount = round(amount + unique_cents, 5)  # 保留5位小数

        try:
            cursor.execute('''
            INSERT INTO orders 
            (order_id, user_id, package_name, amount, quota_amount, payment_address, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
            order_id, str(user_id), package_name, unique_amount, quota_amount, USDT_WALLET, created_at, created_at))

            conn.commit()
            log.info(f"为用户 {user_id} 创建了新订单 {order_id}，金额: {unique_amount}$")
            return order_id, unique_amount
        except Exception as e:
            log.exception(f"创建订单失败: {e}")
            return None, None

def get_order_by_id(order_id):
    """通过订单ID获取订单信息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
        order = cursor.fetchone()

    return order

def get_user_pending_orders(user_id):
    """获取用户的待处理订单"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE user_id = ? AND status = "pending" ORDER BY created_at DESC',
                      (str(user_id),))
        orders = cursor.fetchall()
    return orders

def complete_order(order_id, tx_hash=None):
    """完成订单并增加用户次数"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        try:
            # 获取订单信息
            cursor.execute('SELECT user_id, quota_amount, status FROM orders WHERE order_id = ?', (order_id,))
            order = cursor.fetchone()

            if not order:
                log.error(f"找不到订单 {order_id}")
                return False

            user_id, quota_amount, status = order

            if status != "pending":
                log.warning(f"订单 {order_id} 已处理过，当前状态: {status}")
                return False

            # 更新订单状态
            completed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if tx_hash:
                cursor.execute('''
                UPDATE orders 
                SET status = "completed", tx_hash = ?, updated_at = ?, completed_at = ? 
                WHERE order_id = ?
                ''', (tx_hash, completed_at, completed_at, order_id))
            else:
                cursor.execute('''
                UPDATE orders 
                SET status = "completed", updated_at = ?, completed_at = ? 
                WHERE order_id = ?
                ''', (completed_at, completed_at, order_id))
            conn.commit()
            
            # 增加用户次数
            add_paid_quota(user_id, quota_amount)
            log.info(f"订单 {order_id} 已完成，为用户 {user_id} 增加了 {quota_amount} 次付费转发次数")
            return True
        except Exception as e:
            log.exception(f"完成订单失败: {e}")
            conn.rollback()
            return False 