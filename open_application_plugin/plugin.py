"""
打开应用插件 - 终极版
功能：通过用户指令打开电脑中的应用软件
使用原生Windows API直接启动应用，避免start命令问题
"""

import platform
import subprocess
import logging
import sys
import locale
import os
import winreg
import glob
import ctypes
from typing import List, Tuple, Type, Optional

# 强制设置系统默认编码为UTF-8
if sys.version_info >= (3, 7):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
else:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

# 设置locale为UTF-8
try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
    except:
        pass

# 导入新插件系统
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.base_plugin import register_plugin
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ActionActivationType, ChatMode
from src.common.logger import get_logger

# 获取日志记录器
logger = get_logger("open_app_plugin")

class WindowsAppLauncher:
    """Windows 应用启动工具类，使用原生API"""

    @staticmethod
    def get_desktop_path() -> str:
        """获取桌面路径"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                desktop_path, _ = winreg.QueryValueEx(key, "Desktop")
                if "%" in desktop_path:
                    for env_var in ["USERPROFILE", "HOMEPATH"]:
                        if env_var in os.environ:
                            desktop_path = desktop_path.replace(f"%{env_var}%", os.environ[env_var])
                return os.path.expandvars(desktop_path)
        except Exception:
            return os.path.join(os.path.expanduser("~"), "Desktop")

    @staticmethod
    def find_application(app_name: str) -> Optional[str]:
        """查找应用程序的完整路径（大小写不敏感）"""
        # 1. 检查桌面快捷方式
        desktop_path = WindowsAppLauncher.get_desktop_path()
        for ext in ["*.lnk", "*.url", "*.exe"]:
            for file_path in glob.glob(os.path.join(desktop_path, ext), recursive=False):
                base_name = os.path.splitext(os.path.basename(file_path))[0].lower()
                if app_name.lower() in base_name:
                    return file_path

        # 2. 检查开始菜单
        start_menu_paths = [
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        ]

        for start_path in start_menu_paths:
            if os.path.exists(start_path):
                for root, _, files in os.walk(start_path):
                    for file in files:
                        if file.lower().endswith(('.lnk', '.exe')):
                            base_name = os.path.splitext(file)[0].lower()
                            if app_name.lower() in base_name:
                                return os.path.join(root, file)

        # 3. 检查程序文件目录
        program_dirs = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", "")
        ]

        for dir_path in program_dirs:
            if os.path.exists(dir_path):
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.lower().endswith('.exe'):
                            base_name = os.path.splitext(file)[0].lower()
                            if app_name.lower() in base_name:
                                return os.path.join(root, file)

        # 4. 检查系统路径
        system_path = os.environ.get("PATH", "")
        for path_dir in system_path.split(os.pathsep):
            if os.path.exists(path_dir):
                for file in os.listdir(path_dir):
                    if file.lower().endswith('.exe'):
                        base_name = os.path.splitext(file)[0].lower()
                        if app_name.lower() in base_name:
                            return os.path.join(path_dir, file)

        return None

    @staticmethod
    def launch_app(full_path: str) -> bool:
        """使用ShellExecuteW直接启动应用（原生Windows API）"""
        try:
            # 使用ShellExecuteW处理各种文件类型
            shell32 = ctypes.windll.shell32

            # 转换路径为宽字符（支持Unicode）
            full_path_w = ctypes.create_unicode_buffer(full_path)

            # SW_SHOW = 5, 正常显示窗口
            result = shell32.ShellExecuteW(
                None,           # 父窗口句柄
                "open",         # 操作类型
                full_path_w,    # 文件路径
                None,           # 参数
                None,           # 工作目录
                5               # 显示方式
            )

            # 返回值大于32表示成功
            return result > 32
        except Exception as e:
            logger.error(f"ShellExecuteW 调用失败: {str(e)}")
            return False

class OpenAppAction(BaseAction):
    """打开应用Action - 基于关键词触发打开应用"""

    # ===== 激活控制必须项 =====
    focus_activation_type = ActionActivationType.KEYWORD
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = True

    # ===== 基本信息必须项 =====
    action_name = "open_app_action"
    action_description = "打开指定应用软件"

    # 关键词配置
    activation_keywords = ["打开", "启动", "run", "open"]
    keyword_case_sensitive = False

    # ===== 功能定义必须项 =====
    action_parameters = {
        "app_name": "要打开的应用程序名称"
    }

    action_require = [
        "用户明确要求打开特定应用时使用",
        "应用名称在允许打开的名单中",
        "应用不在禁止打开的名单中"
    ]

    associated_types = ["text", "command"]

    async def execute(self) -> Tuple[bool, str]:
        """执行打开应用操作"""
        app_name = self.action_data.get("app_name", "")

        if not app_name:
            logger.warning(f"{self.log_prefix} 未指定应用名称")
            return False, "未指定应用名称"

        # 检查应用是否允许打开
        if not self._is_app_allowed(app_name):
            logger.warning(f"{self.log_prefix} 应用不在允许名单中: {app_name}")
            await self.send_text(f"⚠️ 无法打开 {app_name}，该应用不在允许名单中")
            return False, f"应用不在允许名单中: {app_name}"

        # 执行打开操作
        success, message, full_path = self._open_application(app_name)

        if success:
            logger.info(f"{self.log_prefix} 成功打开应用: {app_name} (路径: {full_path})")
            await self.send_text(f"✅ 已启动应用: {app_name}")
            return True, f"成功打开 {app_name}"
        else:
            logger.error(f"{self.log_prefix} 打开应用失败: {app_name} - {message}")
            await self.send_text(f"❌ 打开应用失败: {app_name}\n错误: {message}")
            return False, f"打开失败: {message}"

    def _is_app_allowed(self, app_name: str) -> bool:
        """检查应用是否在允许打开的名单中"""
        list_type = self.api.get_config("open_app.list_type", "black")
        app_list = self.api.get_config("open_app.app_list", [])

        if list_type == "black":
            # 黑名单模式 - 不在黑名单中即可打开
            return app_name.lower() not in [a.lower() for a in app_list]
        else:
            # 白名单模式 - 必须在白名单中才能打开
            return app_name.lower() in [a.lower() for a in app_list]

    def _open_application(self, app_name: str) -> Tuple[bool, str, Optional[str]]:
        """打开应用程序（跨平台实现），返回 (成功状态, 消息, 完整路径)"""
        system = platform.system()

        # Windows平台使用原生API启动
        if system == "Windows":
            full_path = WindowsAppLauncher.find_application(app_name)
            if not full_path:
                return False, f"未找到应用程序: {app_name}", None

            try:
                # 使用原生Windows API启动应用
                success = WindowsAppLauncher.launch_app(full_path)
                if success:
                    return True, "应用已启动", full_path
                else:
                    # 原生API失败时回退到subprocess
                    try:
                        # 直接使用完整路径启动
                        subprocess.Popen(full_path, shell=True)
                        return True, "应用已启动", full_path
                    except Exception as e2:
                        return False, f"无法打开应用: {str(e2)}", full_path
            except Exception as e:
                return False, f"启动失败: {str(e)}", full_path

        # 其他平台处理
        try:
            if system == "Darwin":
                # macOS系统
                subprocess.Popen(["open", "-a", app_name])
                return True, "应用已启动", app_name

            elif system == "Linux":
                # Linux系统
                subprocess.Popen([app_name])
                return True, "应用已启动", app_name

            else:
                return False, f"不支持的操作系统: {system}", None

        except Exception as e:
            return False, str(e), None

class OpenAppCommand(BaseCommand):
    """打开应用Command - 通过命令打开应用"""

    command_pattern = r"^/open\s+(?P<app_name>.+)$"
    command_help = "打开指定应用程序，用法：/open <应用名称>"
    command_examples = ["/open notepad", "/open 计算器"]
    intercept_message = True

    async def execute(self) -> Tuple[bool, Optional[str]]:
        """执行打开应用命令"""
        app_name = self.matched_groups.get("app_name", "")

        if not app_name:
            await self.send_text("❌ 请指定要打开的应用程序名称\n用法：/open <应用名称>")
            return False, "未指定应用名称"

        # 检查应用是否允许打开
        if not self._is_app_allowed(app_name):
            await self.send_text(f"⚠️ 无法打开 {app_name}，该应用不在允许名单中")
            return False, f"应用不在允许名单中: {app_name}"

        # 执行打开操作
        success, message, _ = self._open_application(app_name)

        if success:
            await self.send_text(f"✅ 已启动应用: {app_name}")
            return True, f"成功打开 {app_name}"
        else:
            await self.send_text(f"❌ 打开应用失败: {app_name}\n错误: {message}")
            return False, f"打开失败: {message}"

    def _is_app_allowed(self, app_name: str) -> bool:
        """检查应用是否在允许打开的名单中"""
        list_type = self.api.get_config("open_app.list_type", "black")
        app_list = self.api.get_config("open_app.app_list", [])

        if list_type == "black":
            # 黑名单模式 - 不在黑名单中即可打开
            return app_name.lower() not in [a.lower() for a in app_list]
        else:
            # 白名单模式 - 必须在白名单中才能打开
            return app_name.lower() in [a.lower() for a in app_list]

    def _open_application(self, app_name: str) -> Tuple[bool, str, Optional[str]]:
        """打开应用程序（跨平台实现），返回 (成功状态, 消息, 完整路径)"""
        system = platform.system()

        # Windows平台使用原生API启动
        if system == "Windows":
            full_path = WindowsAppLauncher.find_application(app_name)
            if not full_path:
                return False, f"未找到应用程序: {app_name}", None

            try:
                # 使用原生Windows API启动应用
                success = WindowsAppLauncher.launch_app(full_path)
                if success:
                    return True, "应用已启动", full_path
                else:
                    # 原生API失败时回退到subprocess
                    try:
                        # 直接使用完整路径启动
                        subprocess.Popen(full_path, shell=True)
                        return True, "应用已启动", full_path
                    except Exception as e2:
                        return False, f"无法打开应用: {str(e2)}", full_path
            except Exception as e:
                return False, f"启动失败: {str(e)}", full_path

        # 其他平台处理
        try:
            if system == "Darwin":
                # macOS系统
                subprocess.Popen(["open", "-a", app_name])
                return True, "应用已启动", app_name

            elif system == "Linux":
                # Linux系统
                subprocess.Popen([app_name])
                return True, "应用已启动", app_name

            else:
                return False, f"不支持的操作系统: {system}", None

        except Exception as e:
            return False, str(e), None

@register_plugin
class OpenApplicationPlugin(BasePlugin):
    """打开应用插件主类"""

    plugin_name = "open_application_plugin"
    plugin_description = "通过用户指令打开电脑中的应用软件"
    plugin_version = "1.0.0"
    plugin_author = "LMSS_AIOS"
    enable_plugin = True
    config_file_name = "config.toml"

    config_section_descriptions = {
        "plugin": "插件基本信息配置",
        "components": "组件启用控制",
        "open_app": "应用打开配置",
        "logging": "日志记录配置"
    }

    def __init__(self, *args, **kwargs):
        """初始化插件，接受并传递所有参数"""
        super().__init__(*args, **kwargs)
        self.enable_open_action = True  # 默认值
        self.enable_open_command = True  # 默认值

    async def initialize(self):
        """初始化插件，此时api已可用"""
        await super().initialize()

        # 在初始化阶段获取配置
        self.enable_open_action = self.api.get_config("components.enable_open_action", True)
        self.enable_open_command = self.api.get_config("components.enable_open_command", True)

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        components = []

        # 使用初始化阶段设置的配置值
        if self.enable_open_action:
            components.append((
                OpenAppAction.get_action_info(),
                OpenAppAction
            ))

        if self.enable_open_command:
            components.append((
                OpenAppCommand.get_command_info(
                    name="open_app_command",
                    description="打开指定应用程序"
                ),
                OpenAppCommand
            ))

        return components
