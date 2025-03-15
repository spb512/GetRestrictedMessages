"""
Telethon 消息转发机器人
"""

# 1. 导入模块
import asyncio
import logging
import os
import random
import sqlite3
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta

import requests
from decouple import config
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault
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
# USDT(TRC20)钱包地址 - 用于接收付款
USDT_WALLET = config("USDT_WALLET", default="TRxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
# TRONGRID API 密钥 - 用于查询交易
TRONGRID_API_KEY = config("TRONGRID_API_KEY", default="")
# TRC20 USDT 合约地址
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# 自动检查交易的间隔（秒）
TRANSACTION_CHECK_INTERVAL = config("TRANSACTION_CHECK_INTERVAL", default=60, cast=int)
# 管理员用户ID，用于接收订单通知
ADMIN_ID = config("ADMIN_ID", default=None, cast=int)
# 消息范围±10
RANGE = 10
# SQLite 数据库文件
DB_FILE = "message_forward.db"
# 附加信息
addInfo = "\n\n♋[91转发|机器人](https://t.me/91_zf_bot)👉：@91_zf_bot\n♍[91转发|聊天👉：](https://t.me/91_zf_bot)@91_zf_group\n🔯[91转发|通知👉：](https://t.me/91_zf_channel)@91_zf_channel"
# 按钮
# buttons = [
#     [Button.url("91转发|聊天", "https://example.com"), Button.url("91转发|通知", "https://t.me/joinchat/XXXXXX")]
# ]

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

bot_client = TelegramClient(StringSession(BOT_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))
user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH, proxy=('socks5', '127.0.0.1', 10808))


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

    # 创建订单表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        package_name TEXT NOT NULL,
        amount REAL NOT NULL,
        quota_amount INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        payment_address TEXT NOT NULL,
        tx_hash TEXT,
        memo TEXT,
        last_checked TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
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


def reset_all_free_quotas():
    """重置所有用户的免费次数"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    current_date = datetime.now().strftime('%Y-%m-%d')

    # 更新所有用户的免费次数为5，并更新重置日期
    cursor.execute('''
    UPDATE user_forward_quota 
    SET free_quota = 5, last_reset_date = ?, updated_at = CURRENT_TIMESTAMP
    ''', (current_date,))

    affected_rows = cursor.rowcount
    conn.commit()
    conn.close()

    log.info(f"已重置 {affected_rows} 个用户的免费转发次数")
    return affected_rows


# 订单管理相关函数
def generate_order_id():
    """生成唯一的订单ID"""
    import uuid
    return f"ORD-{str(uuid.uuid4())[:8].upper()}"


async def check_trc20_transaction(order_id, wallet_address, expected_amount=None):
    """
    检查指定钱包地址是否收到了TRC20 USDT转账，通过查询订单ID或金额匹配

    :param order_id: 订单ID，用于检查交易备注
    :param wallet_address: 接收付款的钱包地址
    :param expected_amount: 预期收到的金额
    :return: 如果匹配到交易，返回交易哈希，否则返回None
    """
    if not TRONGRID_API_KEY:
        log.warning("未配置TRONGRID_API_KEY，无法自动检查交易")
        return None

    # 从订单获取详细信息
    order = get_order_by_id(order_id)
    if not order:
        log.error(f"找不到订单 {order_id}")
        return None

    user_id = order[1]
    expected_amount = order[3]  # 订单金额

    try:
        # 使用TronGrid API查询交易
        url = f"https://api.trongrid.io/v1/accounts/{wallet_address}/transactions/trc20"
        headers = {
            "Accept": "application/json",
            "TRON-PRO-API-KEY": TRONGRID_API_KEY
        }
        params = {
            "limit": 20,  # 限制最近的20条交易
            "contract_address": USDT_CONTRACT,  # USDT合约地址
            "only_confirmed": True
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            log.error(f"查询交易失败: {response.status_code} {response.text}")
            return None

        data = response.json()

        # 检查是否有符合条件的交易
        if "data" in data:
            transactions = data["data"]
            for tx in transactions:
                # 只检查USDT转入交易
                if tx["to"] == wallet_address and tx["token_info"]["address"] == USDT_CONTRACT:
                    # 获取交易金额（USDT有6位小数）
                    value = float(tx["value"]) / 10 ** 6

                    # 检查金额是否精确匹配
                    if abs(value - expected_amount) < 0.00001:  # 允许0.00001美元的误差，因为我们使用5位小数
                        # 检查交易备注是否包含订单号（可选匹配）
                        tx_hash = tx["transaction_id"]

                        # 尝试获取交易的备注信息，但不强制要求
                        memo = ""
                        try:
                            tx_detail_url = f"https://api.trongrid.io/v1/transactions/{tx_hash}"
                            tx_detail_response = requests.get(tx_detail_url, headers=headers)
                            if tx_detail_response.status_code == 200:
                                tx_detail = tx_detail_response.json()
                                if "data" in tx_detail and tx_detail["data"]:
                                    # 提取备注信息
                                    raw_data = tx_detail["data"][0]["raw_data"]
                                    if "data" in raw_data:
                                        memo = bytes.fromhex(raw_data["data"][2:]).decode('utf-8', errors='ignore')
                        except Exception as e:
                            log.error(f"获取交易备注失败: {e}")
                            # 备注获取失败不影响主要流程

                        # 更新订单的交易哈希和备注
                        update_order_tx_info(order_id, tx_hash, memo)

                        # 完成订单 - 金额精确匹配即可确认
                        success = complete_order(order_id, tx_hash)
                        if success:
                            log.info(f"自动确认订单 {order_id} 支付成功，交易哈希: {tx_hash}，金额: {value}$")
                            # 通知用户订单已完成
                            await notify_user_order_completed(order)

                            # 通知管理员订单已自动完成
                            if ADMIN_ID:
                                admin_msg = f"🤖 自动确认订单 🤖\n\n订单ID: {order_id}\n用户ID: {user_id}\n金额: {expected_amount}$\n交易哈希: {tx_hash}"
                                try:
                                    await bot_client.send_message(ADMIN_ID, admin_msg)
                                except Exception as e:
                                    log.error(f"通知管理员失败: {e}")

                        return tx_hash

        # 更新订单最后检查时间
        update_order_last_checked(order_id)
        return None

    except Exception as e:
        log.exception(f"检查交易失败: {e}")
        return None


def update_order_tx_info(order_id, tx_hash, memo=""):
    """更新订单的交易哈希和备注"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
        UPDATE orders 
        SET tx_hash = ?, memo = ?, updated_at = ? 
        WHERE order_id = ?
        ''', (tx_hash, memo, updated_at, order_id))

        conn.commit()
    except Exception as e:
        log.exception(f"更新订单交易信息失败: {e}")
    finally:
        conn.close()


def update_order_last_checked(order_id):
    """更新订单最后检查时间"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        last_checked = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
        UPDATE orders 
        SET last_checked = ?, updated_at = ? 
        WHERE order_id = ?
        ''', (last_checked, last_checked, order_id))

        conn.commit()
    except Exception as e:
        log.exception(f"更新订单最后检查时间失败: {e}")
    finally:
        conn.close()


async def notify_user_order_completed(order):
    """通知用户订单已完成"""
    # 解包订单信息
    # order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
    order_id = order[0]
    user_id = order[1]
    package_name = order[2]
    quota = order[4]

    try:
        notification = f"""🎉 您的订单已完成 🎉

🆔 订单号: {order_id}
📦 套餐: {package_name}
🔢 已增加次数: {quota}次

您可以通过 /user 查看当前可用次数。
"""
        await bot_client.send_message(int(user_id), notification)
    except Exception as e:
        log.error(f"通知用户订单完成失败: {e}")


def cancel_expired_order(order_id):
    """取消超时未支付的订单"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 获取订单信息以记录日志
        cursor.execute('SELECT user_id, package_name, amount FROM orders WHERE order_id = ? AND status = "pending"',
                       (order_id,))
        order = cursor.fetchone()

        if not order:
            # 订单不存在或已经不是pending状态
            return False

        user_id, package_name, amount = order

        # 更新订单状态为已取消
        cancelled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
        UPDATE orders 
        SET status = "cancelled", updated_at = ? 
        WHERE order_id = ?
        ''', (cancelled_at, order_id))

        conn.commit()
        log.info(f"订单 {order_id} 因超时未支付已自动取消，用户: {user_id}, 套餐: {package_name}, 金额: {amount}$")
        return True
    except Exception as e:
        log.exception(f"取消订单失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


async def schedule_transaction_checker():
    """定时任务：定期检查待处理订单的交易状态和超时情况"""
    # 支付超时时间（秒）
    payment_timeout = 20 * 60  # 20分钟

    while True:
        try:
            # 获取所有待处理的订单
            pending_orders = get_all_pending_orders()

            if pending_orders:
                log.info(f"开始检查 {len(pending_orders)} 个待处理订单")
                now = datetime.now()

                for order in pending_orders:
                    order_id = order[0]
                    payment_address = order[6]
                    created_at = datetime.strptime(order[10], '%Y-%m-%d %H:%M:%S')

                    # 检查订单是否超时
                    time_elapsed = (now - created_at).total_seconds()
                    if time_elapsed > payment_timeout:
                        # 订单已超时，取消订单
                        cancelled = cancel_expired_order(order_id)
                        if cancelled:
                            # 尝试通知用户订单已取消
                            try:
                                user_id = order[1]
                                package_name = order[2]
                                amount = order[3]

                                cancel_msg = f"""⏱️ 订单已超时取消 ⏱️

🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$

订单因超过20分钟未支付已自动取消。
如需继续购买，请重新选择套餐。"""

                                await bot_client.send_message(int(user_id), cancel_msg)
                            except Exception as e:
                                log.error(f"通知用户订单取消失败: {e}")
                        continue

                    # 检查交易
                    await check_trc20_transaction(order_id, payment_address)

                    # 每个订单检查后稍微延迟，避免API请求过于频繁
                    await asyncio.sleep(2)

            # 等待下一次检查
            await asyncio.sleep(TRANSACTION_CHECK_INTERVAL)

        except Exception as e:
            log.exception(f"交易检查任务异常: {e}")
            await asyncio.sleep(60)  # 出错后等待1分钟再继续


def get_all_pending_orders():
    """获取所有待处理的订单"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM orders WHERE status = "pending" ORDER BY created_at ASC')
    orders = cursor.fetchall()

    conn.close()
    return orders


def create_new_order(user_id, package_name, amount, quota_amount):
    """创建新订单，并生成独特的金额"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    order_id = generate_order_id()
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 为订单生成独特金额：基础金额 + 0.00001-0.00099的随机小数（更小的随机值）
    unique_cents = random.randint(1, 99) / 100000
    unique_amount = round(amount + unique_cents, 5)  # 保留5位小数

    try:
        cursor.execute('''
        INSERT INTO orders 
        (order_id, user_id, package_name, amount, quota_amount, payment_address, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, str(user_id), package_name, unique_amount, quota_amount, USDT_WALLET, created_at, created_at))

        conn.commit()
        log.info(f"为用户 {user_id} 创建了新订单 {order_id}，金额: {unique_amount}$")
        return order_id, unique_amount
    except Exception as e:
        log.exception(f"创建订单失败: {e}")
        return None, None
    finally:
        conn.close()


def get_order_by_id(order_id):
    """通过订单ID获取订单信息"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
    order = cursor.fetchone()

    conn.close()
    return order


def get_user_pending_orders(user_id):
    """获取用户的未完成订单"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM orders WHERE user_id = ? AND status = "pending" ORDER BY created_at DESC',
                   (str(user_id),))
    orders = cursor.fetchall()

    conn.close()
    return orders


def complete_order(order_id, tx_hash=None):
    """完成订单并增加用户次数"""
    conn = sqlite3.connect(DB_FILE)
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

        # 增加用户次数
        add_paid_quota(user_id, quota_amount)

        conn.commit()
        log.info(f"订单 {order_id} 已完成，为用户 {user_id} 增加了 {quota_amount} 次付费转发次数")
        return True
    except Exception as e:
        log.exception(f"完成订单失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


async def schedule_quota_reset():
    """定时任务：每天0点重置所有用户的免费次数"""
    while True:
        # 计算距离下一个0点的秒数
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        # 等待到0点
        log.info(f"下一次免费次数重置将在 {seconds_until_midnight:.2f} 秒后进行")
        await asyncio.sleep(seconds_until_midnight)

        # 重置所有用户的免费次数
        affected_users = reset_all_free_quotas()
        log.info(f"已在 {datetime.now()} 重置了 {affected_users} 个用户的免费转发次数")


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
async def replace_message(message: Message):
    if message.fwd_from:
        peer_id = utils.get_peer_id(message.fwd_from.from_id)
        message_id = message.fwd_from.channel_post
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        req_params = {"chat_id": peer_id}
        result = requests.get(url, params=req_params)
        peer_type = "channel"
        channel_username = None
        if result and result.json().get("ok"):
            channel = result.json().get("result")
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
    # await event.reply("该消息已经转发过，正在重新发送...")
    message = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_message_id)
    if message.media:
        await bot_client.send_file(event.chat_id, message.media, caption=message.text + addInfo,
                                   reply_to=event.message.id)
    else:
        await bot_client.send_message(event.chat_id, message.text + addInfo, reply_to=event.message.id)

    # 处理转发次数并发送提示消息
    await process_forward_quota(event)


async def group_forward_message(event, grouped_messages):
    # await event.reply("该消息组已经转发过，正在重新发送...")
    try:
        target_ids = [target_id for _, target_id in grouped_messages]
        messages = await bot_client.get_messages(PeerChannel(PRIVATE_CHAT_ID), ids=target_ids)
        media_files = [msg.media for msg in messages if msg.media]
        caption = messages[0].text
        # 按钮信息追加到原 caption 后面
        await bot_client.send_file(event.chat_id, media_files, caption=caption + addInfo, reply_to=event.message.id)
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
            captions = media_group[0].text
            # 构造相册的文件对象
            album_files = await asyncio.gather(*[prepare_album_file(msg) for msg in media_group if msg.media])
            await bot_client.send_file(event.chat_id, file=album_files, caption=captions + addInfo,
                                       reply_to=event.message.id)
            sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file=album_files,
                                                       caption=captions)
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
        await event.reply("服务器内部错误，请联系管理员")


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
                await bot_client.send_file(event.chat_id, file_path, caption=message.text + addInfo,
                                           reply_to=event.message.id,
                                           attributes=message.media.document.attributes, thumb=thumb_path,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          thumb=thumb_path,
                                                          force_document=force_document)
                os.remove(thumb_path)  # 发送后删除缩略图
            elif isinstance(message.media, MessageMediaDocument) and message.media.document.mime_type == 'audio/mpeg':
                await bot_client.send_file(event.chat_id, file_path, caption=message.text + addInfo,
                                           reply_to=event.message.id,
                                           attributes=message.media.document.attributes,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text,
                                                          attributes=message.media.document.attributes,
                                                          force_document=force_document)
            else:
                await bot_client.send_file(event.chat_id, file_path, caption=message.text + addInfo,
                                           reply_to=event.message.id,
                                           force_document=force_document)
                sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), file_path,
                                                          caption=message.text, force_document=force_document)
            os.remove(file_path)  # 发送后删除文件
        else:
            await bot_client.send_message(event.chat_id, message.text + addInfo, reply_to=event.message.id)
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
        await event.reply("服务器内部错误，请联系管理员")


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
            await bot_client.send_file(event.chat_id, media_files, caption=caption + addInfo, reply_to=event.message.id)
            sent_messages = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), media_files,
                                                       caption=caption)
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
        await event.reply("服务器内部错误，请联系管理员")


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
            await bot_client.send_file(event.chat_id, message.media, caption=message.text + addInfo,
                                       reply_to=event.message.id)
            sent_message = await bot_client.send_file(PeerChannel(PRIVATE_CHAT_ID), message.media,
                                                      caption=message.text)
        else:
            await bot_client.send_message(event.chat_id, message.text + addInfo, reply_to=event.message.id)
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
        await event.reply("服务器内部错误，请联系管理员")


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
        result = requests.get(url, params=req_params)
        if result and result.json().get("ok"):
            channel = result.json().get("result")
            has_protected_content = channel.get("has_protected_content", False)
            peer_type = channel.get("type", "channel")
            if not has_protected_content:
                await event.reply("此消息允许转发！无需使用本机器人")
                return
        else:
            await event.reply("私人频道和私人群组，暂时不支持")
            return
    else:
        peer = chat_id
        req_params = {"chat_id": f"@{chat_id}"}
        result = requests.get(url, params=req_params)
        if result and result.json().get("ok"):
            channel = result.json().get("result")
            has_protected_content = channel.get("has_protected_content", False)
            peer_type = channel.get("type", "channel")
            if not has_protected_content:
                await event.reply("此消息允许转发！无需使用本机器人")
                return
        else:
            await event.reply("服务器内部错误，请联系管理员")
            return

    if peer_type == "channel":  # 频道消息处理
        try:
            # 获取指定聊天中的消息
            message = await bot_client.get_messages(peer, ids=message_id)
        except Exception as e:
            log.exception(f"Error: {e}")
            await event.reply("服务器内部错误，请联系管理员")
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
            await event.reply("服务器内部错误，请联系管理员")
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
            result = await replace_message(message)
            if result:  # 有结果替换为频道消息
                peer, message_id = result
                message = await bot_client.get_messages(peer, ids=message_id)
                # await event.reply("替换频道消息，免下载转发")
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


# 按钮回调处理函数
async def callback_handler(event):
    """处理按钮点击事件"""
    # 获取回调数据
    data = event.data
    user_id = event.sender_id

    # 套餐配置
    packages = {
        b"buy_basic": {"name": "基础包", "price": 1, "quota": 25},
        b"buy_standard": {"name": "标准包", "price": 5, "quota": 150},
        b"buy_premium": {"name": "高级包", "price": 10, "quota": 400}
    }

    # 如果是购买套餐
    if data in packages:
        package = packages[data]
        # 创建新订单
        order_id, unique_amount = create_new_order(user_id, package["name"], package["price"], package["quota"])

        if order_id:
            # 生成付款信息
            payment_text = f"""🛒 您已选择: {package['name']}
💰 价格: {unique_amount}$  (请务必转账此精确到账金额)
🔢 可获得次数: {package['quota']}次

💳 请使用USDT(TRC20)支付至以下地址:
`{USDT_WALLET}`

📝 订单号: `{order_id}`

⚠️ 重要：请务必转账 {unique_amount}$ 的精确(小数点后要一致)到账金额，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""
            # 添加查看订单状态的按钮
            buttons = [
                [Button.inline("查询订单状态", data=f"check_{order_id}".encode())]
            ]
            try:
                await event.edit(payment_text, buttons=buttons, parse_mode='markdown')
            except Exception as e:
                log.error(f"编辑消息失败: {e}")
                await event.answer("消息更新失败，请重试", alert=True)

            # 如果设置了管理员ID，发送订单通知给管理员
            if ADMIN_ID:
                admin_notify = f"📢 新订单通知 📢\n\n用户ID: {user_id}\n套餐: {package['name']}\n金额: {package['price']}$\n订单ID: {order_id}"
                try:
                    await bot_client.send_message(ADMIN_ID, admin_notify)
                except Exception as e:
                    log.error(f"发送管理员通知失败: {e}")
        else:
            try:
                await event.edit("❌ 订单创建失败，请稍后重试或联系管理员。")
            except Exception as e:
                log.error(f"编辑消息失败: {e}")
                await event.answer("消息更新失败，请重试", alert=True)

    # 查询订单状态
    elif data.startswith(b"check_"):
        order_id = data[6:].decode('utf-8')
        order = get_order_by_id(order_id)

        if order:
            # 假设order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
            status = order[5]
            package_name = order[2]
            amount = order[3]
            quota = order[4]
            created_at = order[10]

            status_text = {
                "pending": "⏳ 等待付款",
                "completed": "✅ 已完成",
                "cancelled": "❌ 已取消"
            }.get(status, status)

            order_info = f"""📋 订单详情 📋
            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text}

"""
            if status == "pending":
                order_info += f"""💳 付款地址: `{USDT_WALLET}`

⚠️ 重要：请务必转账 {amount}$ 的精确金额，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""

                buttons = [[Button.inline("刷新状态", data=f"check_{order_id}".encode())]]
                try:
                    # 先尝试显示"正在刷新"状态
                    temp_info = f"""📋 订单详情 - 正在刷新... 📋
                    
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} (刷新中...)

"""
                    if status == "pending":
                        temp_info += f"""💳 付款地址: `{USDT_WALLET}`
⚠️ 重要：请务必转账 {amount}$ 的精确到账金额，系统将通过(小数点后面)金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""

                    # 先显示刷新中状态
                    await event.edit(temp_info, buttons=buttons, parse_mode='markdown')

                    # 等待半秒，让用户能看到刷新效果
                    await asyncio.sleep(0.5)

                    # 然后显示最终结果
                    await event.edit(order_info, buttons=buttons, parse_mode='markdown')

                except Exception as e:
                    error_str = str(e)
                    if "Content of the message was not modified" in error_str:
                        # 消息内容没变化，尝试显示临时消息
                        log.info(f"订单状态没有变化，尝试显示临时刷新效果")
                        try:
                            # 添加时间戳使消息内容强制变化
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            temp_msg = f"""📋 订单详情 - 刷新于 {timestamp} 📋
                            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} ✓

✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"""

                            # 先显示带时间戳的临时信息
                            await event.edit(temp_msg, parse_mode='markdown')

                            # 等待半秒，让用户能看到刷新效果
                            await asyncio.sleep(0.5)

                            # 然后恢复原始信息
                            await event.edit(order_info, parse_mode='markdown')
                        except Exception as inner_e:
                            log.error(f"显示临时刷新消息失败: {inner_e}")
                    else:
                        log.error(f"编辑消息失败: {error_str}")
            elif status == "completed":
                order_info += "✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"
                try:
                    await event.edit(order_info, parse_mode='markdown')
                except Exception as e:
                    error_str = str(e)
                    if "Content of the message was not modified" in error_str:
                        # 消息内容没变化，尝试显示临时消息
                        log.info(f"订单状态没有变化，尝试显示临时刷新效果")
                        try:
                            # 添加时间戳使消息内容强制变化
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            temp_msg = f"""📋 订单详情 - 刷新于 {timestamp} 📋
                            
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text} ✓

✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"""

                            # 先显示带时间戳的临时信息
                            await event.edit(temp_msg, parse_mode='markdown')

                            # 等待半秒，让用户能看到刷新效果
                            await asyncio.sleep(0.5)

                            # 然后恢复原始信息
                            await event.edit(order_info, parse_mode='markdown')
                        except Exception as inner_e:
                            log.error(f"显示临时刷新消息失败: {inner_e}")
                    else:
                        log.error(f"编辑消息失败: {error_str}")
            elif status == "cancelled":
                order_info += "⏱️ 此订单已因超时未支付而自动取消。如需继续购买，请重新选择套餐。"
                try:
                    await event.edit(order_info, parse_mode='markdown')
                except Exception as e:
                    log.error(f"编辑消息失败: {e}")
        else:
            try:
                await event.edit("❌ 找不到此订单，请检查订单号是否正确。")
            except Exception as e:
                log.error(f"编辑消息失败: {e}")

    # 其他回调数据
    else:
        await event.answer("未知操作", alert=True)


# 命令处理函数
async def cmd_start(event):
    """处理 /start 命令，显示使用方法说明"""
    usage_text = """🤖 使用方法 🤖

1️⃣ 发送需要转发的消息链接
2️⃣ 机器人将帮您保存该消息
3️⃣ 每天免费5次，次日0点重置

❓ 如何获取链接：
- 在消息上点击"分享"
- 选择"复制链接"
- 将链接发送给机器人

⚠️范围：支持频道、群组、评论区
⚠️注意：私人频道暂不支持(因为需要授权登录，很多人担心账号安全问题)
"""
    await event.reply(usage_text)


async def cmd_user(event):
    """处理 /user 命令，显示用户中心信息"""
    user_id = event.sender_id
    free_quota, paid_quota, last_reset_date = get_user_quota(user_id)
    total_quota = free_quota + paid_quota

    # 获取用户名
    sender = event.sender
    username = sender.username if sender and sender.username else f"用户{user_id}"

    user_info = f"""👤 用户中心 - @{username}

📊 转发次数统计：
  ├ 今日剩余：{total_quota} 次
  ├ 免费次数：{free_quota} 次
  └ 付费次数：{paid_quota} 次

🔄 下次重置时间：次日0点
📅 上次重置日期：{last_reset_date}

💰 购买更多次数请点击 /buy
"""
    await event.reply(user_info)


async def cmd_buy(event):
    """处理 /buy 命令，显示充值信息"""
    buy_text = """💰 购买转发次数 💰

请选择您想购买的套餐："""

    # 定义套餐按钮
    buttons = [
        [Button.inline("基础包: 25次/1$", data=b"buy_basic")],
        [Button.inline("标准包: 150次/5$", data=b"buy_standard")],
        [Button.inline("高级包: 400次/10$", data=b"buy_premium")]
    ]

    await event.respond(buy_text, buttons=buttons)


async def cmd_check(event):
    """处理 /check 命令，查询订单状态"""
    text = event.text.split()
    if len(text) < 2:
        await event.reply("请提供订单号，例如：`/check ORD-12345678`", parse_mode='markdown')
        return

    order_id = text[1]
    order = get_order_by_id(order_id)

    if order:
        # 假设order是tuple(order_id, user_id, package_name, amount, quota_amount, status, payment_address, tx_hash, memo, last_checked, created_at, updated_at, completed_at)
        status = order[5]
        package_name = order[2]
        amount = order[3]
        quota = order[4]
        created_at = order[7]

        status_text = {
            "pending": "⏳ 等待付款",
            "completed": "✅ 已完成",
            "cancelled": "❌ 已取消"
        }.get(status, status)

        order_info = f"""📋 订单详情 📋
        
🆔 订单号: {order_id}
📦 套餐: {package_name}
💰 金额: {amount}$
🔢 次数: {quota}次
📅 创建时间: {created_at}
🔄 状态: {status_text}

"""
        if status == "pending":
            order_info += f"""💳 付款地址: `{USDT_WALLET}`

⚠️ 重要：请务必转账 {amount}$ 的精确金额，系统将通过金额自动匹配您的订单
✅ 付款成功后系统将自动确认并增加您的次数"""

            buttons = [[Button.inline("刷新状态", data=f"check_{order_id}".encode())]]
            await event.reply(order_info, buttons=buttons, parse_mode='markdown')
        elif status == "completed":
            order_info += "✅ 您的次数已增加，可以通过 /user 查看当前可用次数。"
            await event.reply(order_info, parse_mode='markdown')
        elif status == "cancelled":
            order_info += "⏱️ 此订单已因超时未支付而自动取消。如需继续购买，请重新选择套餐。"
            await event.reply(order_info, parse_mode='markdown')
    else:
        await event.reply("❌ 找不到此订单，请检查订单号是否正确。")


# 6. 主函数定义
async def main():
    # 初始化数据库
    init_db()
    # 客户端初始化
    log.info("连接机器人。")
    await bot_client.connect()
    await user_client.connect()
    try:
        # 设置机器人命令菜单
        commands = [
            BotCommand(command="start", description="使用方法"),
            BotCommand(command="user", description="用户中心"),
            BotCommand(command="buy", description="购买次数"),
            BotCommand(command="check", description="查询订单")
        ]
        await bot_client(SetBotCommandsRequest(
            scope=BotCommandScopeDefault(),
            lang_code="",
            commands=commands
        ))

    except Exception as e:
        log.exception("启动客户端失败")
        log.exception(f"Error: {e}")
        exit(1)

    # 注册消息处理器
    bot_client.add_event_handler(on_new_link, events.NewMessage(func=is_authorized))

    # 注册命令处理器
    bot_client.add_event_handler(cmd_start, events.NewMessage(pattern='/start', func=is_authorized))
    bot_client.add_event_handler(cmd_user, events.NewMessage(pattern='/user', func=is_authorized))
    bot_client.add_event_handler(cmd_buy, events.NewMessage(pattern='/buy', func=is_authorized))
    bot_client.add_event_handler(cmd_check, events.NewMessage(pattern='/check', func=is_authorized))

    # 注册回调处理器
    bot_client.add_event_handler(callback_handler, events.CallbackQuery())

    # 获取机器人的用户信息并开始运行客户端
    ubot_self = await bot_client.get_me()
    log.info("客户端已启动为 %d。", ubot_self.id)
    # 获取 user_client 的用户信息并启动
    u_user = await user_client.get_me()
    log.info("USER_SESSION 已启动为 %d。", u_user.id)

    # 启动定时重置任务
    asyncio.create_task(schedule_quota_reset())
    log.info("已启动每日0点自动重置免费转发次数的定时任务")

    # 启动定时交易检查任务
    asyncio.create_task(schedule_transaction_checker())
    log.info(f"已启动自动检查交易状态的定时任务，间隔 {TRANSACTION_CHECK_INTERVAL} 秒")

    # 启动并等待两个客户端断开连接
    await bot_client.run_until_disconnected()  # 运行 BOT_SESSION
    await user_client.run_until_disconnected()  # 运行 USER_SESSION


# 7. 程序入口
if __name__ == '__main__':
    asyncio.run(main())
