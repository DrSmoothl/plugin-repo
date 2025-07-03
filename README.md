# 麦麦 (MaiBot) 插件中心 (MaiBot Plugin Registry)

[![Validate Plugins](https://github.com/MaiM-with-u/plugin-repo/actions/workflows/validate-pr.yml/badge.svg)](https://github.com/MaiM-with-u/plugin-repo/actions/workflows/validate-pr.yml)
[![插件数量](https://img.shields.io/badge/dynamic/json?color=blue&label=plugins&query=%24.length&url=https%3A%2F%2Fraw.githubusercontent.com%2FMaiM-with-u%2Fplugin-repo%2Fmain%2Fplugins.json)](https://github.com/MaiM-with-u/plugin-repo/blob/main/plugins.json)
[![GitHub Pages](https://img.shields.io/badge/插件展示-GitHub%20Pages-blue?logo=github)](https://maim-with-u.github.io/plugin-repo/)

欢迎来到麦麦（MaiBot）官方社区插件索引仓库！

这里是所有为 [麦麦 (MaiBot)](https://github.com/MaiM-with-u) 开发的社区插件的中央列表。我们的目标是建立一个开放、透明、高质量的插件生态系统。

## 🎯 插件展示页面

您可以通过我们的 **[插件展示页面](https://maim-with-u.github.io/plugin-repo/)** 浏览所有可用的插件，该页面提供了：

- 🔍 智能搜索功能
- 🏷️ 标签分类系统
- 📊 插件详细信息
- 🎨 现代化界面设计
- 📱 移动端适配

## ✨ 工作方式

本仓库通过维护一个核心的 `plugins.json` 文件来索引所有社区插件。所有插件本身都以独立的、公开的 GitHub 仓库形式存在。我们通过自动化的工作流来验证每一个提交，确保其符合社区规范。

## 🚀 如何贡献您的插件

我们非常欢迎您为麦麦（MaiBot）生态贡献插件！提交您的插件非常简单，只需向本仓库发起一个 Pull Request (PR) 即可。

请详细阅读我们的 **[贡献指南 (CONTRIBUTING.md)](./CONTRIBUTING.md)**，其中包含了所有您需要了解的步骤和规范。

## ⚖️ 许可证

本仓库本身使用 [MIT License](./LICENSE) 进行许可。所收录的插件使用其各自仓库中指定的许可证。

# Silent Mode 插件 (silent_mode_plugin)

通过关键字 **麦麦闭嘴** 让 MaiBot 在群聊中进入静音模式，使用 **麦麦张嘴** 解除静音。

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
   _manifest.json
   LICENSE
   README.md
   ```
3. Place the folder `silent_mode_plugin` in your MaiBot `plugins` directory, or include it in `PYTHONPATH`.
4. Start MaiBot.
5. Send **麦麦闭嘴** to mute and **麦麦张嘴** to unmute.

## 配置示例 / Example `config.toml`

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

## 开源协议 / License

MIT