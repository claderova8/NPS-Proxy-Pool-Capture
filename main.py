# -*- coding: utf-8 -*-
# 主脚本 - 程序的入口点，负责参数解析、任务调度和结果汇总。

import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 导入自定义模块 (已修改为绝对导入，便于直接运行 main.py)
from nps_args import parse_args, load_targets, load_passwords      # 参数解析和加载模块
# 使用更新后的 nps_core
from nps_core import brute_host, DummyPbar                        # 核心逻辑模块，包含暴力破解和数据获取功能
from nps_constants import DEFAULT_OUTPUT_FILE, DEFAULT_AGGREGATED_TUNNELS_FILE # 常量模块，定义文件路径等常量

# 导入 tqdm 库，用于显示进度条。如果未安装，打印错误并退出。
# 请确保已安装 tqdm: pip install tqdm
try:
    from tqdm import tqdm
except ImportError:
    print("错误: 缺少 tqdm 库。请运行 'pip install tqdm' 安装。", file=sys.stderr)
    sys.exit(1)


def main():
    """
    主函数：
    1. 解析命令行参数。
    2. 加载目标主机列表和密码列表。
    3. 初始化输出文件和聚合隧道数据文件（如果需要）。
    4. 使用线程池启动针对每个目标主机的暴力破解和数据获取任务。
    5. 实时更新进度条。
    6. 汇总任务结果。
    7. 确保文件句柄正确关闭。
    8. 打印最终的统计信息。
    9. 处理可能发生的异常。
    """
    args = parse_args() # 解析命令行参数，获取用户输入

    # 从解析的参数中提取各个配置项
    username = args.username
    max_threads = args.threads
    output_file = args.output # 成功账号密码输出文件路径
    delay = args.delay # 每次尝试之间的延时
    verbose = args.verbose # 是否启用详细输出模式
    max_failures_per_host = args.max_failures # 同一主机允许的最大网络失败次数
    save_data = args.save_data # 是否保存获取到的数据
    get_clients = args.get_clients # 是否获取客户端数据
    get_tunnels = args.get_tunnels # 是否获取隧道数据

    # 打印程序的启动信息和关键配置
    print("[*] 程序启动：NPS 弱口令检测与数据获取")
    print(f"[*] 登录成功判断依据: JSON 响应包含 'status' == 1")
    print(f"[*] NPS 客户端列表 API: {args.client_api_path} (默认获取前 10 条)") # 使用参数中的 API 路径
    print(f"[*] NPS 隧道列表 API: {args.tunnel_api_path} (默认分页大小: {args.tunnel_page_limit})") # 使用参数中的 API 路径和分页大小
    print(f"[*] 预期数据在 JSON 'rows' 字段，总数在 'total' 字段")
    print(f"[*] 优先尝试的密码: {', '.join(args.priority_passwords)}") # 使用参数中的优先密码
    print(f"[*] 同一主机最大网络错误或超时次数: {max_failures_per_host}")
    print(f"[*] 使用用户名: {username}")
    print(f"[*] 并发线程数: {max_threads}")
    print(f"[*] 每次尝试延时: {delay} 秒")

    # 根据参数打印额外数据获取和保存的状态
    if get_clients and get_tunnels:
        print("[*] 已启用 -C 和 -T: 成功登录后将尝试获取客户端和隧道数据。")
    elif get_clients:
        print("[*] 已启用 -C: 成功登录后将尝试获取客户端数据。")
    elif get_tunnels:
        print("[*] 已启用 -T: 成功登录后将尝试获取隧道数据。")
    else:
        print("[*] 未指定 -C 或 -T: 成功登录后将跳过所有额外数据获取步骤。")

    if save_data:
        print(f"[*] 已启用 -S/--save-data: 成功获取的数据将保存到文件。客户端数据 (.json)，隧道数据将聚合保存到 {args.aggregated_tunnels_file} (.txt 格式)。") # 使用参数中的聚合文件名
    else:
         print("[*] 未指定 -S/--save-data: 额外数据将不会保存到文件。")

    try:
        # 加载目标主机列表和密码列表
        # 将常量中的优先密码列表传递给 load_passwords
        hosts = load_targets(args.target_list, args.single_target)
        passwords = load_passwords(args.password_list, args.priority_passwords)
    except (FileNotFoundError, ValueError, IOError) as e:
        # 捕获加载文件时可能发生的异常并退出
        print(f"[-] 错误: 加载目标或密码文件失败: {e}", file=sys.stderr)
        sys.exit(1)


    total_hosts = len(hosts) # 获取总的目标主机数量，用于进度条

    # 如果没有目标，直接退出
    if total_hosts == 0:
        print("[*] 没有找到有效的目标主机。程序退出。")
        sys.exit(0)

    print(f"[*] 共加载 {total_hosts} 个唯一目标。")
    print("[*] 开始执行 NPS 弱口令检测和数据获取任务...")

    tunnel_fp = None # 初始化隧道文件句柄
    tunnel_lock = None # 初始化隧道文件写入锁

    # 仅在需要保存隧道数据时才打开聚合隧道文件
    if save_data and get_tunnels:
        try:
            # 使用参数中指定的聚合隧道文件名
            tunnel_fp = open(args.aggregated_tunnels_file, 'a', encoding='utf-8')
            tunnel_lock = Lock() # 创建一个线程锁，确保多线程写入文件时不会混乱
            if verbose:
                 print(f"[*] 隧道数据将聚合保存到文件: {args.aggregated_tunnels_file}", file=sys.stdout)
        except Exception as e:
            # 如果文件无法打开，打印错误信息并禁用隧道数据保存，但不中断程序
            print(f"[-] 错误：无法打开隧道聚合保存文件 {args.aggregated_tunnels_file} 进行写入: {e}", file=sys.stderr)
            save_data = False # 禁用隧道数据保存功能
            if tunnel_fp: # 如果文件已经部分打开，尝试关闭
                tunnel_fp.close()
            tunnel_fp = None
            tunnel_lock = None


    # 初始化进度条适配器。如果只有一个目标或没有目标，使用 DummyPbar；否则使用 tqdm。
    current_pbar = None
    if total_hosts > 1:
        current_pbar = tqdm(total=total_hosts, desc="总进度", unit="主机", leave=True, file=sys.stdout) # 将进度条输出到标准输出
    else: # 单目标模式，使用 DummyPbar 避免 tqdm 在单次任务时的额外显示
         current_pbar = DummyPbar()


    # 初始化计数器，用于统计成功的主机数量
    successful_logins_count = 0
    successful_client_data_count = 0
    successful_tunnel_data_count = 0 # Renamed for clarity: counts hosts where tunnel data was *written*

    try:
        # 使用 try...finally 块确保在任务完成后（无论正常结束还是发生异常）都能处理文件句柄的关闭
        try:
            # 使用 with 语句打开成功账号文件，确保文件在块结束时自动关闭
            with open(output_file, "a", encoding="utf-8") as out_fp:
                lock = Lock() # 创建成功账号文件的写入锁

                # 根据目标主机数量确定实际的线程数，单目标时只使用1个线程
                actual_threads = 1 if total_hosts <= 1 else max_threads

                # 使用 ThreadPoolExecutor 创建线程池，管理并发执行的任务
                with ThreadPoolExecutor(max_workers=actual_threads) as executor:

                    # 使用适配后的 pbar 实例作为上下文管理器，确保在 verbose 模式下单目标时也能正确打印
                    with current_pbar as pbar_instance:
                        # 提交 brute_host 任务到线程池，每个主机一个任务
                        # Pass necessary args including API paths and limits
                        futures = [
                            executor.submit(
                                brute_host, host, username, passwords, out_fp, lock,
                                delay, verbose, pbar_instance, max_failures_per_host,
                                get_clients, save_data, get_tunnels,
                                args.client_api_path, args.tunnel_api_path, args.tunnel_page_limit, # Pass API info
                                args.priority_passwords, # Pass priority passwords
                                tunnel_fp, tunnel_lock
                            )
                            for host in hosts
                        ]

                        # 遍历已完成的 Future 对象，获取任务结果并更新计数器
                        for future in as_completed(futures):
                            try:
                                # 获取任务的返回值 (found_success, got_client_data, wrote_tunnel_data)
                                found_success, got_client_data, wrote_tunnel_data = future.result()
                                if found_success:
                                     successful_logins_count += 1
                                if got_client_data:
                                     successful_client_data_count += 1
                                if wrote_tunnel_data: # Check if tunnel data was actually written
                                     successful_tunnel_data_count += 1
                            except Exception as exc:
                                # 捕获任务执行期间发生的异常（例如，brute_host 函数内部未捕获的错误）
                                pbar_instance.write(f"[-] 错误：处理主机时发生未捕获异常: {exc}", file=sys.stderr)
                            finally:
                                # 无论任务成功或失败，都更新进度条
                                pbar_instance.update(1)

        finally:
            # 在 try 块（包括正常结束和异常）结束后执行，确保文件句柄被关闭
            # 检查隧道文件句柄是否存在且未关闭，然后关闭它
            if tunnel_fp and not tunnel_fp.closed:
                tunnel_fp.close()


        # 构建并打印最终的完成消息和统计信息
        final_message_parts = ["\n[*] 所有目标处理完毕。"]

        # 报告成功登录的主机数量和结果文件信息
        if successful_logins_count > 0:
             final_message_parts.append(f"成功登录 {successful_logins_count} 个目标。")
             # 检查输出文件是否存在且有内容
             if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                  final_message_parts.append(f"成功账号密码已写入 {output_file}。")
             else: # 虽然计数大于0，但文件可能因其他原因为空或不存在
                  final_message_parts.append(f"警告: 已成功登录 {successful_logins_count} 个目标，但输出文件 {output_file} 可能为空或写入失败。")
        else:
             final_message_parts.append("未发现成功登录账号。")

        # 报告额外数据获取和保存的状态
        if save_data:
            client_msg = f"客户端数据 ({successful_client_data_count} 个目标)" if get_clients else ""
            # Use the count of hosts where tunnel data was *written*
            tunnel_msg = f"隧道数据 ({successful_tunnel_data_count} 个目标)" if get_tunnels else ""

            if client_msg and tunnel_msg:
                # Check if tunnel file actually has content
                tunnel_file_status = f"已聚合保存到 {args.aggregated_tunnels_file}" if os.path.exists(args.aggregated_tunnels_file) and os.path.getsize(args.aggregated_tunnels_file) > 0 else "未写入或文件为空"
                final_message_parts.append(f"{client_msg} 和 {tunnel_msg} {tunnel_file_status}。")
            elif client_msg:
                 final_message_parts.append(f"{client_msg} 已保存到文件。")
            elif tunnel_msg:
                 tunnel_file_status = f"已聚合保存到 {args.aggregated_tunnels_file}" if os.path.exists(args.aggregated_tunnels_file) and os.path.getsize(args.aggregated_tunnels_file) > 0 else "未写入或文件为空"
                 final_message_parts.append(f"{tunnel_msg} {tunnel_file_status}。")
            # No need for an else here if neither -C nor -T was used with -S (handled by arg parsing)
        elif get_clients or get_tunnels: # If not saving, just report counts
             client_msg = f"成功获取客户端数据 ({successful_client_data_count} 个目标)" if get_clients and successful_client_data_count > 0 else ""
             tunnel_msg = f"成功获取隧道数据 ({successful_tunnel_data_count} 个目标)" if get_tunnels and successful_tunnel_data_count > 0 else "" # Use the write count here too

             if client_msg and tunnel_msg:
                 final_message_parts.append(f"{client_msg} 和 {tunnel_msg}。数据未保存 (未指定 -S)。")
             elif client_msg:
                 final_message_parts.append(f"{client_msg}。数据未保存 (未指定 -S)。")
             elif tunnel_msg:
                 final_message_parts.append(f"{tunnel_msg}。数据未保存 (未指定 -S)。")

        print(" ".join(final_message_parts)) # 使用空格连接所有部分并打印最终消息

    except Exception as e: # 捕获主函数在初始化、线程执行管理等阶段可能发生的致命异常
        print(f"\n致命错误：程序运行过程中发生未处理异常: {e}", file=sys.stderr) # 打印致命错误消息到标准错误
        sys.exit(1) # 以非零状态码退出程序，表示程序异常终止


if __name__ == "__main__":
    # 当脚本直接运行时，调用 main 函数
    main()
