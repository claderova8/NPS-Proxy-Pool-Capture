#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOCKS5代理验证脚本
使用方法: python socks5_validator.py -l proxy_list.txt
"""

import argparse
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

class SOCKS5Validator:
    def __init__(self, timeout=10):
        self.timeout = timeout
        self.test_url = "httpbin.org"
        self.test_port = 80
        
    def validate_proxy(self, proxy_info):
        """验证单个SOCKS5代理"""
        try:
            parts = proxy_info.strip().split()
            if len(parts) < 3:
                return False, proxy_info.strip(), "格式错误"
            
            proxy_type = parts[0]
            host = parts[1]
            port = int(parts[2])
            username = parts[3] if len(parts) > 3 else None
            password = parts[4] if len(parts) > 4 else None
            
            if proxy_type.lower() != 'socks5':
                return False, f"{host}:{port}", "不是SOCKS5代理"
            
            # 创建socket连接
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            
            try:
                # 连接到代理服务器
                sock.connect((host, port))
                
                # SOCKS5握手 - 发送认证方法
                if username and password:
                    # 支持用户名/密码认证
                    sock.send(b'\x05\x02\x00\x02')  # VER=5, NMETHODS=2, METHOD=0(无认证), METHOD=2(用户名密码)
                else:
                    # 只支持无认证
                    sock.send(b'\x05\x01\x00')  # VER=5, NMETHODS=1, METHOD=0(无认证)
                
                # 接收认证响应
                response = sock.recv(2)
                if len(response) != 2 or response[0] != 5:
                    sock.close()
                    return False, f"{host}:{port}", "SOCKS5握手失败"
                
                auth_method = response[1]
                
                if auth_method == 0:  # 无认证
                    pass
                elif auth_method == 2:  # 用户名密码认证
                    if not username or not password:
                        sock.close()
                        return False, f"{host}:{port}", "需要用户名密码认证"
                    
                    # 发送用户名密码
                    auth_request = b'\x01'  # 认证协议版本
                    auth_request += bytes([len(username)]) + username.encode()
                    auth_request += bytes([len(password)]) + password.encode()
                    sock.send(auth_request)
                    
                    # 接收认证结果
                    auth_response = sock.recv(2)
                    if len(auth_response) != 2 or auth_response[1] != 0:
                        sock.close()
                        return False, f"{host}:{port}", "用户名密码认证失败"
                        
                elif auth_method == 255:  # 不支持的认证方法
                    sock.close()
                    if username and password:
                        return False, f"{host}:{port}", "不支持用户名密码认证"
                    else:
                        return False, f"{host}:{port}", "不支持无认证方式"
                else:
                    sock.close()
                    return False, f"{host}:{port}", f"不支持的认证方法: {auth_method}"
                
                # 发送连接请求
                # VER=5, CMD=1(CONNECT), RSV=0, ATYP=3(域名)
                request = b'\x05\x01\x00\x03'
                request += bytes([len(self.test_url)]) + self.test_url.encode()
                request += struct.pack('>H', self.test_port)
                sock.send(request)
                
                # 接收连接响应
                response = sock.recv(4)
                if len(response) != 4 or response[0] != 5 or response[1] != 0:
                    sock.close()
                    return False, f"{host}:{port}", "连接请求失败"
                
                # 读取剩余的地址信息
                if response[3] == 1:  # IPv4
                    sock.recv(6)  # 4字节IP + 2字节端口
                elif response[3] == 3:  # 域名
                    addr_len = ord(sock.recv(1))
                    sock.recv(addr_len + 2)  # 域名 + 2字节端口
                elif response[3] == 4:  # IPv6
                    sock.recv(18)  # 16字节IP + 2字节端口
                
                # 发送HTTP请求测试
                http_request = f"GET / HTTP/1.1\r\nHost: {self.test_url}\r\nConnection: close\r\n\r\n"
                sock.send(http_request.encode())
                
                # 接收响应
                response = sock.recv(1024)
                sock.close()
                
                if b"HTTP/" in response:
                    auth_info = f" (用户名密码认证)" if username and password else ""
                    return True, f"{host}:{port}", f"连接成功{auth_info}"
                else:
                    return False, f"{host}:{port}", "HTTP响应异常"
                    
            except socket.timeout:
                sock.close()
                return False, f"{host}:{port}", "连接超时"
            except Exception as e:
                sock.close()
                return False, f"{host}:{port}", f"连接错误: {str(e)}"
                
        except ValueError as e:
            return False, proxy_info.strip(), f"格式错误: {str(e)}"
        except Exception as e:
            return False, proxy_info.strip(), f"未知错误: {str(e)}"

def load_proxy_list(filename):
    """从文件加载代理列表"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        return proxies
    except FileNotFoundError:
        print(f"错误: 文件 '{filename}' 不存在")
        sys.exit(1)
    except Exception as e:
        print(f"错误: 读取文件失败 - {str(e)}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='SOCKS5代理验证工具')
    parser.add_argument('-l', '--list', required=True, help='代理列表文件路径')
    parser.add_argument('-t', '--timeout', type=int, default=10, help='连接超时时间(秒), 默认10秒')
    parser.add_argument('-w', '--workers', type=int, default=20, help='并发线程数, 默认20')
    parser.add_argument('-o', '--output', default='cgdl.txt', help='输出有效代理到文件, 默认为cgdl.txt')
    parser.add_argument('-v', '--verbose', action='store_true', help='显示详细信息')
    
    args = parser.parse_args()
    
    # 加载代理列表
    print(f"正在加载代理列表: {args.list}")
    proxy_list = load_proxy_list(args.list)
    print(f"加载了 {len(proxy_list)} 个代理")
    
    # 创建验证器
    validator = SOCKS5Validator(timeout=args.timeout)
    
    # 统计变量
    valid_proxies = []
    invalid_proxies = []
    start_time = time.time()
    
    print(f"开始验证代理 (超时: {args.timeout}秒, 并发: {args.workers})")
    print("-" * 60)
    
    # 使用线程池并发验证
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_proxy = {
            executor.submit(validator.validate_proxy, proxy): proxy 
            for proxy in proxy_list
        }
        
        # 处理完成的任务
        for i, future in enumerate(as_completed(future_to_proxy), 1):
            proxy = future_to_proxy[future]
            try:
                is_valid, proxy_addr, message = future.result()
                
                if is_valid:
                    valid_proxies.append(proxy)
                    status = "✓ 有效"
                    print(f"[{i:3d}/{len(proxy_list)}] {proxy_addr:<25} {status}")
                else:
                    invalid_proxies.append((proxy, message))
                    if args.verbose:
                        status = f"✗ 无效 ({message})"
                        print(f"[{i:3d}/{len(proxy_list)}] {proxy_addr:<25} {status}")
                        
            except Exception as e:
                invalid_proxies.append((proxy, f"验证异常: {str(e)}"))
                if args.verbose:
                    print(f"[{i:3d}/{len(proxy_list)}] {proxy:<25} ✗ 验证异常: {str(e)}")
    
    # 计算统计信息
    end_time = time.time()
    elapsed_time = end_time - start_time
    success_rate = (len(valid_proxies) / len(proxy_list)) * 100 if proxy_list else 0
    
    print("-" * 60)
    print(f"验证完成!")
    print(f"总代理数: {len(proxy_list)}")
    print(f"有效代理: {len(valid_proxies)}")
    print(f"无效代理: {len(invalid_proxies)}")
    print(f"成功率: {success_rate:.1f}%")
    print(f"耗时: {elapsed_time:.1f}秒")
    
    # 输出有效代理到文件
    if valid_proxies:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                for proxy in valid_proxies:
                    f.write(proxy + '\n')
            print(f"有效代理已保存到: {args.output}")
        except Exception as e:
            print(f"保存文件失败: {str(e)}")
    else:
        print("没有找到有效代理，未创建输出文件")
    
    # 显示无效代理详情
    if args.verbose and invalid_proxies:
        print("\n无效代理详情:")
        print("-" * 60)
        for proxy, reason in invalid_proxies:
            print(f"{proxy:<30} - {reason}")

if __name__ == "__main__":
    main()