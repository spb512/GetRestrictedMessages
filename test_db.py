"""
测试数据库模块的脚本
"""

import logging

from db import (
    init_db, get_user_quota, decrease_user_quota, add_paid_quota,
    create_new_order, get_order_by_id,
    complete_order, get_user_invite_code, process_invite, get_invite_stats
)

# 设置日志记录
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
log = logging.getLogger("TestDB")


def test_user_quota():
    """测试用户配额相关函数"""
    log.info("测试用户配额功能...")

    user_id = 123456789

    # 获取用户配额（应该创建新用户）
    free_quota, paid_quota, reset_date = get_user_quota(user_id)
    log.info(f"用户初始配额: 免费={free_quota}, 付费={paid_quota}, 重置日期={reset_date}")

    # 减少配额
    decreased = decrease_user_quota(user_id)
    log.info(f"减少配额结果: {decreased}")

    # 再次获取配额
    free_quota, paid_quota, reset_date = get_user_quota(user_id)
    log.info(f"减少后配额: 免费={free_quota}, 付费={paid_quota}, 重置日期={reset_date}")

    # 添加付费配额
    new_paid_quota = add_paid_quota(user_id, 10)
    log.info(f"添加10次付费配额后: {new_paid_quota}")

    # 最终配额
    free_quota, paid_quota, reset_date = get_user_quota(user_id)
    log.info(f"最终配额: 免费={free_quota}, 付费={paid_quota}, 重置日期={reset_date}")


def test_orders():
    """测试订单相关函数"""
    log.info("测试订单功能...")

    user_id = 123456789

    # 创建新订单
    order_id, amount = create_new_order(user_id, "测试套餐", 5.0, 30)
    log.info(f"创建订单: ID={order_id}, 金额={amount}")

    # 获取订单
    order = get_order_by_id(order_id)
    log.info(f"获取订单: {order}")

    # 完成订单
    completed = complete_order(order_id, "测试交易哈希")
    log.info(f"完成订单: {completed}")

    # 再次获取订单
    order = get_order_by_id(order_id)
    log.info(f"完成后订单: {order}")

    # 检查用户配额
    free_quota, paid_quota, reset_date = get_user_quota(user_id)
    log.info(f"订单完成后用户配额: 免费={free_quota}, 付费={paid_quota}")


def test_invite():
    """测试邀请码相关函数"""
    log.info("测试邀请功能...")

    inviter_id = 123456789
    invitee_id = 987654321

    # 获取邀请码
    invite_code = get_user_invite_code(inviter_id)
    log.info(f"用户邀请码: {invite_code}")

    # 处理邀请
    success, message = process_invite(invite_code, invitee_id)
    log.info(f"处理邀请: 成功={success}, 消息={message}")

    # 获取邀请统计
    invite_count, reward_count = get_invite_stats(inviter_id)
    log.info(f"邀请统计: 邀请人数={invite_count}, 奖励次数={reward_count}")

    # 检查邀请人配额
    free_quota, paid_quota, reset_date = get_user_quota(inviter_id)
    log.info(f"邀请后用户配额: 免费={free_quota}, 付费={paid_quota}")


def main():
    """主测试函数"""
    log.info("开始测试数据库模块...")

    # 初始化数据库
    init_db()
    log.info("数据库已初始化")

    # 测试用户配额
    test_user_quota()

    # 测试订单
    test_orders()

    # 测试邀请
    test_invite()

    log.info("测试完成!")


if __name__ == "__main__":
    main()
