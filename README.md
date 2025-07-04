# 麦麦闭嘴（Silent Mode）插件  

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)  

让 **MaiBot** 在群聊中暂时"闭嘴"。发送关键词 **麦麦闭嘴** 进入静音，发送 **麦麦张嘴** 解除静音。

+![静音触发示例](https://github.com/user-attachments/assets/ca95d421-0013-4f96-a70f-4b9727be410f)
+![静音中提示](https://github.com/user-attachments/assets/2c04d6ff-b8f6-433b-a311-0c26c16a0196)

---

## 目录 (Table of Contents)

1. [功能特性](#功能特性--features)  
2. [安装与使用](#安装与使用--installation)  
3. [配置](#配置)  
4. [License](#开源协议--license)

## 功能特性 / Features

- 一键静音 / 解除静音（Quick mute & un‐mute）
- 支持自定义静音时长、触发 / 解除关键词（Customizable keywords & duration）
- 支持白名单 / 黑名单控制指令权限（Whitelist / blacklist）
- 静音期间完全屏蔽机器人回复，且可配置是否允许 @Bot 打断（Optional @Bot override）
- 实时热重载 `config.toml`（Hot‐reload configuration）

## 安装与使用 / Installation

1. 下载或克隆本仓库。  
2. 将 `silent_mode_plugin/` 文件夹放入 MaiBot 的 `plugins` 目录 (或将其路径加入 `PYTHONPATH`)。  
3. 重启/热加载插件后，在群聊发送 **麦麦闭嘴** → 进入静音；发送 **麦麦张嘴** → 解除。

## 配置

`config.toml` 支持以下字段（示例取默认值）：

```toml
[plugin]
enabled = true              # 是否启用插件
config_version = "1.0.5"

[silent]
duration_seconds   = 600     # 静音时长（秒）
shutup_keywords     = ["麦麦闭嘴"]
open_mouth_keywords = ["麦麦张嘴"]
enable_open_mouth  = true    # 是否启用解除关键词
at_mention_break   = true    # @机器人时是否打断静音
suppress_memory_logs = true  # 静音时隐藏 memory 日志
show_summary_log   = true    # 是否输出静音剩余时间提醒日志
suppress_chat_logs = true    # 静音时是否屏蔽后台 chat/normal_chat 消息日志

[user_control]
list_type = "blacklist"     # "whitelist" / "blacklist"
list = []                    # QQ 号列表
```

编辑配置后 **无需重启**，插件会在后台自动检测变更并热更新。

## 开源协议 / License

Released under the **GNU Affero General Public License v3.0** (AGPL-3.0). See [`LICENSE`](LICENSE) for details.
