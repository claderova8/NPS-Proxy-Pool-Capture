#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
from colorama import Fore, Style, init

init(autoreset=True)

# 配置路径与输出路径
CONFIG_PATH = '/etc/proxychains.conf'
BACKUP_PATH = CONFIG_PATH + '.bak'
OUTPUT_FILE = 'cs.txt'

# 匹配 proxy 行（以 socks4/5 或 http 开头）
PROXY_PATTERN = re.compile(r'^\s*(socks4|socks5|http)\s+.+', re.IGNORECASE)

def backup_file():
    try:
        shutil.copy(CONFIG_PATH, BACKUP_PATH)
        print(Fore.YELLOW + f"[备份] 已备份配置到 {BACKUP_PATH}")
    except Exception as e:
        print(Fore.RED + f"[错误] 备份失败: {e}")
        exit(1)

def extract_and_clear():
    try:
        with open(CONFIG_PATH, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(Fore.RED + f"[错误] 找不到配置文件: {CONFIG_PATH}")
        return
    except PermissionError:
        print(Fore.RED + f"[错误] 权限不足，请使用 sudo 运行")
        return

    proxy_lines = []
    retained_lines = []

    for line in lines:
        if PROXY_PATTERN.match(line):
            proxy_lines.append(line.strip() + '\n')  # 去除多余空格
        else:
            retained_lines.append(line)

    if not proxy_lines:
        print(Fore.CYAN + "[信息] 未找到任何代理配置")
        return

    try:
        with open(OUTPUT_FILE, 'w') as f:
            f.writelines(proxy_lines)
        print(Fore.GREEN + f"[成功] 已保存 {len(proxy_lines)} 条代理到 {OUTPUT_FILE}")
    except Exception as e:
        print(Fore.RED + f"[错误] 写入 {OUTPUT_FILE} 失败: {e}")
        return

    try:
        with open(CONFIG_PATH, 'w') as f:
            f.writelines(retained_lines)
        print(Fore.GREEN + f"[成功] 已清除 {CONFIG_PATH} 中的代理配置")
    except Exception as e:
        print(Fore.RED + f"[错误] 写入配置文件失败: {e}")

if __name__ == '__main__':
    print(Style.BRIGHT + Fore.BLUE + "[开始] 提取并清除 proxychains 配置中的代理...")
    backup_file()
    extract_and_clear()
