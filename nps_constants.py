# -*- coding: utf-8 -*-
# 常量模块 - 存放程序中使用的各种固定值和配置。

# 默认弱口令列表 - 这是一个常用的弱密码集合，用于在没有指定密码文件时进行尝试。
DEFAULT_PASSWORDS = ( # Use tuple for immutable default
    "123", "123456", "password", "admin", "12345678", "qwerty",
    "abc123", "111111", "1234567", "password1", "123123",
    "12345", "123456789", "admin123", "administrator", "test",
    "root", "user", "1111111", "000000", "654321", "abcdef"
)

# 定义优先尝试的密码列表 - 这些密码会在 DEFAULT_PASSWORDS 列表中的其他密码之前尝试。
PRIORITY_PASSWORDS = ("admin", "123") # Use tuple

# NPS API 路径 - NPS Web 界面用于获取客户端和隧道数据的接口路径。
# 根据 NPS 特征修改：获取客户端列表的 API 路径
CLIENT_DATA_PATH = "/client/list" # NPS 客户端列表接口相对路径
# 获取隧道列表的 API 路径
TUNNEL_DATA_PATH = "/index/gettunnel" # NPS 隧道（端口管理）列表接口相对路径

# 聚合保存隧道数据的文件名 - 所有成功获取的隧道数据将汇总到这个文件中。
DEFAULT_AGGREGATED_TUNNELS_FILE = "tunnels.txt"

# 默认成功账号密码输出文件 - 成功登录的账号密码将保存到这个文件中。
DEFAULT_OUTPUT_FILE = "ok.txt"

# 隧道数据分页获取的每页数量 - NPS API 可能对返回的列表数据进行分页，这里定义每页请求的数量。
TUNNEL_PAGE_LIMIT = 50

# Note: Consider adding default timeout values here if used consistently.
# DEFAULT_TIMEOUT = 10
