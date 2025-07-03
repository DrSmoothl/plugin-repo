# 麦麦闭嘴（静音模式）插件 (silent_mode_plugin)

通过关键字 **麦麦闭嘴** 让 MaiBot 在群聊中进入静音模式，使用 **麦麦张嘴** 解除静音。
![image](https://github.com/user-attachments/assets/ca95d421-0013-4f96-a70f-4b9727be410f)
![402c06a068b300efaa39a0fb15eef211](https://github.com/user-attachments/assets/2c04d6ff-b8f6-433b-a311-0c26c16a0196)

> This plugin mutes MaiBot in group chats when someone says "麦麦闭嘴" (shut up) and unmutes it when "麦麦张嘴" (open mouth) is detected. All behaviors can be customized in `config.toml`.

## 功能特性 / Features

- 一键静音 / 解除静音（Quick mute & un-mute）
- 支持自定义静音时长、触发 / 解除关键词（Customizable keywords & duration）
- 支持白名单 / 黑名单控制指令权限（Whitelist / blacklist for permitted users）
- 静音期间完全屏蔽机器人回复，且可配置是否允许 @Bot 打断（Block replies while muted, with optional @Bot override）
- 实时热重载 `config.toml`（Hot-reload configuration without restart）

## 安装与使用 / Installation

1. Clone or download this repository.
2. Ensure the directory structure as follows:
   ```
   silent_mode_plugin/
     ├── __init__.py
     ├── plugin.py
     ├── config.toml
   
   ```
3. Place the folder `silent_mode_plugin` in your MaiBot `plugins` directory, or include it in `PYTHONPATH`.
4. Start MaiBot.
5. Send **麦麦闭嘴** to mute and **麦麦张嘴** to unmute.

### 配置示例 / Example `config.toml`

```toml
[plugin]
enabled = true
config_version = "1.0.2"

[silent]
duration_seconds = 600
shutup_keywords = ["麦麦闭嘴"]
open_mouth_keywords = ["麦麦张嘴"]
enable_open_mouth = true
at_mention_break = true
suppress_memory_logs = true

[user_control]
list_type = "blacklist"
list = []
```

##免责声明

本插件AI全权开发，本人无知识储备

## 开源协议 / License

本项目基于 **GNU Affero General Public License v3.0** (AGPL-3.0) 开源发布。详细条款请见 `LICENSE` 文件。 
