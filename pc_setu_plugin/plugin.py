import os
import base64
import random
from typing import List, Tuple, Type
from pathlib import Path
from io import BytesIO
from PIL import Image
from src.common.logger import get_logger
from src.plugin_system import (
    BasePlugin, register_plugin, BaseAction,
    ComponentInfo, ActionActivationType, ChatMode
)
from src.plugin_system.base.config_types import ConfigField

logger = get_logger("pc_setu_action")


@register_plugin
class PCSetuPlugin(BasePlugin):
    """本地图片随机发送插件
    - 从指定文件夹随机获取图片
    - 图片压缩功能
    - 完整的错误处理
    """

    plugin_name = "pc_setu_plugin"
    plugin_description = "从本地文件夹随机发送图片"
    plugin_version = "1.0.0"
    plugin_author = "fzjyp"
    enable_plugin = True
    config_file_name = "config.toml"

    # 必需的依赖声明
    dependencies: List[str] = []
    python_dependencies: List[str] = ["Pillow"]

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "components": "组件启用控制",
        "image": "图片相关配置",
        "logging": "日志记录配置",
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="插件配置文件版本号"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        "components": {
            "enable_pc_setu": ConfigField(type=bool, default=True, description="是否启用图片发送功能"),
        },
        "image": {
            "source_dir": ConfigField(type=str, default=r"D:\pic", description="图片源文件夹路径"),
            "max_image_size": ConfigField(type=int, default=1048576, description="图片最大字节数(默认1MB)"),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[LocalImage]", description="日志前缀"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        components = []
        if self.get_config("components.enable_pc_setu", True):
            components.append((PCSetuAction.get_action_info(), PCSetuAction))
        return components


class PCSetuAction(BaseAction):
    """从本地文件夹随机发送图片"""

    focus_activation_type = ActionActivationType.KEYWORD
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = False

    action_name = "pc_setu"
    action_description = "从本地文件夹随机发送图片"
    activation_keywords = ["来张图片", "发张图", "来一张", "随机图片", "色图"]
    keyword_case_sensitive = False

    action_parameters = {}  # 不再需要关键词参数

    action_require = ["需要发送随机图片的场景", "当有人要求你发图片时调用", "当有人要求你或者@你发图片时调用"]
    associated_types = ["image"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 获取配置
        cfg = getattr(self, "global_config", None) or kwargs.get("global_config", {}) or {}
        image_cfg = cfg.get("image", {})

        # 图片源文件夹
        self.source_dir = Path(image_cfg.get("source_dir", r"D:\pic"))
        # 最大图片大小
        self.max_image_size = image_cfg.get("max_image_size", 1048576)

        # 检查文件夹是否存在
        if not self.source_dir.exists():
            logger.warning(f"图片文件夹不存在: {self.source_dir}")

    def get_random_image(self) -> Path:
        """从文件夹中随机获取一张PNG图片"""
        if not self.source_dir.exists():
            raise FileNotFoundError(f"图片文件夹不存在: {self.source_dir}")

            # 支持多种图片格式
        image_files = []
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"]:
            image_files.extend(self.source_dir.glob(ext))

        if not image_files:
            raise FileNotFoundError(f"文件夹中没有图片: {self.source_dir}")

        return random.choice(image_files)

    async def compress_image(self, img_bytes: bytes, max_size: int = None) -> bytes:
        """压缩图片到指定大小以内"""
        if max_size is None:
            max_size = self.max_image_size

        try:
            img = Image.open(BytesIO(img_bytes))
            img_format = img.format if img.format else "PNG"
            quality = 90
            step = 5
            buffer = BytesIO()

            # 先尝试原尺寸压缩
            while True:
                buffer.seek(0)
                buffer.truncate()
                img.save(buffer, format=img_format, quality=quality)
                data = buffer.getvalue()
                if len(data) <= max_size or quality <= 30:
                    break
                quality -= step

            # 如果还超限，缩放分辨率
            while len(data) > max_size and (img.width > 300 or img.height > 300):
                new_width = int(img.width * 0.85)
                new_height = int(img.height * 0.85)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                buffer.seek(0)
                buffer.truncate()
                img.save(buffer, format=img_format, quality=quality)
                data = buffer.getvalue()

            return data
        except Exception as e:
            logger.error(f"图片压缩失败: {e}")
            return img_bytes

    async def execute(self) -> Tuple[bool, str]:
        try:
            logger.info("请求随机本地图片")

            # 随机获取图片文件
            image_path = self.get_random_image()
            logger.info(f"选中图片: {image_path.name}")

            # 读取图片
            with open(image_path, "rb") as f:
                img_bytes = f.read()

            # 压缩图片
            img_bytes = await self.compress_image(img_bytes, self.max_image_size)
            base64_image = base64.b64encode(img_bytes).decode("utf-8")

            # 发送图片
            # await self.send_text(f"📸 来了来了~ ({image_path.name})")
            await self.send_image(base64_image)

            return True, "发送了随机图片"

        except FileNotFoundError as e:
            logger.error(f"文件夹错误: {e}")
            return False, f"图片文件夹配置错误: {str(e)}"
        except Exception as e:
            logger.error(f"发送图片失败: {e}", exc_info=True)
            return False, "发送图片失败，请稍后再试"
