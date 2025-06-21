# -*- coding: utf-8 -*-
# 主脚本 - 程序的入口点，负责参数解析、任务调度和结果汇总。

import sys
import os
import re # 导入 re 模块用于解析主机
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 导入自定义模块
from nps_args import parse_args, load_targets, load_passwords
from nps_core import brute_host, DummyPbar
from nps_constants import DEFAULT_OUTPUT_FILE, DEFAULT_AGGREGATED_TUNNELS_FILE

try:
    from tqdm import tqdm
except ImportError:
    print("错误: 缺少 tqdm 库。请运行 'pip install tqdm' 安装。", file=sys.stderr)
    sys.exit(1)

def load_processed_hosts(file_path):
    """从结果文件中加载已经处理过的主机列表。"""
    processed_hosts = set()
    if not os.path.exists(file_path):
        return processed_hosts
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 从 ok.txt 的行 (e.g., "http://1.2.3.4:8080 -> admin=123") 中提取主机
                # 或直接使用 sb.txt 的行 (e.g., "1.2.3.4:8080")
                match = re.search(r'//(.*?)\s*', line)
                if match:
                    host = match.group(1).strip('/')
                    processed_hosts.add(host)
                else:
                    # 假设没有匹配到 "http://" 的是 sb.txt 中的格式
                    processed_hosts.add(line)
    except Exception as e:
        print(f"[!] 警告: 读取已处理文件 {file_path} 时发生错误: {e}", file=sys.stderr)
        
    return processed_hosts

def main():
    """
    主函数：实现参数解析、任务调度、结果汇总和断点续扫功能。
    """
    args = parse_args()

    # 配置项
    username = args.username
    max_threads = args.threads
    output_file = args.output
    fail_output_file = args.fail_output
    delay = args.delay
    verbose = args.verbose
    max_failures_per_host = args.max_failures
    save_data = args.save_data
    get_clients = args.get_clients
    get_tunnels = args.get_tunnels

    # 打印启动信息
    print("[*] 程序启动：NPS 弱口令检测与数据获取 (V3 - 支持断点续扫)")
    # ... (其他打印信息可以保持不变)

    try:
        hosts = load_targets(args.target_list, args.single_target)
        passwords = load_passwords(args.password_list, args.priority_passwords)
    except (FileNotFoundError, ValueError, IOError) as e:
        print(f"[-] 错误: 加载目标或密码文件失败: {e}", file=sys.stderr)
        sys.exit(1)

    # --- 断点续扫逻辑 ---
    if not args.force_rescan:
        print("[*] 正在检查已处理过的目标...")
        processed_ok = load_processed_hosts(output_file)
        processed_fail = load_processed_hosts(fail_output_file)
        processed_hosts = processed_ok.union(processed_fail)

        if processed_hosts:
            original_count = len(hosts)
            hosts_to_scan = [h for h in hosts if h not in processed_hosts]
            skipped_count = original_count - len(hosts_to_scan)
            if skipped_count > 0:
                print(f"[*] 断点续扫: 已跳过 {skipped_count} 个已存在于结果文件中的目标。")
                print("[*] 使用 --force-rescan 标志可以强制重新扫描所有目标。")
            hosts = hosts_to_scan
    else:
        print("[*] 已启用 --force-rescan，将扫描所有目标。")
    # --- 断点续扫逻辑结束 ---

    total_hosts = len(hosts)
    if total_hosts == 0:
        print("[*] 没有需要扫描的新目标。程序退出。")
        sys.exit(0)

    print(f"[*] 本次将扫描 {total_hosts} 个唯一目标。")
    print("[*] 开始执行 NPS 弱口令检测和数据获取任务...")

    # 初始化文件句柄和锁
    tunnel_fp = None
    tunnel_lock = None
    fail_fp = None
    fail_lock = None

    try:
        fail_fp = open(fail_output_file, 'a', encoding='utf-8')
        fail_lock = Lock()
    except Exception as e:
        print(f"[-] 错误：无法打开失败目标文件 {fail_output_file}: {e}", file=sys.stderr)
        # 即使失败文件打不开，程序也应继续
        fail_fp = None
        fail_lock = None

    if save_data and get_tunnels:
        try:
            tunnel_fp = open(args.aggregated_tunnels_file, 'a', encoding='utf-8')
            tunnel_lock = Lock()
        except Exception as e:
            print(f"[-] 错误：无法打开隧道聚合文件 {args.aggregated_tunnels_file}: {e}", file=sys.stderr)
            tunnel_fp = None
            tunnel_lock = None

    current_pbar = tqdm(total=total_hosts, desc="总进度", unit="主机", leave=True, file=sys.stdout) if total_hosts > 1 else DummyPbar()
    
    successful_logins_count = 0
    successful_client_data_count = 0
    successful_tunnel_data_count = 0

    try:
        try:
            with open(output_file, "a", encoding="utf-8") as out_fp:
                lock = Lock()
                actual_threads = min(max_threads, total_hosts) if total_hosts > 0 else 1

                with ThreadPoolExecutor(max_workers=actual_threads) as executor:
                    with current_pbar as pbar_instance:
                        futures = [
                            executor.submit(
                                brute_host, host, username, passwords, out_fp, lock,
                                delay, verbose, pbar_instance, max_failures_per_host,
                                get_clients, save_data, get_tunnels,
                                args.client_api_path, args.tunnel_api_path, args.tunnel_page_limit,
                                args.priority_passwords,
                                tunnel_fp, tunnel_lock,
                                fail_fp, fail_lock
                            )
                            for host in hosts
                        ]

                        for future in as_completed(futures):
                            try:
                                found_success, got_client_data, wrote_tunnel_data = future.result()
                                if found_success: successful_logins_count += 1
                                if got_client_data: successful_client_data_count += 1
                                if wrote_tunnel_data: successful_tunnel_data_count += 1
                            except Exception as exc:
                                pbar_instance.write(f"[-] 错误：处理主机时发生未捕获异常: {exc}", file=sys.stderr)
                            finally:
                                pbar_instance.update(1)
        finally:
            if tunnel_fp and not tunnel_fp.closed: tunnel_fp.close()
            if fail_fp and not fail_fp.closed: fail_fp.close()

        # 打印最终报告
        final_message_parts = ["\n[*] 所有目标处理完毕。"]
        # ... (后续报告逻辑可以保持，它会报告本次运行的结果)
        print(" ".join(final_message_parts))

    except Exception as e:
        print(f"\n致命错误：程序运行过程中发生未处理异常: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
