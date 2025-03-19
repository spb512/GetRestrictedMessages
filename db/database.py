import logging
import sqlite3
from contextlib import contextmanager

# 全局变量定义
DB_FILE = "message_forward.db"

# 初始化日志记录器
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
log = logging.getLogger("DB")


@contextmanager
def get_db_connection():
    """提供SQLite数据库连接的上下文管理器"""
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """初始化数据库，创建所需的表结构"""
    with get_db_connection() as conn:
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

        # 创建邀请关系表
        cursor.execute('DROP TABLE IF EXISTS invite_relations')
        cursor.execute('''
        CREATE TABLE invite_relations (
            inviter_id TEXT NOT NULL,
            invitee_id TEXT,
            invite_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (invitee_id)
        )
        ''')

        conn.commit()
    log.info("数据库初始化完成")
