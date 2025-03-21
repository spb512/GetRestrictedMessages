# Telegram消息转发机器人

这是一个基于Telethon库开发的Telegram消息转发机器人，用于自动化管理和转发Telegram消息。

## 项目功能

- **消息转发**：自动转发消息至指定目标
- **用户管理**：支持用户授权和权限控制
- **配额系统**：管理用户转发配额和使用限制
- **邀请系统**：支持邀请码功能扩展用户
- **支付集成**：支持USDT交易检测
- **系统监控**：实时监控CPU、内存和磁盘IO使用情况

## 技术栈

- Python 3.x
- Telethon (Telegram客户端库)
- SQLite数据库
- 异步编程 (asyncio)
- 代理支持 (SOCKS5)

## 安装步骤

1. 克隆代码仓库：
```bash
git clone https://github.com/spb512/91_zf
```

2. 创建并激活虚拟环境：
```bash
apt install python3.12-venv
python3 -m venv /root/91_zf/venv
source /root/91_zf/venv/bin/activate
```

3. 安装依赖包：
```bash
pip install -r requirements.txt
#退出虚拟环境
deactivate
```

4. 配置环境变量：
创建一个`.env`文件，填入以下配置：
```
cd 91_zf
cp .env.sample .env

API_ID=你的API_ID
API_HASH=你的API_HASH
BOT_TOKEN=你的BOT_TOKEN
BOT_SESSION=你的BOT_SESSION
USER_SESSION=你的USER_SESSION
PRIVATE_CHAT_ID=你的私聊ID
AUTHS=授权用户ID列表

# 代理设置（可选）
USE_PROXY=False
PROXY_TYPE=socks5
PROXY_HOST=127.0.0.1
PROXY_PORT=10808

# 系统监控阈值
CPU_THRESHOLD=80
MEMORY_THRESHOLD=80
DISK_IO_THRESHOLD=80

# USDT交易相关（可选）
TRONGRID_API_KEY=你的TRONGRID_API_KEY
USDT_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
```

5. 生成session文件（可选）:
```bash
python sessiongen.py
```

## 使用方法

1. 启动机器人：
```bash
/root/91_zf/venv/bin/python /root/91_zf/main.py

cat > /etc/systemd/system/91_zf.service << EOF
[Unit]
Description=91_zf
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/91_zf
ExecStart=/root/91_zf/venv/bin/python /root/91_zf/main.py
StandardOutput=inherit
StandardError=inherit
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable 91_zf
systemctl start 91_zf
```

2. 机器人命令：
   - `/start` - 开始使用机器人
   - `/user` - 查看用户信息
   - `/buy` - 购买转发配额
   - `/check` - 检查支付状态
   - `/invite` - 获取邀请链接

## 项目结构

- `main.py` - 主程序入口
- `config.py` - 全局配置文件
- `sessiongen.py` - 会话生成工具
- `db/` - 数据库相关模块
- `handlers/` - 命令和事件处理器
- `services/` - 后台服务和任务

## 注意事项

- 使用前请确保已获取Telegram API凭证
- 请遵循Telegram API使用条款和政策
- 系统监控功能会在资源占用过高时自动限制处理 