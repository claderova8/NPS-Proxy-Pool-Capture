# NPS Proxy 弱口令检测与数据获取工具
这是一个用于检测 NPS Proxy 管理界面弱口令，并在成功登录后可选地获取客户端和隧道（端口管理）数据的 Python 工具。此外，它还提供了一个离线功能，用于格式化特定分组格式的隧道账号密码数据。

## 功能特性
- ⚪弱口令检测: 支持对单个目标或从文件中读取的目标列表进行弱口令检测。
- ⚪多线程: 支持指定并发线程数，提高检测效率。
- ⚪自定义密码字典: 可以指定自定义密码文件，或使用内置的常用弱口令列表。
- ⚪网络错误处理: 设置最大网络错误或超时次数，避免对不稳定目标的长时间尝试。
- ⚪数据获取 (可选): 成功登录后，可以尝试获取 NPS 客户端列表和隧道列表数据。
- ⚪数据保存 (可选): 将成功登录的账号密码保存到文件，并将获取到的客户端数据保存为 JSON 文件，隧道数据聚合保存为特定格式的文本文件。
- ⚪离线格式化功能: 支持将特定分组格式的隧道账号密码数据（一个隧道信息后跟多个账号密码）格式化为每行一个隧道+账号密码的标准格式。

## 特性

- 🎯 自动抓取高可用 HTTP/HTTPS 代理  
- 🔓 弱口令检测 (HTTP Basic / Digest)  
- 🧩 通过本地 SOCKS5 隧道抓取目标站点  
- 🚀 支持多线程并发  

## 目录

- [安装](#安装)   
- [使用示例](#使用示例)
- [文件架构](#文件架构)  
- [功能演示](#功能演示)  
  - [弱口令检测](#弱口令检测)  
  - [SOCKS5 隧道抓取](#socks5-隧道抓取)   
- [许可](#许可)  

## 安装

```bash
git clone https://github.com/claderova8/nps-proxy-pool.git
cd nps-proxy-pool
pip install requests tqdm
```
## 使用示例
```bash
基本用法示例：
python main.py [目标指定参数] [弱口令检测参数] [数据获取/保存参数] [输出控制参数]
python main.py -l targets.txt                            #获取目标文件
python main.py -H 192.168.1.100:8080                     #获取单个目标
python main.py -G grouped_tunnels_input.txt              #指定包含分组隧道数据的文件（一个隧道信息后跟多个账号密码）。启用此模式时，将忽略其他弱口令检测和数据获取参数，只进行离线格式化
python main.py -H 192.168.1.100:8080 -u administrator    #指定用户名
python main.py -l targets.txt -t 50                      #设置线程
python main.py -H 192.168.1.100:8080 -d 0.5              #密码重试延迟，默认0.1秒
python main.py -l targets.txt -m 5                       #重连次数，默认2次
python main.py -H 192.168.1.100:8080 -C                  #服务端数据
python main.py -H 192.168.1.100:8080 -T                  #隧道信息
python main.py -l targets.txt -C -T -S                   #保存获取到的数据。客户端数据保存为 .json，隧道数据聚合保存到 tunnels.txt。
```
## 文件结构
```bash
  main.py: 程序主入口，负责参数解析、模式判断和任务调度。
  nps_args.py: 负责命令行参数的定义和解析，以及目标和密码文件的加载。
  nps_auth.py: 处理 NPS 登录认证相关的网络请求和响应判断。
  nps_constants.py: 存放程序中使用的各种常量，如默认密码、API 路径等。
  nps_core.py: 包含对单个目标进行弱口令尝试和数据获取的核心逻辑。
  nps_data.py: 负责在成功登录后获取客户端和隧道数据，以及处理特定格式的隧道数据格式化。
```
## 功能演示
### 弱口令检测
![image](https://github.com/user-attachments/assets/2f525fdc-9863-4b8b-9e96-9f819382e1fc)

### socks5隧道抓取
![image](https://github.com/user-attachments/assets/af9f884f-6852-4747-9d5f-e023970e1c6f)

