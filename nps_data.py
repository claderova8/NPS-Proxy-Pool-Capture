# -*- coding: utf-8 -*-
# 数据获取模块 - 负责在成功登录 NPS 后，获取客户端列表和隧道列表数据。

import requests # 导入 requests 库，用于发送网络请求
import json     # 导入 json 模块，用于解析 JSON 数据
import sys      # 导入 sys 模块，用于打印到标准错误或标准输出
import os       # 导入 os 模块，用于文件操作
import re       # 导入 re 模块，用于更灵活地分割字符串
from urllib.parse import urljoin # 导入 urljoin 函数，用于拼接 URL

# 禁用 requests 库的 HTTPS 警告
# Note: Consider making this conditional based on a flag if needed.
try:
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass


def get_nps_client_data(session, host, scheme, username, password, client_api_path, verbose=False, pbar=None, save_data=False):
    """
    使用已建立的会话尝试从 NPS 获取客户端列表数据。
    函数会发送请求，解析 JSON 响应，并根据参数决定是否保存数据到文件。

    Args:
        session (requests.Session): 用于发送请求的 requests 会话对象。
        host (str): 目标主机的地址 (格式: host:port)。
        scheme (str): 成功登录时使用的协议 ('http' 或 'https')。
        username (str): 成功登录的用户名。
        password (str): 成功登录的密码。
        client_api_path (str): The relative API path for fetching client data.
        verbose (bool): 是否启用详细输出模式。
        pbar (tqdm.Tqdm or DummyPbar, optional): 进度条对象，用于安全打印信息。
        save_data (bool): 是否需要保存获取到的数据到 .json 文件（每个主机一个文件）。

    Returns:
        dict or None: 返回解析后的 JSON 数据字典。如果请求失败、解析失败或发生异常，返回 None。
                      如果获取到数据但列表为空，仍然返回数据字典（其中 'rows' 可能为空列表）。
    """
    base_url = f"{scheme}://{host}" # 构建基础 URL
    # 拼接 NPS 客户端列表接口的完整 URL using the provided path
    data_url = urljoin(base_url, client_api_path) # 使用参数 client_api_path

    output_func = pbar.write if pbar else print # 根据 pbar 是否存在选择输出函数

    # 定义请求头，模拟浏览器行为
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01", # 期望 JSON 响应
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", # 通常是 POST 带表单数据
        "Referer": urljoin(base_url, "/index"), # 模拟从首页发起的请求 (adjust if needed)
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        # Add cookies from session if needed, though session handles them automatically
    }

    # 定义请求参数，根据 NPS Web 界面的实际请求调整
    # Consider making limit configurable if needed
    params = { # Use params for GET, data for POST. Assuming POST based on Content-Type.
        "search": "",    # 空搜索，获取所有客户端
        "order": "asc",  # 按升序排序
        "offset": 0,     # 从第0条数据开始
        "limit": 10      # 默认获取前10条数据
    }

    try:
        # 发送 POST 请求获取客户端数据 (adjust to GET if necessary for the API)
        resp = session.post( # Or session.get(data_url, headers=headers, params=params, ...)
            data_url,
            headers=headers,
            data=params, # Use data for POST body
            timeout=10, # 设置超时时间
            verify=False # 禁用证书验证
        )

        if resp.status_code != 200: # 如果状态码不是 200，请求失败
            if verbose:
                output_func(f"[-] 获取 NPS 客户端数据失败 ({data_url}, 参数: {params})，状态码: {resp.status_code}", file=sys.stderr)
            return None # 返回 None 表示获取失败

        # 尝试解析 JSON 响应
        try:
            parsed_data = resp.json() # requests 库可以直接将响应体解析为 JSON

            # 从返回的 JSON 中提取 'total'（总数）和 'rows'（当前页数据列表）字段
            # Use .get() for safety
            client_count_raw = parsed_data.get("total")
            client_count = int(client_count_raw) if isinstance(client_count_raw, (int, str)) and str(client_count_raw).isdigit() else "未知"
            clients_list = parsed_data.get("rows", [])       # 获取客户端列表，如果不存在则为空列表

            # 在详细模式下打印获取到的数据概览
            if verbose:
                 count_str = str(client_count) if client_count != "未知" else client_count
                 if clients_list: # 如果客户端列表非空
                     # 打印成功获取客户端数据的信息
                     pbar.write(f"[✔] {base_url} 成功获取客户端数据 (总数: {count_str})")
                     # 打印部分客户端列表的 JSON 格式数据 (只打印少量信息避免刷屏)
                     preview_list = clients_list[:3] # 只预览前3条
                     pbar.write(f"[✔] {base_url} 客户端数据预览 (前 {len(preview_list)} 条):\n{json.dumps(preview_list, indent=2, ensure_ascii=False)}")
                 elif client_count == 0: # 如果总数为 0
                      pbar.write(f"[*] {base_url} 成功获取客户端数据，总数: 0。")
                 else: # 其他情况，例如总数不是数字，或列表为空但总数不为 0
                      pbar.write(f"[*] {base_url} 获取客户端数据，总数: {count_str}，但列表为空或格式异常。")
                      if verbose and parsed_data: # 如果在详细模式下且有解析到的数据，打印数据片段用于调试
                           pbar.write(f"原始响应数据片段:\n{json.dumps(parsed_data, indent=2, ensure_ascii=False)[:500]}...", file=sys.stderr)

            # 根据 save_data 参数决定是否将数据保存到文件
            if save_data and clients_list: # 仅在需要保存数据且获取到非空客户端列表时才保存
                 # 构建保存文件的文件名，使用主机地址并替换冒号，加上 .json 后缀
                 # Sanitize filename further if needed (e.g., handle other invalid chars)
                 safe_host = host.replace(':', '_').replace('/', '_')
                 filename = f"{safe_host}_clients.json"
                 try:
                     # 以写入模式 'w' 打开文件，如果文件已存在则覆盖
                     with open(filename, 'w', encoding='utf-8') as f:
                         # 将获取到的 JSON 数据以美化（indent=2）的方式写入文件，并确保支持中文
                         json.dump(parsed_data, f, indent=2, ensure_ascii=False)
                     if verbose: # 在详细模式下打印保存成功信息
                         pbar.write(f"[✔] 客户端数据已保存到文件: {filename}")
                 except IOError as e: # Catch file IO errors specifically
                      if verbose: # 在详细模式下打印保存失败错误信息
                          pbar.write(f"[-] 错误：保存客户端数据到文件 {filename} 失败: {e}", file=sys.stderr)
                 except Exception as e: # Catch other potential errors during saving
                      if verbose:
                          pbar.write(f"[-] 错误：保存客户端数据到文件 {filename} 时发生意外错误: {e}", file=sys.stderr)

            elif save_data and verbose and not clients_list: # 如果启用了保存，但客户端列表为空
                 if verbose:
                     pbar.write(f"[*] 未获取到客户端列表数据，未创建客户端数据文件。", file=sys.stdout)


            return parsed_data # 返回解析后的完整数据字典，无论列表是否为空
        except json.JSONDecodeError: # 捕获 JSON 解析错误
            if verbose:
                snippet = resp.text[:200].replace('\n', ' ') + ('...' if len(resp.text) > 200 else '')
                output_func(f"[-] 获取 NPS 客户端数据响应非 JSON 格式 ({data_url}, 参数: {params}):\n{snippet}", file=sys.stderr)
            return None # 解析失败返回 None
        except Exception as e: # 捕获其他解析过程中可能发生的异常
             if verbose:
                 output_func(f"[-] 解析 NPS 客户端数据响应时发生错误 ({data_url}, 参数: {params}): {e}", file=sys.stderr)
             return None # 其他解析异常返回 None

    except requests.exceptions.RequestException as e: # 捕获 requests 库的所有请求异常（如连接错误、超时等）
        if verbose:
            output_func(f"[-] 请求 NPS 客户端数据 ({data_url}, 参数: {params}) 时发生请求异常: {e}", file=sys.stderr)
        return None # 请求异常返回 None
    except Exception as e: # 捕获其他所有意外异常
        if verbose:
            output_func(f"[-] 处理 NPS 客户端数据 ({data_url}, 参数: {params}) 时发生意外错误: {e}", file=sys.stderr)
        return None # 其他意外错误返回 None


def format_tunnel_data(tunnel, host_ip, verbose=False, pbar=None):
    """
    格式化单个隧道数据条目。如果条目包含多个凭证信息（如在 S5User 字段中
    以逗号或换行符分隔），则为每个凭证生成一个格式化字符串。
    修改：对于无认证的 socks5 隧道，输出格式为 'socks5 ip:port'。

    Args:
        tunnel (dict): 一个字典，包含单个隧道配置的详细信息。
        host_ip (str): 目标主机的 IP 地址部分。
        verbose (bool): 是否启用详细输出模式。
        pbar (tqdm.Tqdm or DummyPbar, optional): 进度条对象，用于安全打印信息。

    Returns:
        list[str]: 包含一个或多个格式化隧道信息字符串的列表
                   (例如 ['socks5 1.2.3.4:5555 user1 pass1', 'socks5 1.2.3.4:5555 user2 pass2'] 或 ['socks5 1.2.3.4:5555'])。
                   如果隧道无效或未找到有效凭证，则返回空列表。
    """
    output_func = pbar.write if pbar else print
    formatted_lines = [] # 用于存储此隧道的所有格式化输出行

    # 从隧道字典中安全地获取字段值
    mode = tunnel.get("Mode", "").lower() # Default to empty string if missing
    port = tunnel.get("Port") # Get port, check type later
    s5_user_field = tunnel.get("S5User", "") # 获取 S5User 字段的原始值
    s5_password_field = tunnel.get("S5Password", "") # 获取 S5Password 字段

    # --- 基础信息检查 ---
    # Ensure port is valid (convert to string, check if digit, check if not empty)
    port_str = str(port) if port is not None else ""
    if mode != "socks5" or not port_str.isdigit() or not port_str:
        if verbose:
            # Provide more specific reason for skipping
            reason = "非 socks5 模式" if mode != "socks5" else f"无效端口 ('{port_str}')"
            output_func(f"[*] 跳过隧道条目 ({reason}) : {tunnel.get('Id', '无ID')}, Mode={mode}, Port={port}", file=sys.stderr)
        return [] # 返回空列表表示无效

    base_info = f"socks5 {host_ip} {port_str}" # 构建基础部分 'socks5 ip:port'

    # --- 凭证提取逻辑 ---
    credential_pairs = [] # 存储解析出的 (user, password) 元组

    # Define default values for no auth
    NO_USER = "nouser"
    NO_PASSWORD = "nopassword"

    # 1. 检查 S5User 字段是否包含多个凭证 (用逗号或换行符分隔)
    #    使用 re.split 来处理逗号和换行符，并去除空字符串
    #    Handle potential None value for s5_user_field
    potential_creds = []
    if isinstance(s5_user_field, str):
        potential_creds = [cred.strip() for cred in re.split(r'[,\n]', s5_user_field) if cred.strip()]

    if len(potential_creds) > 1:
        # 如果 S5User 字段包含多个潜在凭证
        if verbose:
            output_func(f"[*] 发现 S5User 字段包含多个潜在凭证: '{s5_user_field}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stdout)
        processed_multi = False
        for cred_pair_str in potential_creds:
            if ':' in cred_pair_str:
                try:
                    user, password = cred_pair_str.split(':', 1)
                    # Ensure user and password are not empty after split
                    user = user.strip()
                    password = password.strip()
                    if user and password:
                        credential_pairs.append((user, password))
                        processed_multi = True
                    elif user: # 如果只有用户名，密码视为 nopassword
                        credential_pairs.append((user, NO_PASSWORD))
                        processed_multi = True
                    else: # 格式错误 (e.g., ":pass")
                         if verbose: output_func(f"[*] 警告：跳过 S5User 中格式不正确的凭证对 '{cred_pair_str}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stderr)
                except ValueError: # Should not happen with split(':', 1) but good practice
                     if verbose: output_func(f"[*] 警告：跳过 S5User 中无法解析的凭证对 '{cred_pair_str}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stderr)
            elif cred_pair_str: # Treat as username if non-empty and no colon
                 # 如果没有冒号，假定它是用户名，密码为空
                 credential_pairs.append((cred_pair_str, NO_PASSWORD))
                 processed_multi = True
                 if verbose: output_func(f"[*] S5User 中的 '{cred_pair_str}' 没有密码，假设密码为 '{NO_PASSWORD}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stdout)
        # If after processing multiple, none were valid, maybe fall back? Or just return empty.
        # Current logic: if potential_creds > 1, we only use those.

    # 2. 如果 S5User 不包含多个凭证 (len(potential_creds) <= 1)
    #    则检查 S5User 和 S5Password 字段的组合
    elif s5_user_field and s5_password_field:
        # 标准情况：S5User 和 S5Password 都有值 (strip them)
        credential_pairs.append((s5_user_field.strip(), s5_password_field.strip()))
    elif s5_user_field and ':' in s5_user_field:
        # S5User 包含 user:pass 格式，S5Password 为空
        try:
            user, password = s5_user_field.split(':', 1)
            user = user.strip()
            password = password.strip()
            if user and password:
                credential_pairs.append((user, password))
            elif user: # Only user provided in user: format
                 credential_pairs.append((user, NO_PASSWORD))
            else: # Starts with ':'
                 if verbose: output_func(f"[*] 警告：跳过 S5User 中格式不正确的凭证对 '{s5_user_field}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stderr)
        except ValueError:
             if verbose: output_func(f"[*] 警告：跳过 S5User 中无法解析的凭证对 '{s5_user_field}' (隧道 ID: {tunnel.get('Id', '无ID')})", file=sys.stderr)
    elif s5_user_field:
        # 只有 S5User 有值，密码为空 (treat S5Password as empty)
        credential_pairs.append((s5_user_field.strip(), NO_PASSWORD))
    elif s5_password_field:
        # 只有 S5Password 有值，用户名为空 (treat S5User as empty) - This case might not be common but handle it
        credential_pairs.append((NO_USER, s5_password_field.strip()))
    else:
        # S5User 和 S5Password 都为空或无效，表示无认证
        credential_pairs.append((NO_USER, NO_PASSWORD)) # 代表无认证

    # --- 构建输出行 ---
    added_creds = set() # 用于跟踪已添加的凭证对，避免重复
    for user, password in credential_pairs:
        # Basic sanitation: replace spaces in user/pass, though ideally NPS shouldn't allow them
        user_safe = user.replace(" ", "_")
        pass_safe = password.replace(" ", "_")
        cred_tuple = (user_safe, pass_safe)

        if cred_tuple not in added_creds:
            # --- 修改点：根据凭证是否为 NO_USER/NO_PASSWORD 决定输出格式 ---
            if user_safe == NO_USER and pass_safe == NO_PASSWORD:
                formatted_lines.append(f"{base_info}") # 无认证时只输出 ip:port
            else:
                formatted_lines.append(f"{base_info} {user_safe} {pass_safe}") # 有认证时输出 ip:port user pass
            # --- 修改点结束 ---
            added_creds.add(cred_tuple)

    if not formatted_lines and verbose:
        # This might be normal if auth is disabled, check tunnel status?
        # Check if auth is explicitly disabled in the tunnel data if possible
        auth_disabled = not s5_user_field and not s5_password_field
        if not auth_disabled: # Only warn if creds were expected but not found/parsed
            output_func(f"[*] 警告：未能在隧道条目中找到有效的凭证: ID={tunnel.get('Id', '无ID')}, S5User='{s5_user_field}', S5Password='{s5_password_field}'", file=sys.stderr)
        # else: # If auth is disabled, it's expected to have no lines here if NO_USER/NO_PASSWORD wasn't added
        #     output_func(f"[*] Info: Tunnel ID={tunnel.get('Id', '无ID')} appears to have no authentication configured.", file=sys.stdout)


    return formatted_lines


def get_nps_tunnel_data(session, host, scheme, username, password, tunnel_api_path, tunnel_page_limit, verbose=False, pbar=None):
    """
    使用已建立的会话尝试从 NPS 获取隧道列表数据，处理分页逻辑。
    函数会循环请求所有页面的数据，并返回包含所有隧道条目的列表。
    此函数只负责获取和解析数据，不负责将数据格式化或保存到文件。

    Args:
        session (requests.Session): 用于发送请求的 requests 会话对象。
        host (str): 目标主机的地址 (格式: host:port)。
        scheme (str): 成功登录时使用的协议 ('http' 或 'https')。
        username (str): 成功登录的用户名。
        password (str): 成功登录的密码。
        tunnel_api_path (str): The relative API path for fetching tunnel data.
        tunnel_page_limit (int): The number of items to request per page.
        verbose (bool): 是否启用详细输出模式。
        pbar (tqdm.Tqdm or DummyPbar, optional): 进度条对象，用于安全打印信息。

    Returns:
        list: 返回包含所有隧道数据字典的列表。如果获取失败或解析失败，返回空列表。
    """
    base_url = f"{scheme}://{host}" # 构建基础 URL
    # 拼接 NPS 隧道列表接口的完整 URL using provided path
    data_url = urljoin(base_url, tunnel_api_path) # 使用参数 tunnel_api_path

    output_func = pbar.write if pbar else print # 根据 pbar 是否存在选择输出函数

    # 定义请求头，模拟浏览器行为
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01", # 期望 JSON 响应
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", # 通常是 POST 带表单数据
        "Referer": urljoin(base_url, "/index"), # 模拟从首页发起的请求
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    all_tunnels = [] # 初始化一个空列表，用于存储所有页面的隧道数据
    offset = 0 # 初始分页偏移量
    limit = tunnel_page_limit # 每页获取的数据数量，从参数导入
    total_fetched_count = 0 # 记录实际获取的总条数
    page_num = 1 # Track page number for logging

    # 循环获取所有分页的隧道数据，直到获取完所有数据或发生错误
    while True:
        # 定义请求参数，包括偏移量、每页数量、隧道类型等
        # Assuming POST based on Content-Type
        data = {
            "offset": offset,        # 当前页的起始偏移量
            "limit": limit,          # 每页获取的数量
            "type": "socks5",        # 默认只获取 socks5 类型，可以根据需要修改或循环获取所有类型
            "client_id": "",         # 默认获取所有客户端的隧道，可以根据需要修改
            "search": "",            # 空搜索，获取所有隧道
        }

        if verbose:
            output_func(f"[*] {base_url} 正在获取隧道数据第 {page_num} 页 (offset: {offset}, limit: {limit})...", file=sys.stdout)

        try: # 第一个 try 块：用于捕获发送请求本身可能发生的异常（如连接错误、超时）
            # 发送 POST 请求获取隧道数据
            resp = session.post( # Or session.get if API uses GET
                data_url,
                headers=headers,
                data=data, # 传递请求体参数
                timeout=15, # 增加超时时间以应对可能的慢响应
                verify=False # 禁用证书验证
            )

            if resp.status_code != 200: # 如果状态码不是 200，请求失败
                if verbose:
                    output_func(f"[-] 获取 NPS 隧道数据失败 ({data_url}, 页: {page_num}, 参数: {data})，状态码: {resp.status_code}", file=sys.stderr)
                break # 请求失败，退出分页循环

            try: # 第二个 try 块：嵌套在第一个 try 块中，用于捕获 JSON 解析和数据处理异常
                parsed_data = resp.json() # 尝试将响应体解析为 JSON

                # 从解析后的 JSON 数据中提取当前页的隧道列表和总数
                current_tunnels = parsed_data.get("rows", [])       # 获取当前页的隧道列表，如果不存在则为空列表
                # 尝试更可靠地获取总数，如果 total 键不存在或不是数字，则标记为未知
                total_count_raw = parsed_data.get("total")
                # Handle potential None or non-integer total
                total_count = None
                if isinstance(total_count_raw, (int, str)) and str(total_count_raw).isdigit():
                    total_count = int(total_count_raw)

                current_page_count = len(current_tunnels) if isinstance(current_tunnels, list) else 0

                if current_page_count > 0: # 只有当获取到数据时才添加到列表和增加计数
                    all_tunnels.extend(current_tunnels)
                    total_fetched_count += current_page_count

                # 在详细模式下打印当前页的获取信息
                if verbose:
                     total_str = str(total_count) if total_count is not None else "未知"
                     output_func(f"[*] {base_url} 隧道数据第 {page_num} 页获取: {current_page_count} 条 (累计: {total_fetched_count}, API报告总数: {total_str})", file=sys.stdout)

                # 判断是否还有下一页数据：
                # 1. 如果 API 返回的总数已知，并且已获取的数量达到或超过总数，则停止
                # 2. 如果当前页获取的数据数量为 0 或少于请求的 limit，则停止
                if total_count is not None and total_fetched_count >= total_count:
                    if verbose: output_func(f"[*] 已获取 {total_fetched_count} 条隧道，达到或超过 API 报告的总数 {total_count}，停止分页。", file=sys.stdout)
                    break
                # Check if the number fetched is less than the limit OR if 0 items were fetched
                if current_page_count == 0 or current_page_count < limit:
                    if verbose:
                        reason = "获取数量为 0" if current_page_count == 0 else f"获取数量 {current_page_count} 少于请求数量 {limit}"
                        output_func(f"[*] {reason}，假定为最后一页，停止分页。", file=sys.stdout)
                    break
                else:
                    offset += limit # 否则，增加偏移量，准备获取下一页数据
                    page_num += 1 # Increment page number for logging

            except json.JSONDecodeError: # 捕获 JSON 解析错误
                if verbose:
                    snippet = resp.text[:200].replace('\n', ' ') + ('...' if len(resp.text) > 200 else '')
                    output_func(f"[-] 获取 NPS 隧道数据响应非 JSON 格式 ({data_url}, 页: {page_num}, 参数: {data}):\n{snippet}", file=sys.stderr)
                break # JSON 解析失败，退出分页循环
            except Exception as e: # 捕获解析和处理当前页数据时可能发生的其他异常
                 if verbose:
                     output_func(f"[-] 解析 NPS 隧道数据响应或处理数据时发生错误 ({data_url}, 页: {page_num}, 参数: {data}): {e}", file=sys.stderr)
                 break # 其他异常，退出分页循环

        except requests.exceptions.RequestException as e: # 捕获 requests 库的所有请求异常（如连接错误、超时）
            if verbose:
                output_func(f"[-] 请求 NPS 隧道数据 ({data_url}, 页: {page_num}, 参数: {data}) 时发生请求异常: {e}", file=sys.stderr)
            break # 请求异常，退出分页循环
        except Exception as e: # 捕获处理请求和响应的第一个 try 块中可能发生的其他意外异常
            if verbose:
                output_func(f"[-] 处理 NPS 隧道数据 ({data_url}, 页: {page_num}, 参数: {data}) 时发生意外错误: {e}", file=sys.stderr)
            break # 其他意外错误，退出分页循环

    # 分页循环结束后，all_tunnels 列表中包含了该主机的所有隧道数据
    if verbose and all_tunnels: # 如果在详细模式下且获取到隧道数据
         # 打印成功获取所有隧道数据的信息
         pbar.write(f"[✔] {base_url} 隧道数据获取完成 (共获取 {len(all_tunnels)} 条原始条目)")
    elif verbose and not all_tunnels: # 如果在详细模式下但没有获取到隧道数据
         pbar.write(f"[*] {base_url} 未获取到任何隧道数据。")

    return all_tunnels # 返回包含所有隧道数据字典的列表
