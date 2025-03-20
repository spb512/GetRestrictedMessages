#!/usr/bin/env python
"""
数据库索引使用情况分析工具
"""

import logging

from db.database import analyze_index_usage

# 设置日志格式
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
logger = logging.getLogger("IndexAnalyzer")


def main():
    """主函数"""
    logger.info("开始分析数据库索引使用情况...")

    # 运行索引使用分析
    analyze_index_usage()

    logger.info("索引分析完成。")
    logger.info("提示: 如果某些索引没有使用统计信息，可能是因为它们尚未被查询操作使用。")
    logger.info("建议在系统运行一段时间后再次运行此分析工具，以获取更准确的结果。")


if __name__ == "__main__":
    main()
