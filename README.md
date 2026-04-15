# Server Monitor

轻量级服务器监控程序，CPU/内存/磁盘/带宽超限时发送 Telegram 告警。

- 零第三方依赖（纯 Python 3 标准库）
- 内存占用 < 15 MB，CPU 空转 < 0.1%
- 支持告警冷却，防止消息轰炸
- 连续 N 次超阈值才告警，过滤瞬时抖动

---

## 目录

- [效果预览](#效果预览)
- [部署步骤](#部署步骤)
- [配置说明](#配置说明)
- [常用命令](#常用命令)
- [手动运行](#手动运行)
- [常见问题](#常见问题)

---

## 效果预览

触发告警时，Telegram 收到如下消息：

```
🔴 [my-server] HIGH CPU
Usage: 92.3% (threshold 85%, 3 consecutive checks)

🔴 [my-server] HIGH MEMORY
Usage: 91.5% (7640 MB / 8192 MB)
Threshold: 90%

🔴 [my-server] HIGH DISK (/)
Usage: 93.0% (186 GB / 200 GB)
Threshold: 90%

🔴 [my-server] BANDWIDTH SATURATION (eth0)
Usage: 94.2% of 100 Mbps
RX: 11.7 MB/s  TX: 0.3 MB/s
Saturated direction: RX (3 consecutive checks)
```

---

## 部署步骤

### 第一步：获取 Telegram Bot Token 和 Chat ID

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)，发送 `/newbot` 创建机器人，获得 `bot_token`。
2. 获取 `chat_id`：
   - 个人聊天：找 [@userinfobot](https://t.me/userinfobot)，发送任意消息，它会返回你的 ID。
   - 群组/频道：将机器人加入群组后，浏览器访问：
     ```
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
     ```
     在返回的 JSON 中找 `"chat":{"id": -100xxxxxxxxxx}` 即为群组 ID（负数）。

---

### 第二步：填写配置文件

编辑 `config.json`，至少填写 `bot_token` 和 `chat_id`：

```json
{
    "telegram": {
        "bot_token": "123456789:ABCdefGHI...",
        "chat_id": "-1001234567890"
    },
    "interval": 30,
    "thresholds": {
        "cpu_percent": 85,
        "cpu_consecutive": 3,
        "mem_percent": 90,
        "disk_percent": 90,
        "disk_paths": ["/", "/data"],
        "net_interface": "eth0",
        "net_max_mbps": 100,
        "net_percent": 90,
        "net_consecutive": 3
    },
    "cooldown": 1800
}
```

> **注意**：`net_interface` 填你服务器实际的网卡名。用 `ip link` 查看，常见的有 `eth0`、`ens3`、`ens18`、`enp1s0` 等。

---

### 第三步：一键安装

```bash
# 在项目目录下执行
sudo bash install.sh
```

脚本会自动完成：

- 将 `monitor.py` 复制到 `/opt/monitor/`
- 将 `config.json` 复制到 `/etc/monitor/`（已存在则跳过）
- 注册并启动 `server-monitor` systemd 服务
- 设置开机自启

---

## 配置说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `telegram.bot_token` | — | BotFather 给出的 Token |
| `telegram.chat_id` | — | 接收告警的聊天/群组 ID |
| `interval` | `30` | 每轮检测的间隔秒数 |
| `cpu_percent` | `85` | CPU 使用率告警阈值（%） |
| `cpu_consecutive` | `3` | 连续超阈值多少次后才发送告警 |
| `mem_percent` | `90` | 内存使用率告警阈值（%） |
| `disk_percent` | `90` | 磁盘使用率告警阈值（%） |
| `disk_paths` | `["/"]` | 需要监控的磁盘挂载点列表 |
| `net_interface` | `"eth0"` | 监控的网卡名 |
| `net_max_mbps` | `100` | 该网卡的带宽上限（Mbps） |
| `net_percent` | `90` | 带宽使用率告警阈值（%） |
| `net_consecutive` | `3` | 连续超阈值多少次后才发送告警 |
| `cooldown` | `1800` | 同一告警的冷却时间（秒），防止重复发送 |

### 参数调优建议

- **`interval`**：设为 `10`–`30` 秒。越小越灵敏，但会略微增加 CPU 占用。
- **`cpu_consecutive`**：设为 `3` 意味着 CPU 需持续高负载 `interval × 3` 秒才告警，可过滤编译、备份等短暂峰值。
- **`cooldown`**：默认 30 分钟。若磁盘已满且无法立即处理，可适当调大避免刷屏；若需要持续提醒，可调小。
- **`net_max_mbps`**：填写购买的带宽套餐值，而非理论最大值。例如购买了 100 Mbps 则填 `100`。

---

## 常用命令

```bash
# 查看实时日志
journalctl -fu server-monitor

# 查看服务状态
systemctl status server-monitor

# 修改配置后重启
sudo systemctl restart server-monitor

# 停止监控
sudo systemctl stop server-monitor

# 禁用开机自启
sudo systemctl disable server-monitor
```

---

## 手动运行

不想使用 systemd，也可以直接运行：

```bash
# 使用默认配置路径 /etc/monitor/config.json
python3 monitor.py

# 指定配置文件路径
MONITOR_CONFIG=/path/to/config.json python3 monitor.py

# 后台运行并记录日志
nohup python3 monitor.py >> /var/log/monitor.log 2>&1 &
```

---

## 常见问题

**Q：告警发不出去，日志显示 `Telegram not configured`**

检查 `config.json` 中 `bot_token` 和 `chat_id` 是否已填写（不能是默认的 `YOUR_BOT_TOKEN`）。

---

**Q：告警发不出去，日志显示 `Telegram send failed`**

1. 确认服务器能访问外网：`curl https://api.telegram.org`
2. 确认 bot_token 正确，且机器人已被加入目标群组并有发消息权限。
3. 如服务器在中国大陆，需为 Python 配置代理：在 `monitor.py` 顶部添加：
   ```python
   import os
   os.environ["https_proxy"] = "http://127.0.0.1:7890"  # 替换为你的代理地址
   ```

---

**Q：网络带宽告警不准**

1. 用 `ip link` 确认网卡名，填入 `net_interface`。
2. 将 `net_max_mbps` 设置为你实际购买的带宽值（Mbps）。
3. 如果是国内服务器，带宽峰值和标称值可能有差距，可适当下调 `net_max_mbps`。

---

**Q：想监控多块磁盘**

在 `disk_paths` 中添加挂载点：

```json
"disk_paths": ["/", "/data", "/backup"]
```

---

**Q：修改配置后何时生效？**

配置文件在程序**启动时**读取一次。修改后需重启服务：

```bash
sudo systemctl restart server-monitor
```

---

## 系统要求

- Linux（依赖 `/proc/stat`、`/proc/meminfo`、`/proc/net/dev`）
- Python 3.6+
- systemd（仅安装为服务时需要）
