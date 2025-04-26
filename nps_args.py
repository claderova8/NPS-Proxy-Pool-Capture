# -*- coding: utf-8 -*-
# 参数解析模块 - 负责定义、解析命令行参数以及加载目标和密码文件。

import argparse # 导入 argparse 库，用于命令行参数解析
import os       # 导入 os 模块，用于文件路径操作
import sys      # 导入 sys 模块，用于退出程序

# 导入常量模块 (已修改为绝对导入)
# Import constants directly here for defaults
from nps_constants import (
    DEFAULT_PASSWORDS, PRIORITY_PASSWORDS, CLIENT_DATA_PATH,
    TUNNEL_DATA_PATH, DEFAULT_AGGREGATED_TUNNELS_FILE,
    DEFAULT_OUTPUT_FILE, TUNNEL_PAGE_LIMIT
)


def parse_args():
    """
    解析命令行参数。

    Returns:
        argparse.Namespace: 返回一个命名空间对象，其中包含解析后的参数及其值。
    """
    # 创建 ArgumentParser 对象，设置程序描述
    parser = argparse.ArgumentParser(
        description="NPS Proxy 弱口令检测与客户端/隧道数据获取工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show default values in help
    )

    # --- Target Specification ---
    target_group = parser.add_mutually_exclusive_group(required=True) # required=True 表示此组中必须至少指定一个参数
    target_group.add_argument(
        "-l", "--target-list",
        help="包含目标主机列表的文件路径，每行一个 host:port (无需协议头)"
    )
    target_group.add_argument(
        "-H", "--target", dest='single_target',
        help="直接指定单个目标主机地址 (host:port)，与 -l 互斥"
    )

    # --- Credentials ---
    parser.add_argument(
        "-u", "--username", default="admin",
        help="指定 NPS 登录用户名"
    )
    parser.add_argument(
        "-p", "--password-list",
        help="包含自定义密码的文件路径，每行一个密码；不指定则使用内置弱口令列表"
    )
    parser.add_argument(
        "--priority-passwords", nargs='+', default=list(PRIORITY_PASSWORDS), # Allow multiple, default from constant
        help="优先尝试的密码列表 (空格分隔)"
    )

    # --- Connection & Performance ---
    parser.add_argument(
        "-t", "--threads", type=int, default=20,
        help="并发线程数"
    )
    parser.add_argument(
        "-d", "--delay", type=float, default=0.1,
        help="每次密码尝试之间的延时（秒）"
    )
    parser.add_argument(
        "-m", "--max-failures", type=int, default=2,
        help="对同一主机允许的最大网络错误或超时次数，达到该次数将跳过剩余密码尝试"
    )

    # --- Data Fetching ---
    parser.add_argument(
        "-C", "--get-clients", action="store_true",
        help="成功登录后尝试获取 NPS 客户端列表数据"
    )
    parser.add_argument(
        "-T", "--get-tunnels", action="store_true",
        help="成功登录后尝试获取 NPS 隧道（端口管理）列表数据"
    )
    parser.add_argument(
        "--client-api-path", default=CLIENT_DATA_PATH,
        help="NPS 获取客户端列表的 API 相对路径"
    )
    parser.add_argument(
        "--tunnel-api-path", default=TUNNEL_DATA_PATH,
        help="NPS 获取隧道列表的 API 相对路径"
    )
    parser.add_argument(
        "--tunnel-page-limit", type=int, default=TUNNEL_PAGE_LIMIT,
        help="获取隧道数据时每页请求的数量"
    )

    # --- Output & Saving ---
    parser.add_argument(
        "-o", "--output", default=DEFAULT_OUTPUT_FILE,
        help="成功账号密码的输出文件路径 (格式: base_url -> username=password)"
    )
    parser.add_argument(
        "-S", "--save-data", action="store_true",
        help=f"将成功获取的客户端数据保存为 .json 文件 (每个主机一个)，将隧道数据聚合保存到指定文件"
    )
    parser.add_argument(
        "--aggregated-tunnels-file", default=DEFAULT_AGGREGATED_TUNNELS_FILE,
        help="聚合保存隧道数据的目标文件路径"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="启用详细输出模式，显示每次尝试结果和数据获取详情"
    )

    args = parser.parse_args() # 解析命令行参数，结果存储在 args 对象中

    # --- Argument Validation ---
    # Validate -S requires -C or -T
    if args.save_data and not (args.get_clients or args.get_tunnels):
         parser.error("错误: 已指定 -S/--save-data 标志，但未指定 -C/--get-clients 或 -T/--get-tunnels。请指定需要获取和保存的数据类型。")

    # Validate priority passwords are strings
    if any(not isinstance(p, str) for p in args.priority_passwords):
        parser.error("错误: --priority-passwords 必须是字符串列表。")

    # Suggest verbose mode if saving data
    if args.save_data and not args.verbose:
         print(f"[*] 提示: 已指定 -S/--save-data 标志。建议同时启用 -v 参数以查看数据保存的详细提示。", file=sys.stderr)

    # Ensure priority passwords are treated as a set for efficient lookup later
    args.priority_passwords = set(args.priority_passwords)

    return args # 返回解析后的参数对象，main 函数会使用这些参数


def load_targets(target_list_file, single_target):
    """
    根据用户指定的参数加载目标主机列表。支持从文件加载或直接指定单个目标。
    函数会对列表进行去重和排序。

    Args:
        target_list_file (str): 目标文件路径 (如果用户通过 -l 指定)。
        single_target (str): 单个目标地址 (如果用户通过 -H 指定)。

    Returns:
        list: 包含唯一且已排序的目标主机地址 (host:port) 的列表。

    Raises:
        FileNotFoundError: 如果指定的目标文件不存在。
        ValueError: 如果目标文件为空或不包含有效目标，或者指定的单个目标为空。
        IOError: 如果读取目标文件时发生其他错误。
    """
    hosts = [] # 初始化存储目标主机的空列表

    if target_list_file: # 如果用户指定了目标文件
        if not os.path.isfile(target_list_file): # 检查文件是否存在
            raise FileNotFoundError(f"错误: 未找到目标文件: {target_list_file}") # 文件不存在则抛出 FileNotFoundError
        try:
            # 打开并读取目标文件，每行一个目标，并移除行首尾空白字符
            with open(target_list_file, 'r', encoding="utf-8") as tf: # Specify 'r' mode
                hosts = [line.strip() for line in tf if line.strip()] # 过滤掉空行
            if not hosts: # 如果读取后列表为空
                 raise ValueError(f"错误: 目标文件 {target_list_file} 为空或不包含有效目标。") # 文件为空则抛出 ValueError
        except Exception as e: # 捕获文件读取时可能发生的其他异常
             raise IOError(f"错误: 读取目标文件 {target_list_file} 失败: {e}") from e # 重新抛出 IOError，包含原始异常信息

    elif single_target: # 如果用户指定了单个目标
        hosts = [single_target.strip()] # 将单个目标（移除空白字符后）放入列表中
        if not hosts or not hosts[0]: # 检查单个目标是否为空字符串
             raise ValueError(f"错误: 提供的单个目标地址为空。") # 单个目标为空则抛出 ValueError

    # 对加载的主机列表进行去重和排序，确保每个目标只处理一次
    original_host_count = len(hosts) # 记录去重前的数量
    unique_hosts = sorted(list(set(h for h in hosts if h))) # Use set for deduplication, filter empty strings again just in case
    deduplicated_host_count = len(unique_hosts) # 记录去重后的数量

    # 打印去重信息（如果发生了去重）
    if original_host_count > deduplicated_host_count:
        print(f"[*] 已对目标列表进行去重，移除了 {original_host_count - deduplicated_host_count} 个重复项。")

    return unique_hosts # 返回处理后的唯一且排序的目标主机列表

def load_passwords(password_file, priority_passwords_set):
    """
    根据用户指定的参数加载密码列表。如果未指定文件，则使用内置的弱口令列表。
    Ensures priority passwords are included and listed first.

    Args:
        password_file (str): 密码文件路径 (如果用户通过 -p 指定)。
        priority_passwords_set (set): A set of passwords to try first.

    Returns:
        list: 包含密码字符串的列表, with priority passwords first.

    Raises:
        FileNotFoundError: 如果指定的密码文件不存在。
        ValueError: 如果密码文件为空或不包含有效密码。
        IOError: 如果读取密码文件时发生其他错误。
    """
    passwords_from_file = [] # Initialize list for passwords from file or default

    if password_file: # 如果用户指定了密码文件
        if not os.path.isfile(password_file): # 检查文件是否存在
            raise FileNotFoundError(f"错误: 未找到密码文件: {password_file}") # 文件不存在则抛出 FileNotFoundError
        try:
            # 打开并读取密码文件，每行一个密码，并移除行首尾空白字符
            with open(password_file, 'r', encoding="utf-8") as f: # Specify 'r' mode
                passwords_from_file = [line.strip() for line in f if line.strip()] # 过滤掉空行
            if not passwords_from_file: # 如果读取后列表为空
                 raise ValueError(f"错误: 密码文件 {password_file} 为空或不包含有效密码。") # 文件为空则抛出 ValueError
            print(f"[*] 从文件 {password_file} 加载了 {len(passwords_from_file)} 个密码。")
        except Exception as e: # 捕获文件读取时可能发生的其他异常
             raise IOError(f"错误: 读取密码文件 {password_file} 失败: {e}") from e # 重新抛出 IOError，包含原始异常信息

    else: # 如果用户未指定密码文件
        passwords_from_file = list(DEFAULT_PASSWORDS) # Use copy of default list
        print("[*] 未指定密码文件，使用内置弱口令列表。")

    # Combine priority passwords and other passwords, ensuring priority come first and no duplicates
    # Start with priority passwords (convert set back to list, order might not be preserved but they are first)
    final_passwords = list(priority_passwords_set)
    # Add passwords from file/default list only if they are not already in the priority list
    final_passwords.extend([p for p in passwords_from_file if p not in priority_passwords_set])

    print(f"[*] 共准备 {len(final_passwords)} 个唯一密码进行尝试 (优先: {len(priority_passwords_set)})。") # 打印加载的密码数量
    return final_passwords # 返回加载的密码列表
