"""
系统监控模块 - 负责监控系统资源使用情况
"""

import logging
import time

import psutil

# 初始化日志记录器
log = logging.getLogger("SystemMonitor")


def monitor_system_resources(cpu_threshold, memory_threshold, disk_io_threshold,
                             monitor_interval, system_overloaded_var):
    """
    监控系统资源使用情况，并在超过阈值时设置系统过载标志
    
    :param cpu_threshold: CPU使用率阈值(百分比)
    :param memory_threshold: 内存使用率阈值(百分比)
    :param disk_io_threshold: 磁盘I/O使用率阈值(百分比)
    :param monitor_interval: 监控间隔时间(秒)
    :param system_overloaded_var: 系统过载标志变量，multiprocessing.Value类型
    """
    while True:
        try:
            # 获取CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)

            # 获取内存使用率
            memory_percent = psutil.virtual_memory().percent

            # 获取磁盘I/O使用率
            disk_io = psutil.disk_io_counters()
            time.sleep(0.1)
            disk_io_new = psutil.disk_io_counters()
            disk_io_percent = 0
            if hasattr(disk_io, 'read_bytes') and hasattr(disk_io_new, 'read_bytes'):
                read_diff = disk_io_new.read_bytes - disk_io.read_bytes
                write_diff = disk_io_new.write_bytes - disk_io.write_bytes
                # 简单估算I/O使用率，实际应根据系统磁盘性能调整基准值
                disk_io_percent = min(100.0, (read_diff + write_diff) / (10 * 1024 * 1024) * 100)

            # 记录资源使用情况
            # log.info(f"系统资源监控 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")

            # 检查是否超过阈值
            current_overloaded = bool(system_overloaded_var.value)
            is_overloaded = (cpu_percent > cpu_threshold or
                             memory_percent > memory_threshold or
                             disk_io_percent > disk_io_threshold)

            # 只在状态变化时记录日志和更新值
            if is_overloaded != current_overloaded:
                # 获取锁并更新值
                with system_overloaded_var.get_lock():
                    system_overloaded_var.value = is_overloaded

                if is_overloaded:
                    log.warning(
                        f"系统负载过高 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")
                else:
                    log.info(
                        f"系统负载恢复正常 - CPU: {cpu_percent}%, 内存: {memory_percent}%, 磁盘I/O: {disk_io_percent}%")

            # 等待下一次监控
            time.sleep(monitor_interval)
        except Exception as e:
            log.exception(f"系统监控异常: {e}")
            time.sleep(monitor_interval)


def start_system_monitor(cpu_threshold, memory_threshold, disk_io_threshold,
                         monitor_interval, system_overloaded_var):
    """
    启动系统资源监控线程
    
    :param cpu_threshold: CPU使用率阈值(百分比)
    :param memory_threshold: 内存使用率阈值(百分比)
    :param disk_io_threshold: 磁盘I/O使用率阈值(百分比)
    :param monitor_interval: 监控间隔时间(秒)
    :param system_overloaded_var: 系统过载标志变量，multiprocessing.Value类型
    :return: 监控线程
    """
    import threading

    # 创建并启动监控线程
    monitor_thread = threading.Thread(
        target=monitor_system_resources,
        args=(cpu_threshold, memory_threshold, disk_io_threshold,
              monitor_interval, system_overloaded_var),
        daemon=True
    )
    monitor_thread.start()

    log.info("已启动系统资源监控线程")
    return monitor_thread
