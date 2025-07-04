from typing import List, Tuple, Type
import time
import asyncio
import sys
import os
import logging  # 新增导入
import re  # 新增导入

from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseAction,
    BaseCommand,
    ComponentInfo,
    ActionActivationType,
    ChatMode,
    ConfigField,
)
from src.common.logger import get_logger
from src.chat.normal_chat.normal_chat import NormalChat  # 新增导入
from src.config.config import global_config  # 引入机器人自身信息

logger = get_logger("silent_mode_plugin")

# Python >=3.11 原生 tomllib；低版本兼容 tomli
try:
    import tomllib as _toml_lib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml_lib  # type: ignore

class SilentStatus:
    """群聊静音状态管理器"""

    _mute_until: dict[str, float] = {}
    _group_names: dict[str, str] = {}  # 记录群ID到群名称的映射
    _original_handlers: dict[str, callable] = {}
    _muted_groups: set = set()  # 存储当前静音的群组
    _patched = False  # 标记是否已应用猴子补丁
    _last_summary_log_time: dict[str, float] = {}  # 群 -> 最近一次摘要输出时间

    @classmethod
    def _key(cls, platform: str, group_id: str) -> str:
        return f"{platform}:{group_id}"

    @classmethod
    def set_mute(cls, platform: str, group_id: str, seconds: int = 600, group_name: str | None = None):
        key = cls._key(platform, group_id)
        cls._mute_until[key] = time.time() + seconds
        cls._muted_groups.add(key)
        if group_name:
            cls._group_names[key] = group_name
            SilentGroupLogFilter.add_group(group_name)
        logger.info(f"[SilentStatus] 群 {platform}:{group_id} 静音 {seconds} 秒")

    @classmethod
    def clear_mute(cls, platform: str, group_id: str):
        key = cls._key(platform, group_id)
        if cls._mute_until.pop(key, None) is not None:
            cls._muted_groups.discard(key)
            # 移除日志过滤
            g_name = cls._group_names.pop(key, None)
            if g_name:
                SilentGroupLogFilter.remove_group(g_name)
            logger.info(f"[SilentStatus] 群 {platform}:{group_id} 解除静音")

    @classmethod
    def is_muted(cls, platform: str, group_id: str) -> bool:
        key = cls._key(platform, group_id)
        # 检查是否过期
        if key in cls._muted_groups:
            if time.time() >= cls._mute_until.get(key, 0):
                # 已过期，自动清理
                cls._muted_groups.discard(key)
                cls._mute_until.pop(key, None)
                # 移除日志过滤
                g_name = cls._group_names.pop(key, None)
                if g_name:
                    SilentGroupLogFilter.remove_group(g_name)
                logger.info(f"[SilentStatus] 群 {platform}:{group_id} 静音时间已到，自动解除")
                return False
            return True
        return False

    @classmethod
    def store_handler(cls, platform: str, group_id: str, handler):
        cls._original_handlers[cls._key(platform, group_id)] = handler

    @classmethod
    def get_handler(cls, platform: str, group_id: str):
        return cls._original_handlers.get(cls._key(platform, group_id))
        
    @classmethod
    def is_patched(cls):
        return cls._patched
        
    @classmethod
    def set_patched(cls, value=True):
        cls._patched = value

    # ===== 摘要日志 =====
    @classmethod
    def log_summary(cls, platform: str, group_id: str):
        """按照一定频率输出静音剩余时间摘要。"""
        if not ENABLE_SUMMARY_LOG:
            return

        key = cls._key(platform, group_id)
        if key not in cls._muted_groups:
            return

        now = time.time()
        last_time = cls._last_summary_log_time.get(key, 0)
        if now - last_time < 5:  # 每群至多5秒打印一次，防止刷屏
            return

        remain = int(cls._mute_until.get(key, 0) - now)
        end_ts = cls._mute_until.get(key, 0)
        end_str = time.strftime("%H:%M:%S", time.localtime(end_ts))

        g_name = cls._group_names.get(key)
        display = g_name if g_name else f"{platform}:{group_id}"
        logger.info(f"[{display}] 群聊静音剩余{remain}秒，结束时间{end_str}")
        cls._last_summary_log_time[key] = now


# ====================== Command Components ======================


class ShutupCommand(BaseCommand):
    """命令：麦麦闭嘴 → 进入静音"""

    command_name = "shutup"
    command_description = "让麦麦闭嘴，进入10分钟静音模式"
    command_pattern = r"^(?:麦麦)?闭嘴$"
    command_examples = ["麦麦闭嘴", "闭嘴"]
    intercept_message = True

    async def execute(self):
        # 权限判断
        if not self._check_user_permission():
            return False, "权限不足"

        platform = self.message.chat_stream.platform
        group_id = str(self.message.chat_stream.group_info.group_id)
        group_name = getattr(self.message.chat_stream.group_info, "group_name", None)
        if not group_name:
            try:
                from src.chat.message_receive.chat_stream import get_chat_manager
                group_name = get_chat_manager().get_stream_name(self.message.chat_stream.stream_id)
            except Exception:
                group_name = None
        
        # 尝试多种方式拦截消息处理
        
        # 1. 保存原始消息处理器并替换
        if hasattr(self.message.chat_stream, "message_handler"):
            original_handler = self.message.chat_stream.message_handler
            SilentStatus.store_handler(platform, group_id, original_handler)
            
            # 先读取全局chat_stream配置的 at_bot_inevitable_reply，其次读取插件开关
            _allow_attr = getattr(self.message.chat_stream, "at_bot_inevitable_reply", None)
            if _allow_attr is None:
                _allow_at_break = self.get_config("silent.at_mention_break", True)
            else:
                _allow_at_break = bool(_allow_attr)

            async def enhanced_silent_handler(message):
                """增强版静音处理器：根据配置判断是否允许@或关键词打断静音"""

                # DEBUG：输出提及检测信息
                logger.info(
                    f"[EnhancedSilentHandler] is_mentioned={getattr(message, 'is_mentioned', False)}, "
                    f"contains_at={_contains_at(message)}, text='{getattr(message, 'text', '')}'"
                )

                # 如果检测到解除静音关键词或@
                should_unmute = False
                if is_open_mouth_keyword(message):
                    should_unmute = True
                elif _allow_at_break:
                    if getattr(message, "is_mentioned", False):
                        should_unmute = True
                    elif getattr(message.chat_stream, "at_bot_inevitable_reply", False):
                        should_unmute = True
                    else:
                        # 如果文本中出现显式提及机器人 (@机器人/CQ:at 指向机器人)，则解除静音
                        if _contains_at(message):
                            should_unmute = True

                if should_unmute:
                    # 解除静音
                    SilentStatus.clear_mute(platform, group_id)
                    logger.info(f"[SilentStatus] 群 {platform}:{group_id} 因关键词/提及解除静音")

                    # 恢复原消息处理器
                    original_handler = SilentStatus.get_handler(platform, group_id)
                    if original_handler and hasattr(message.chat_stream, "set_message_handler"):
                        message.chat_stream.set_message_handler(original_handler)
                        logger.info(f"[SilentStatus] 群 {platform}:{group_id} 已恢复原始消息处理器")

                    # 对于@打断，需要正常回复；对于关键词解除则静默
                    if getattr(message, "is_mentioned", False):
                        # 让原处理器来处理当前这条消息
                        if original_handler:
                            return await original_handler(message)
                    # 关键词解除（如"麦麦张嘴"）不回复
                    return None

                # 若未解除静音，则继续拦截处理
                SilentStatus.log_summary(platform, group_id)

                # 阻止其他处理逻辑
                if hasattr(message, "is_processed"):
                    message.is_processed = True

                if hasattr(message.chat_stream, "reply_probability"):
                    message.chat_stream.reply_probability = 0

                for attr_name in ["at_bot_inevitable_reply", "mentioned_bot_inevitable_reply",
                                  "interested_rate", "interest_rate", "reply_rate"]:
                    if hasattr(message.chat_stream, attr_name):
                        try:
                            if isinstance(getattr(message.chat_stream, attr_name), bool):
                                setattr(message.chat_stream, attr_name, False)
                            elif isinstance(getattr(message.chat_stream, attr_name), (int, float)):
                                setattr(message.chat_stream, attr_name, 0)
                        except:
                            pass

                return None
            
            # 替换为静音消息处理器
            if hasattr(self.message.chat_stream, "set_message_handler"):
                self.message.chat_stream.set_message_handler(enhanced_silent_handler)
                logger.info(f"[SilentStatus] 群 {platform}:{group_id} 已替换为增强版静音消息处理器")
        
        # 2. 尝试直接修改回复概率相关属性
        try:
            # 尝试找到并修改回复概率相关的属性
            chat_stream = self.message.chat_stream
            if hasattr(chat_stream, "reply_probability"):
                # 直接设置回复概率为0
                setattr(chat_stream, "reply_probability", 0)
                logger.info(f"[SilentStatus] 已将群 {platform}:{group_id} 的回复概率设置为0")
            
            # 修改其他可能的属性
            for attr_name in ["at_bot_inevitable_reply", "mentioned_bot_inevitable_reply", 
                            "interested_rate", "interest_rate", "reply_rate"]:
                if hasattr(chat_stream, attr_name):
                    try:
                        if isinstance(getattr(chat_stream, attr_name), bool):
                            setattr(chat_stream, attr_name, False)
                            logger.info(f"[SilentStatus] 已将群 {platform}:{group_id} 的 {attr_name} 设置为False")
                        elif isinstance(getattr(chat_stream, attr_name), (int, float)):
                            setattr(chat_stream, attr_name, 0)
                            logger.info(f"[SilentStatus] 已将群 {platform}:{group_id} 的 {attr_name} 设置为0")
                    except Exception as e:
                        logger.error(f"[SilentStatus] 修改属性 {attr_name} 时出错: {str(e)}")
        except Exception as e:
            logger.error(f"[SilentStatus] 尝试修改回复概率时出错: {str(e)}")

        duration = self.get_config("silent.duration_seconds", 600)
        SilentStatus.set_mute(platform, group_id, duration, group_name)
        
        # 不发送任何提示消息，静默进入静音状态
        return True, "已进入静音"

    # ------------------ 权限校验 ------------------
    def _check_user_permission(self) -> bool:
        user_id = str(self.message.chat_stream.user_info.user_id)
        ltype = self.get_config("user_control.list_type", "whitelist")
        ulist = [str(x) for x in self.get_config("user_control.list", [])]
        if ltype == "whitelist":
            # 空白名单时禁止任何人使用
            return user_id in ulist
        else:  # blacklist
            return user_id not in ulist


class OpenMouthCommand(BaseCommand):
    """命令：麦麦张嘴 → 解除静音"""

    command_name = "open_mouth"
    command_description = "解除静音模式"
    command_pattern = r"^(?:麦麦)?张嘴$"
    command_examples = ["麦麦张嘴", "张嘴"]
    intercept_message = True

    async def execute(self):
        if not self.message.chat_stream.group_info:
            # 非群聊不处理
            return False, "非群聊"

        if not self._check_user_permission():
            return False, "权限不足"

        platform = self.message.chat_stream.platform
        group_id = str(self.message.chat_stream.group_info.group_id)
        group_name = getattr(self.message.chat_stream.group_info, "group_name", None)
        if not group_name:
            try:
                from src.chat.message_receive.chat_stream import get_chat_manager
                group_name = get_chat_manager().get_stream_name(self.message.chat_stream.stream_id)
            except Exception:
                group_name = None

        # 恢复原来的消息处理器
        original_handler = SilentStatus.get_handler(platform, group_id)
        if original_handler and hasattr(self.message.chat_stream, "set_message_handler"):
            self.message.chat_stream.set_message_handler(original_handler)
            logger.info(f"[SilentStatus] 群 {platform}:{group_id} 已恢复原始消息处理器")

        SilentStatus.clear_mute(platform, group_id)
        if group_name:
            SilentGroupLogFilter.remove_group(group_name)
        # 不发送任何提示消息，静默解除静音状态
        return True, None

    def _check_user_permission(self) -> bool:
        user_id = str(self.message.chat_stream.user_info.user_id)
        ltype = self.get_config("user_control.list_type", "whitelist")
        ulist = [str(x) for x in self.get_config("user_control.list", [])]
        if ltype == "whitelist":
            return user_id in ulist
        else:
            return user_id not in ulist


# ======================== Action Component =======================


class SilentFilterAction(BaseAction):
    """静音过滤 Action：作为备用拦截机制"""

    action_name = "silent_filter"
    action_description = "静音期间备用拦截机制"

    # 确保在所有模式下都激活，最高优先级
    focus_activation_type = ActionActivationType.ALWAYS
    normal_activation_type = ActionActivationType.ALWAYS
    mode_enable = ChatMode.ALL
    parallel_action = False
    priority = 1000  # 极高优先级，确保最先执行

    action_parameters = {}
    action_require = ["当机器人处于静音模式时，完全不处理任何消息"]

    async def execute(self):
        # 根据配置，是否允许@机器人打断静音
        if not self.get_config("silent.at_mention_break", True):
            allow_at = False
        else:
            allow_at = True

        # 仅在群聊场景下生效
        if not self.is_group:
            return False, "非群聊"

        # 检查是否处于静音状态
        gid_str = str(self.group_id)
        if not SilentStatus.is_muted(self.platform, gid_str):
            return False, "未静音"

        # 检查是否是解除静音命令
        is_open_mouth_cmd = False
        if self.message.text:
            is_open_mouth_cmd = is_open_mouth_keyword(self.message.text)
        
        # 如果检测到解除静音命令，则不拦截
        if is_open_mouth_cmd:
            # 解除静音
            SilentStatus.clear_mute(self.platform, gid_str)
            logger.info(f"[SilentFilterAction] 群 {self.platform}:{gid_str} 解除静音命令，不拦截")
            return False, "解除命令，不拦截"

        # 检查是否允许@机器人打断静音
        contains_at_flag = _contains_at(self.message)
        logger.info(f"[SilentFilterAction] check at: allow_at={allow_at}, contains_explicit_at={contains_at_flag}, text='{getattr(self.message, 'text', '')}'")

        if allow_at and contains_at_flag:
            # 解除静音并放行
            SilentStatus.clear_mute(self.platform, gid_str)

            # 恢复原始消息处理器（如果之前被替换）
            original_handler = SilentStatus.get_handler(self.platform, gid_str)
            if original_handler and hasattr(self.message.chat_stream, "set_message_handler"):
                self.message.chat_stream.set_message_handler(original_handler)
                logger.info(f"[SilentFilterAction] 群 {self.platform}:{gid_str} 已恢复原始消息处理器 (因@提及)")

            # 取消已处理标记，放行后续正常流程
            if hasattr(self.message, "is_processed"):
                self.message.is_processed = False

            logger.info(f"[SilentFilterAction] 群 {self.platform}:{gid_str} 因@提及解除静音，已放行正常处理链")
            return False, "@提及放行"

        # ===== 强制阻断后续 Action =====
        try:
            # 新版 MaiBot BaseAction 提供 block_other_actions()
            if hasattr(self, "block_other_actions"):
                await self.block_other_actions()
        except Exception:
            # 旧版没有该方法则忽略
            pass

        # 这是一个备用拦截机制 - 仅输出简要日志
        SilentStatus.log_summary(self.platform, gid_str)
        
        # 尝试直接修改消息对象，阻止后续处理
        try:
            # 1. 设置消息已处理标记
            await self.store_action_info(
                action_build_into_prompt=False,
                action_prompt_display="静音中",
                action_done=True,
            )
            
            # 2. 直接终止消息处理 - 关键修改
            self.message.is_processed = True  # 标记消息已处理
            
            # 3. 如果消息有chat_stream属性，修改其回复概率
            if hasattr(self.message, "chat_stream"):
                chat_stream = self.message.chat_stream
                
                # 设置回复概率为0
                if hasattr(chat_stream, "reply_probability"):
                    setattr(chat_stream, "reply_probability", 0)
                
                # 尝试设置其他可能的属性
                for attr_name in ["at_bot_inevitable_reply", "mentioned_bot_inevitable_reply", 
                                 "interested_rate", "interest_rate", "reply_rate"]:
                    if hasattr(chat_stream, attr_name):
                        try:
                            if isinstance(getattr(chat_stream, attr_name), bool):
                                setattr(chat_stream, attr_name, False)
                            elif isinstance(getattr(chat_stream, attr_name), (int, float)):
                                setattr(chat_stream, attr_name, 0)
                        except:
                            pass
            
            # 4. 如果有message_handler属性，替换为空函数
            if hasattr(self.message, "message_handler"):
                async def empty_handler(msg):
                    logger.info(f"[SilentFilterAction] 空处理器拦截消息: {msg.text if hasattr(msg, 'text') else '无文本'}")
                    return None
                
                self.message.message_handler = empty_handler
                
            # 5. 如果消息有chat_stream属性，且chat_stream有message_handler属性，也替换为空函数
            if hasattr(self.message, "chat_stream") and hasattr(self.message.chat_stream, "message_handler"):
                async def empty_stream_handler(msg):
                    logger.info(f"[SilentFilterAction] 空处理器拦截流消息: {msg.text if hasattr(msg, 'text') else '无文本'}")
                    return None
                
                self.message.chat_stream.message_handler = empty_stream_handler
                
                # 如果有set_message_handler方法，也调用它
                if hasattr(self.message.chat_stream, "set_message_handler"):
                    self.message.chat_stream.set_message_handler(empty_stream_handler)
                    
        except Exception as e:
            logger.error(f"[SilentFilterAction] 尝试修改消息属性时出错: {str(e)}")
        
        # 返回True表示已处理，阻止后续动作执行
        return True, "静音过滤"


# =============== 最小补丁 ===============

def _apply_silent_patch_to_normal_chat():
    """给 NormalChat.normal_response 打补丁，拦截静音期间的所有回复。"""
    if getattr(NormalChat, "_silent_mode_patched", False):
        return  # 已经补过

    original_normal_response = NormalChat.normal_response

    async def patched_normal_response(self: NormalChat, message, is_mentioned: bool, interested_rate: float):
        # 仅群聊检查静音
        if hasattr(self.chat_stream, "group_info") and self.chat_stream.group_info:
            platform = self.chat_stream.platform
            group_id = str(self.chat_stream.group_info.group_id)
            if SilentStatus.is_muted(platform, group_id):
                # 如果是解除静音关键词则放行
                if is_open_mouth_keyword(getattr(message, "text", "")):
                    SilentStatus.clear_mute(platform, group_id)
                    logger.info(f"[SilentPatch] 群 {platform}:{group_id} 解除静音 (关键词)")
                # 如果@提及并允许打断，则解除并继续正常回复
                elif _contains_at(message) and ALLOW_AT_BREAK:
                    SilentStatus.clear_mute(platform, group_id)
                    logger.info(f"[SilentPatch] 群 {platform}:{group_id} 因@提及解除静音")
                    # 解除后调用原始响应，正常回复
                    return await original_normal_response(self, message, is_mentioned, interested_rate)
                else:
                    # 输出摘要日志
                    SilentStatus.log_summary(platform, group_id)

                    # 如果未开启 chat 日志屏蔽，则手动记录一条聊天明细，保持可观察性
                    if not SilentGroupLogFilter.suppress_chat_logs:
                        _chat_logger = logging.getLogger("chat")
                        try:
                            sender = getattr(message, "sender_nickname", None)
                            if not sender:
                                sender = getattr(message.user_info if hasattr(message, "user_info") else message, "nickname", None)
                            if not sender:
                                sender = str(getattr(message, "user_id", "?"))
                            group_display = getattr(self.chat_stream.group_info, "group_name", None) or group_id
                            _chat_logger.info("[%s]%s:%s", group_display, sender, getattr(message, "text", ""))
                        except Exception:
                            pass

                    return  # 直接不回复
        # 非静音或已解除 -> 调用原函数
        return await original_normal_response(self, message, is_mentioned, interested_rate)

    NormalChat.normal_response = patched_normal_response
    NormalChat._silent_mode_patched = True
    logger.info("[SilentPatch] 已为 NormalChat.normal_response 应用补丁")


# ====================== Console Log Filter ======================


class SilentGroupLogFilter(logging.Filter):
    """日志过滤器：屏蔽处于静音状态群聊的详细聊天日志，只保留插件自身输出。"""

    muted_group_names: set[str] = set()
    suppress_memory_logs: bool = True  # 可由插件配置覆盖
    suppress_chat_logs: bool = True   # 新增：是否屏蔽 chat/normal_chat 日志

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        """决定是否放行日志记录。"""
        # 始终放行插件本身的日志
        if str(record.name).startswith("silent_mode_plugin"):
            return True

        # 获取日志消息文本
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)

        # 当存在处于静音的群聊时，根据开关决定是否屏蔽 chat / normal_chat 日志
        if self.suppress_chat_logs and SilentStatus._muted_groups:
            # 检查日志是否包含静音群聊的ID或名称
            is_muted_group_log = False
            
            # 检查群ID是否在消息中
            for key in list(SilentStatus._muted_groups):
                # key 格式: platform:group_id
                _, g_id = key.split(":", 1)
                if g_id and g_id in msg:
                    is_muted_group_log = True
                    break
            
            # 检查群名称是否在消息中
            if not is_muted_group_log:
                for g_name in list(self.muted_group_names):
                    if g_name and g_name in msg:
                        is_muted_group_log = True
                        break
            
            # 仅当是静音群的日志时才过滤
            if is_muted_group_log:
                _chat_like_loggers = {"chat", "normal_chat", "chat_utils", "sub_heartflow", "subheartflow_manager"}
                
                if record.name in _chat_like_loggers:
                    return False
                
                # 对 normal_chat 的详细输出做额外关键字判断
                if record.name == "normal_chat" and "当前回复频率" in msg:
                    return False

        # 静音期间屏蔽 memory 模块日志，避免噪音
        if self.suppress_memory_logs and record.name == "memory" and SilentStatus._muted_groups:
            return False

        return True  # 其它日志正常放行

    # --------- 静态方法，供 SilentStatus 调用 ---------

    @classmethod
    def add_group(cls, group_name: str | None):
        if group_name:
            cls.muted_group_names.add(group_name)

    @classmethod
    def remove_group(cls, group_name: str | None):
        if group_name and group_name in cls.muted_group_names:
            cls.muted_group_names.discard(group_name)


# 在插件加载时为根 logger 安装过滤器（仅安装一次）

def _install_log_filter_once():
    root_logger = logging.getLogger()
    if not any(isinstance(f, SilentGroupLogFilter) for f in root_logger.filters):
        root_logger.addFilter(SilentGroupLogFilter())
        logger.info("[SilentModePlugin] 已安装静音群聊日志过滤器")

    # 同时给频繁输出的模块 logger 单独加过滤器，避免其自定义 handler 绕过 root
    for lname in ("chat", "normal_chat", "memory"):
        l = logging.getLogger(lname)
        if not any(isinstance(f, SilentGroupLogFilter) for f in l.filters):
            l.addFilter(SilentGroupLogFilter())


# =========================== Plugin ==============================


@register_plugin
class SilentModePlugin(BasePlugin):
    """静音模式插件：可通过命令让机器人在群聊中闭嘴一段时间"""

    plugin_name = "silent_mode_plugin"
    enable_plugin = True
    config_file_name = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "silent": "静音参数配置",
        "user_control": "用户控制配置",
    }

    # 配置 Schema
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="0.3.0", description="配置文件版本"),
        },
        "silent": {
            "duration_seconds": ConfigField(type=int, default=600, description="静音持续时间（秒)"),
            # 新版：支持配置多个关键词
            "shutup_keywords": ConfigField(type=list, default=["麦麦闭嘴", "闭嘴"], description="进入静音关键词列表"),
            "open_mouth_keywords": ConfigField(type=list, default=["麦麦张嘴", "张嘴"], description="解除静音关键词列表"),

            # 旧版兼容字段（单关键词）
            "shutup_keyword": ConfigField(type=str, default="麦麦闭嘴", description="进入静音关键词（兼容旧版本）"),
            "open_mouth_keyword": ConfigField(type=str, default="麦麦张嘴", description="解除静音关键词（兼容旧版本）"),

            "enable_open_mouth": ConfigField(type=bool, default=True, description="是否启用解除静音关键词"),
            "at_mention_break": ConfigField(type=bool, default=True, description="@机器人时是否忽略静音"),
            "suppress_memory_logs": ConfigField(type=bool, default=True, description="静音时是否隐藏 memory 日志"),
            "suppress_chat_logs": ConfigField(type=bool, default=True, description="静音时是否屏蔽后台 chat/normal_chat 消息日志"),
            "show_summary_log": ConfigField(type=bool, default=True, description="是否输出静音剩余时间提醒日志"),
        },
        "user_control": {
            "list_type": ConfigField(type=str, default="whitelist", description="whitelist 或 blacklist"),
            "list": ConfigField(type=list, default=[], description="QQ号列表"),
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 应用最小补丁
        _apply_silent_patch_to_normal_chat()
        # 安装日志过滤器
        _install_log_filter_once()
        logger.info("[SilentModePlugin] 静音模式插件初始化完成，并已应用补丁")

        # 设置 memory 日志抑制开关供过滤器使用
        SilentGroupLogFilter.suppress_memory_logs = self.get_config("silent.suppress_memory_logs", True)
        # 设置 chat 日志抑制开关
        SilentGroupLogFilter.suppress_chat_logs = self.get_config("silent.suppress_chat_logs", True)

        # 读取是否输出静音剩余提醒日志的开关
        global ENABLE_SUMMARY_LOG
        ENABLE_SUMMARY_LOG = self.get_config("silent.show_summary_log", True)

        # 读取@提及是否打断静音的开关
        global ALLOW_AT_BREAK
        ALLOW_AT_BREAK = self.get_config("silent.at_mention_break", True)

        # ----------------- 动态更新关键词 -----------------
        global SHUTUP_KEYWORDS, OPEN_MOUTH_KEYWORDS

        # 1) 读取闭嘴关键词列表
        shutup_kws = self.get_config("silent.shutup_keywords", None)
        if not shutup_kws:
            # 兼容旧字段
            old_kw = self.get_config("silent.shutup_keyword", "麦麦闭嘴")
            shutup_kws = [old_kw]
        elif isinstance(shutup_kws, str):
            shutup_kws = [shutup_kws]
        SHUTUP_KEYWORDS = {kw.strip() for kw in shutup_kws if kw.strip()}

        # 2) 读取张嘴关键词列表
        open_kws = self.get_config("silent.open_mouth_keywords", None)
        if not open_kws:
            old_kw = self.get_config("silent.open_mouth_keyword", "麦麦张嘴")
            open_kws = [old_kw]
        elif isinstance(open_kws, str):
            open_kws = [open_kws]
        OPEN_MOUTH_KEYWORDS = {kw.strip() for kw in open_kws if kw.strip()}

        # 3) 更新命令正则与说明
        # 闭嘴命令
        shutup_pattern = "|".join(re.escape(k) for k in SHUTUP_KEYWORDS)
        mention_prefix = r"(?:\[CQ:at,[^\]]+\]\s*|@\S+\s*)*"
        ShutupCommand.command_pattern = rf"^{mention_prefix}(?:{shutup_pattern})$"
        ShutupCommand.command_description = f"让机器人闭嘴，关键词：{', '.join(SHUTUP_KEYWORDS)}"
        ShutupCommand.command_examples = list(SHUTUP_KEYWORDS)

        # 张嘴命令
        if self.get_config("silent.enable_open_mouth", True) and OPEN_MOUTH_KEYWORDS:
            open_pattern = "|".join(re.escape(k) for k in OPEN_MOUTH_KEYWORDS)
            OpenMouthCommand.command_pattern = rf"^{mention_prefix}(?:{open_pattern})$"
            OpenMouthCommand.command_description = f"解除静音，关键词：{', '.join(OPEN_MOUTH_KEYWORDS)}"
            OpenMouthCommand.command_examples = list(OPEN_MOUTH_KEYWORDS)
        else:
            OpenMouthCommand.command_pattern = r"^$"  # 永不匹配

        # --- 启动后台任务监听 config 热更新 ---
        try:
            async def _watch_config():
                cfg_path = os.path.join(os.path.dirname(__file__), self.config_file_name)
                last_mtime = os.path.getmtime(cfg_path)
                while True:
                    await asyncio.sleep(10)  # 每10秒检查一次
                    try:
                        mtime = os.path.getmtime(cfg_path)
                    except FileNotFoundError:
                        continue
                    if mtime != last_mtime:
                        last_mtime = mtime
                        logger.info("[SilentModePlugin] 检测到 config.toml 变更，重新加载配置…")
                        try:
                            with open(cfg_path, "rb") as f:
                                new_cfg = _toml_lib.load(f)
                            # 更新内存配置
                            self.config.update(new_cfg)
                            # 重新应用关键词集等动态设置
                            shutup_kw_list = new_cfg.get("silent", {}).get("shutup_keywords")
                            if shutup_kw_list:
                                global SHUTUP_KEYWORDS
                                SHUTUP_KEYWORDS = {str(k).strip() for k in shutup_kw_list}
                            open_kw_list = new_cfg.get("silent", {}).get("open_mouth_keywords")
                            if open_kw_list:
                                global OPEN_MOUTH_KEYWORDS
                                OPEN_MOUTH_KEYWORDS = {str(k).strip() for k in open_kw_list}

                            # 重新生成命令正则
                            shutup_pattern = "|".join(re.escape(k) for k in SHUTUP_KEYWORDS)
                            mention_prefix = r"(?:\[CQ:at,[^\]]+\]\s*|@\S+\s*)*"
                            ShutupCommand.command_pattern = rf"^{mention_prefix}(?:{shutup_pattern})$"
                            ShutupCommand.command_examples = list(SHUTUP_KEYWORDS)

                            if new_cfg.get("silent", {}).get("enable_open_mouth", True):
                                open_pattern = "|".join(re.escape(k) for k in OPEN_MOUTH_KEYWORDS)
                                OpenMouthCommand.command_pattern = rf"^{mention_prefix}(?:{open_pattern})$"
                                OpenMouthCommand.command_examples = list(OPEN_MOUTH_KEYWORDS)
                            else:
                                OpenMouthCommand.command_pattern = r"^$"

                            # 更新摘要日志输出开关
                            global ENABLE_SUMMARY_LOG
                            ENABLE_SUMMARY_LOG = new_cfg.get("silent", {}).get("show_summary_log", True)

                            # 更新@提及打断开关
                            global ALLOW_AT_BREAK
                            ALLOW_AT_BREAK = new_cfg.get("silent", {}).get("at_mention_break", True)

                            # 更新 chat 日志抑制开关
                            SilentGroupLogFilter.suppress_chat_logs = new_cfg.get("silent", {}).get("suppress_chat_logs", True)

                            logger.info("[SilentModePlugin] 配置热更新完成：关键词已刷新")
                        except Exception as e:
                            logger.error(f"[SilentModePlugin] 热更新配置失败: {e}")

            # 在插件环境里启动后台看护任务
            loop = asyncio.get_event_loop()
            loop.create_task(_watch_config())
        except Exception as e:
            logger.debug(f"[SilentModePlugin] 未启动热更新监视器: {e}")

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        comps = [
            (SilentFilterAction.get_action_info(), SilentFilterAction),
            (ShutupCommand.get_command_info(), ShutupCommand),
        ]
        if self.get_config("silent.enable_open_mouth", True):
            comps.append((OpenMouthCommand.get_command_info(), OpenMouthCommand))
        return comps

# ======================= 关键词全局集合 =======================
# 这些集合会在插件初始化时根据配置动态填充，供各组件/补丁统一引用。

SHUTUP_KEYWORDS: set[str] = set()
OPEN_MOUTH_KEYWORDS: set[str] = set()

# 控制是否输出静音剩余时间摘要日志（通过配置 silent.show_summary_log 开关）
ENABLE_SUMMARY_LOG: bool = True

# 是否允许@打断静音（通过配置 silent.at_mention_break 开关）
ALLOW_AT_BREAK: bool = True

# +++++ 新增：通用工具函数 +++++

def _get_msg_text(msg) -> str:
    """尽量从不同字段获取可读文本"""
    if msg is None:
        return ""
    if hasattr(msg, "text") and msg.text:
        return str(msg.text)
    if hasattr(msg, "processed_plain_text") and msg.processed_plain_text:
        return str(msg.processed_plain_text)
    return ""

def _strip_mentions(text: str) -> str:
    """移除文本中的[CQ:at]或@提及，返回干净文本"""
    if not text:
        return ""
    # 移除 CQ 码形式的 @
    text = re.sub(r"\[CQ:at,[^\]]+\]", "", text)
    # 移除简易的 @xxx
    text = re.sub(r"@\S+", "", text)
    return text.strip()

def is_shutup_keyword(text_or_msg) -> bool:
    """判断文本/消息是否为触发静音关键词"""
    text = text_or_msg if isinstance(text_or_msg, str) else _get_msg_text(text_or_msg)
    if not text:
        return False
    return _strip_mentions(text) in SHUTUP_KEYWORDS

def is_open_mouth_keyword(text_or_msg) -> bool:
    text = text_or_msg if isinstance(text_or_msg, str) else _get_msg_text(text_or_msg)
    if not text:
        return False
    return _strip_mentions(text) in OPEN_MOUTH_KEYWORDS

def _contains_at(text_or_msg) -> bool:
    """判断文本/消息中是否显式提及了 **机器人本身**。

    仅在满足以下任意一种情况时返回 True：
        1) CQ 码形式   : [CQ:at,qq={bot_qq}]
        2) Mirai 形式  : @<任意昵称:{bot_qq}>
        3) 纯文本形式  : @机器人昵称 或 @机器人别名
    其中机器人信息取自全局配置 global_config.bot。
    """

    text = text_or_msg if isinstance(text_or_msg, str) else _get_msg_text(text_or_msg)
    if not text:
        return False

    # ---- 基础信息 ----
    try:
        bot_qq: str = str(global_config.bot.qq_account).strip()
    except Exception:
        bot_qq = ""

    bot_names: list[str] = []
    try:
        if global_config.bot.nickname:
            bot_names.append(str(global_config.bot.nickname).strip())
        if global_config.bot.alias_names:
            bot_names.extend([str(n).strip() for n in global_config.bot.alias_names])
    except Exception:
        pass

    # ---- 模式 1. CQ 码 ----
    if bot_qq and re.search(rf"\[CQ:at,qq={re.escape(bot_qq)}\]", text):
        return True

    # ---- 模式 2. Mirai/小栗子格式 ----
    if bot_qq and re.search(rf"@<[^>]*?:{re.escape(bot_qq)}>", text):
        return True

    # ---- 模式 3. 纯文本 @昵称/别名 ----
    for name in bot_names:
        if not name:
            continue
        # 支持 @昵称、@ 昵称（带空格）等形式
        if re.search(rf"@\s*{re.escape(name)}", text):
            return True

    return False