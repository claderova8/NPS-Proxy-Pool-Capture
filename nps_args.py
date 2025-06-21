# -*- coding: utf-8 -*-
# 参数解析模块 - 负责定义、解析命令行参数以及加载目标和密码文件。

import argparse
import os
import sys

from nps_constants import (
    DEFAULT_PASSWORDS, PRIORITY_PASSWORDS, CLIENT_DATA_PATH,
    TUNNEL_DATA_PATH, DEFAULT_AGGREGATED_TUNNELS_FILE,
    DEFAULT_OUTPUT_FILE, TUNNEL_PAGE_LIMIT
)


def parse_args():
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="NPS Proxy 弱口令检测与数据获取工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Target Specification ---
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("-l", "--target-list", help="包含目标主机列表的文件路径，每行一个 host:port")
    target_group.add_argument("-H", "--target", dest='single_target', help="直接指定单个目标主机地址 (host:port)")

    # --- Credentials ---
    parser.add_argument("-u", "--username", default="admin", help="指定 NPS 登录用户名")
    parser.add_argument("-p", "--password-list", help="包含自定义密码的文件路径；不指定则使用内置弱口令列表")
    parser.add_argument("--priority-passwords", nargs='+', default=list(PRIORITY_PASSWORDS), help="优先尝试的密码列表 (空格分隔)")

    # --- Connection & Performance ---
    parser.add_argument("-t", "--threads", type=int, default=20, help="并发线程数")
    parser.add_argument("-d", "--delay", type=float, default=0.1, help="每次密码尝试之间的延时（秒）")
    parser.add_argument("-m", "--max-failures", type=int, default=2, help="对同一主机允许的最大网络错误或超时次数")

    # --- Data Fetching ---
    parser.add_argument("-C", "--get-clients", action="store_true", help="成功登录后尝试获取 NPS 客户端列表数据")
    parser.add_argument("-T", "--get-tunnels", action="store_true", help="成功登录后尝试获取 NPS 隧道列表数据")
    parser.add_argument("--client-api-path", default=CLIENT_DATA_PATH, help="NPS 获取客户端列表的 API 相对路径")
    parser.add_argument("--tunnel-api-path", default=TUNNEL_DATA_PATH, help="NPS 获取隧道列表的 API 相对路径")
    parser.add_argument("--tunnel-page-limit", type=int, default=TUNNEL_PAGE_LIMIT, help="获取隧道数据时每页请求的数量")

    # --- Output & Saving ---
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_FILE, help="成功账号密码的输出文件路径")
    parser.add_argument("--fail-output", default="sb.txt", help="爆破失败的目标主机列表的输出文件路径")
    parser.add_argument("-S", "--save-data", action="store_true", help="保存成功获取的数据")
    parser.add_argument("--aggregated-tunnels-file", default=DEFAULT_AGGREGATED_TUNNELS_FILE, help="聚合保存隧道数据的目标文件路径")
    
    # --- Control ---
    parser.add_argument("-v", "--verbose", action="store_true", help="启用详细输出模式")
    # **** 新增：定义强制重新扫描的标志 ****
    parser.add_argument("--force-rescan", action="store_true", help="强制重新扫描所有目标，即使它们存在于旧的结果文件中（默认进行断点续扫）")

    args = parser.parse_args()

    # --- Argument Validation ---
    if args.save_data and not (args.get_clients or args.get_tunnels):
         parser.error("错误: 已指定 -S/--save-data，但未指定 -C 或 -T。")

    if any(not isinstance(p, str) for p in args.priority_passwords):
        parser.error("错误: --priority-passwords 必须是字符串列表。")

    if args.save_data and not args.verbose:
         print(f"[*] 提示: 已启用 -S/--save-data。建议同时启用 -v 以查看详细保存提示。", file=sys.stderr)

    args.priority_passwords = set(args.priority_passwords)

    return args


# load_targets 和 load_passwords 函数保持不变
def load_targets(target_list_file, single_target):
    """根据用户指定的参数加载目标主机列表。"""
    hosts = []
    if target_list_file:
        if not os.path.isfile(target_list_file):
            raise FileNotFoundError(f"错误: 未找到目标文件: {target_list_file}")
        try:
            with open(target_list_file, 'r', encoding="utf-8") as tf:
                hosts = [line.strip() for line in tf if line.strip()]
            if not hosts:
                 raise ValueError(f"错误: 目标文件 {target_list_file} 为空。")
        except Exception as e:
             raise IOError(f"错误: 读取目标文件 {target_list_file} 失败: {e}") from e

    elif single_target:
        hosts = [single_target.strip()]
        if not hosts or not hosts[0]:
             raise ValueError(f"错误: 提供的单个目标地址为空。")

    original_host_count = len(hosts)
    unique_hosts = sorted(list(set(h for h in hosts if h)))
    deduplicated_host_count = len(unique_hosts)

    if original_host_count > deduplicated_host_count:
        print(f"[*] 已对目标列表去重，移除了 {original_host_count - deduplicated_host_count} 个重复项。")

    return unique_hosts

def load_passwords(password_file, priority_passwords_set):
    """根据用户指定的参数加载密码列表。"""
    passwords_from_file = []
    if password_file:
        if not os.path.isfile(password_file):
            raise FileNotFoundError(f"错误: 未找到密码文件: {password_file}")
        try:
            with open(password_file, 'r', encoding="utf-8") as f:
                passwords_from_file = [line.strip() for line in f if line.strip()]
            if not passwords_from_file:
                 raise ValueError(f"错误: 密码文件 {password_file} 为空。")
            print(f"[*] 从文件 {password_file} 加载了 {len(passwords_from_file)} 个密码。")
        except Exception as e:
             raise IOError(f"错误: 读取密码文件 {password_file} 失败: {e}") from e
    else:
        passwords_from_file = list(DEFAULT_PASSWORDS)
        print("[*] 未指定密码文件，使用内置弱口令列表。")

    final_passwords = list(priority_passwords_set)
    final_passwords.extend([p for p in passwords_from_file if p not in priority_passwords_set])

    print(f"[*] 共准备 {len(final_passwords)} 个唯一密码进行尝试 (优先: {len(priority_passwords_set)})。")
    return final_passwords
