"""
全局配置文件
"""

import logging

from decouple import config

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("Config")
# 设置Telethon内部日志级别，减少日志输出
logging.getLogger('telethon').setLevel(logging.WARNING)

# 从环境变量中获取配置
API_ID = config("API_ID", default=None, cast=int)
API_HASH = config("API_HASH", default=None)
BOT_SESSION = config("BOT_SESSION", default=None)
USER_SESSION = config("USER_SESSION", default=None)
BOT_TOKEN = config("BOT_TOKEN", default=None)
PRIVATE_CHAT_ID = config("PRIVATE_CHAT_ID", default=None, cast=int)
AUTHS = config("AUTHS", default="")

# 代理设置
USE_PROXY = config("USE_PROXY", default=False, cast=bool)
PROXY_TYPE = config("PROXY_TYPE", default="socks5")
PROXY_HOST = config("PROXY_HOST", default="127.0.0.1")
PROXY_PORT = config("PROXY_PORT", default=10808, cast=int)

# USDT(TRC20)钱包地址 - 用于接收付款
USDT_WALLET = config("USDT_WALLET", default="TM9tn28zug456sMkd5AZp9cDCRMFxrH7EG")
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

# 过载条件阈值
SYSTEM_OVERLOADED = False
CPU_THRESHOLD = 80  # CPU使用率阈值（百分比）
MEMORY_THRESHOLD = 80  # 内存使用率阈值（百分比）
DISK_IO_THRESHOLD = 80  # 磁盘I/O使用率阈值（百分比）
MONITOR_INTERVAL = 5  # 监控间隔（秒）

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


# 获取代理配置
def get_proxy(proxy_format="tuple"):
    """
    返回代理设置，根据format参数返回不同格式
    
    :param format: 返回格式，"tuple"返回(type,host,port)元组，"url"返回"type://host:port"字符串
    :return: 根据格式返回代理设置，如果USE_PROXY为False则返回None
    """
    if not USE_PROXY:
        return None
        
    if proxy_format == "url":
        return f"{PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}"
    else:  # 默认返回tuple格式
        return PROXY_TYPE, PROXY_HOST, PROXY_PORT


# 验证用户是否有权使用机器人
def is_authorized(event):
    """检查用户是否被授权使用机器人"""
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
