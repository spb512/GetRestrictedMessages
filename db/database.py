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


def add_indexes():
    """添加数据库索引以优化查询性能"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        log.info("开始添加数据库索引...")
        
        # message_relations 表索引
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_relations_source 
        ON message_relations(source_chat_id, source_message_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_relations_target 
        ON message_relations(target_chat_id, target_message_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_relations_grouped 
        ON message_relations(grouped_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_relations_created 
        ON message_relations(created_at)
        ''')
        
        # user_forward_quota 表索引
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_quota_last_reset 
        ON user_forward_quota(last_reset_date)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_quota_updated 
        ON user_forward_quota(updated_at)
        ''')
        
        # orders 表索引
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_orders_user 
        ON orders(user_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_orders_status 
        ON orders(status)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_orders_created 
        ON orders(created_at)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_orders_completed 
        ON orders(completed_at)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_orders_tx_hash 
        ON orders(tx_hash)
        ''')
        
        # invite_relations 表索引
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invite_inviter 
        ON invite_relations(inviter_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invite_code 
        ON invite_relations(invite_code)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_invite_created 
        ON invite_relations(created_at)
        ''')
        
        conn.commit()
        log.info("数据库索引添加完成")


def analyze_db():
    """运行ANALYZE命令更新数据库统计信息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("ANALYZE")
        conn.commit()
        log.info("数据库统计信息已更新")


def analyze_index_usage():
    """分析索引使用情况"""
    # 首先运行ANALYZE更新统计信息
    analyze_db()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 获取所有索引
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = cursor.fetchall()
        
        log.info("索引使用情况分析：")
        
        # 检查sqlite_stat1表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
        if not cursor.fetchone():
            log.warning("没有索引使用统计信息。请先执行查询操作，然后再运行analyze_db()函数更新统计信息。")
            return
        
        for index in indexes:
            index_name = index[0]
            # 获取索引使用统计
            cursor.execute(f"SELECT * FROM sqlite_stat1 WHERE idx='{index_name}'")
            stats = cursor.fetchone()
            
            if stats:
                table_name = stats[0]
                idx_name = stats[1]
                stat_info = stats[2]
                log.info(f"表 {table_name} 的索引 {idx_name}: {stat_info}")
            else:
                log.warning(f"索引 {index_name} 没有使用统计信息")


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
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_relations (
            inviter_id TEXT NOT NULL,
            invitee_id TEXT,
            invite_code TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (invitee_id)
        )
        ''')

        conn.commit()
    log.info("数据库表结构初始化完成")
    
    # 添加索引
    add_indexes()
