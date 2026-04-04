import asyncio
import base64
import json
import os
import random
import re
import time
from pathlib import Path

from astrbot.api.event import filter
from astrbot.api.event.filter import PermissionType
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.core.message.components import At, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from astrbot.api import AstrBotConfig
from .db import SadStoryDB
from .nest_command import NestCommandHandler
from .sticker import StickerManager


from .configs.constants import *
from .core.generator import StoryGeneratorMixin
from .commands.cmd_style import StyleCommandsMixin
from .commands.cmd_template import TemplateCommandsMixin
@register("astrbot_plugin_sadstory", "Towqs", "伪装聊天插件 - 以合并转发形式在群聊中展示伪装聊天", "0.9.2")
class SadStoryPlugin(Star, StoryGeneratorMixin, StyleCommandsMixin, TemplateCommandsMixin):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.user_pool = []
        self.group_users_map = {}
        self.cooldown_map = {}
        self._cooldown_lock = asyncio.Lock()
        self._import_lock = asyncio.Lock()
        self._group_users_lock = asyncio.Lock()
        data_dir = StarTools.get_data_dir("astrbot_plugin_sadstory")
        self.db = SadStoryDB(Path(data_dir) / "sadstory.db")
        self.sticker_manager = StickerManager()

    async def initialize(self):
        await self.db.init()
        self._reload_config()
        await self._import_webui_data()
        await self._import_file_templates()
        self.nest_handler = NestCommandHandler(self)
        logger.info(f"[SadStory] 插件初始化完成，主讲人: {len(self.custom_protagonists)}个, 网友: {len(self.custom_bystanders)}个")

    async def terminate(self):
        """插件卸载时清理资源"""
        if hasattr(self, 'db') and self.db:
            await self.db.close()
            logger.info("[SadStory] 数据库连接已关闭")

    # ==================== 配置管理 ====================

    @staticmethod
    def _parse_bool(val) -> bool:
        """兼容 WebUI 返回的各种 bool 格式"""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "是")
        return bool(val)

    def _reload_config(self):
        """同步读取配置"""
        cfg = self.config

        self.source_group_id = self._parse_int(cfg.get("source_group_id", ""), 0)
        self.use_card_as_name = self._parse_bool(cfg.get("use_card_as_name", True))
        self.cooldown_seconds = max(0, self._parse_int(cfg.get("cooldown_seconds", ""), 60))
        self.story_min_messages = self._clamp(self._parse_int(cfg.get("story_min_messages", ""), 30), 1, 100)
        self.story_max_messages = self._clamp(self._parse_int(cfg.get("story_max_messages", ""), 80), 1, 100)
        
        self.remove_ending_punctuation = self._parse_bool(cfg.get("remove_ending_punctuation", True))
        self.punctuations_to_remove = cfg.get("punctuations_to_remove", "。，；;~")

        if self.story_min_messages > self.story_max_messages:
            self.story_min_messages, self.story_max_messages = self.story_max_messages, self.story_min_messages
        self.bystander_count = self._clamp(self._parse_int(cfg.get("bystander_count", ""), 3), 0, 10)
        self.chat_provider_id = str(cfg.get("chat_provider_id", "")).strip()
        self.use_virtual_users = self._parse_bool(cfg.get("use_virtual_users", False))
        self.use_story_template = self._parse_bool(cfg.get("use_story_template", True))
        self.use_face_emoji = self._parse_bool(cfg.get("use_face_emoji", True))
        self.use_casual_style = self._parse_bool(cfg.get("use_casual_style", True))
        
        use_meme_sticker = self._parse_bool(cfg.get("use_meme_sticker", False))
        meme_sticker_frequency = self._clamp(self._parse_int(cfg.get("meme_sticker_frequency", ""), 10), 0, 100)
        self.sticker_manager.update_config(use_meme_sticker, meme_sticker_frequency)

        self.nest_count_min = self._clamp(self._parse_int(cfg.get("nest_count_min", ""), 1), 1, 5)
        self.nest_count_max = self._clamp(self._parse_int(cfg.get("nest_count_max", ""), 3), 1, 5)
        if self.nest_count_min > self.nest_count_max:
            self.nest_count_min, self.nest_count_max = self.nest_count_max, self.nest_count_min
        self.inner_msg_min = self._clamp(self._parse_int(cfg.get("inner_msg_min", ""), 3), 2, 20)
        self.inner_msg_max = self._clamp(self._parse_int(cfg.get("inner_msg_max", ""), 8), 2, 20)
        if self.inner_msg_min > self.inner_msg_max:
            self.inner_msg_min, self.inner_msg_max = self.inner_msg_max, self.inner_msg_min

        self.daily_usage_limit = self._clamp(self._parse_int(cfg.get("daily_usage_limit", ""), 3), 0, 100)

        raw_allowed = cfg.get("allowed_user_list", [])
        self.allowed_users = set()
        if isinstance(raw_allowed, list):
            for item in raw_allowed:
                qq = str(item).strip()
                if qq:
                    self.allowed_users.add(qq)

        raw_protagonists = cfg.get("protagonist_qq_list", [])
        self.custom_protagonists = []
        if isinstance(raw_protagonists, list):
            for item in raw_protagonists:
                qq = str(item).strip()
                if qq:
                    self.custom_protagonists.append({"nickname": "", "user_id": qq})

        # 解析网友QQ号列表
        raw_bystanders = cfg.get("bystander_qq_list", [])
        self.custom_bystanders = []
        if isinstance(raw_bystanders, list):
            for item in raw_bystanders:
                qq = str(item).strip()
                if qq:
                    self.custom_bystanders.append({"nickname": "", "user_id": qq})

        logger.info(f"[SadStory] 配置加载: 主讲人={len(self.custom_protagonists)}, 网友={len(self.custom_bystanders)}, 素材群={self.source_group_id}, 贴纸={self.sticker_manager.enabled}")
        self.user_pool = self.custom_protagonists + self.custom_bystanders

    async def _import_webui_data(self):
        """从 WebUI 的 template_list 配置导入写作风格和故事模板到数据库，导入后清空"""
        async with self._import_lock:
            cfg = self.config
            imported = 0

            raw_styles = cfg.get("add_writing_styles", [])
            logger.debug(f"[SadStory] WebUI raw_styles type={type(raw_styles).__name__}, value={raw_styles!r}")
            if isinstance(raw_styles, list) and raw_styles:
                for s in raw_styles:
                    if isinstance(s, dict):
                        name = str(s.get("style_name", "")).strip()
                        enabled = self._parse_bool(s.get("enabled", True))
                        content = str(s.get("prompt_content", "")).strip()
                        if name and content:
                            await self.db.add_style(name, content, enabled)
                            imported += 1
                cfg["add_writing_styles"] = []
                self.config.save_config()

            raw_tpls = cfg.get("add_story_templates", [])
            logger.debug(f"[SadStory] WebUI raw_tpls type={type(raw_tpls).__name__}, value={raw_tpls!r}")
            if isinstance(raw_tpls, list) and raw_tpls:
                for t in raw_tpls:
                    if isinstance(t, dict):
                        name = str(t.get("tpl_name", "")).strip()
                        enabled = self._parse_bool(t.get("enabled", True))
                        content = str(t.get("content", "")).strip()
                        if name and content:
                            await self.db.add_template(name, content, enabled)
                            imported += 1
                cfg["add_story_templates"] = []
                self.config.save_config()

            if imported:
                logger.info(f"[SadStory] 从 WebUI 导入了 {imported} 条数据到数据库")

    async def _import_file_templates(self):
        """将 templates/ 目录下的 .txt 文件模板导入数据库（仅首次，按文件名去重）"""
        if not os.path.isdir(TEMPLATES_DIR):
            return
        imported = 0
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if not fname.endswith(".txt"):
                continue
            name = fname.replace(".txt", "")
            if await self.db.has_template_by_name(name):
                continue
            fpath = os.path.join(TEMPLATES_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    tpl_id = await self.db.add_template(name, content, enabled=True)
                    if tpl_id is not None:
                        imported += 1
            except Exception as e:
                logger.warning(f"[SadStory] 导入文件模板 {fname} 失败：{e}")
        if imported:
            logger.info(f"[SadStory] 从 templates/ 目录导入了 {imported} 个文件模板到数据库")

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(value, hi))

    @staticmethod
    def _parse_int(s, default: int = 0) -> int:
        try:
            return int(s) if s is not None and str(s).strip() else default
        except (ValueError, TypeError):
            return default

    # ==================== 用户池管理 ====================

    async def _fetch_group_users(self, bot, group_id: int) -> list:
        try:
            members = await asyncio.wait_for(
                bot.get_group_member_list(group_id=group_id),
                timeout=30.0
            )
            users = []
            for m in members:
                uid = str(m.get("user_id", ""))
                nickname = m.get("card", "") if self.use_card_as_name else ""
                if not nickname:
                    nickname = m.get("nickname", f"用户{uid[-4:]}")
                users.append({"nickname": nickname, "user_id": uid})
            logger.info(f"[SadStory] 从群 {group_id} 获取到 {len(users)} 个用户")
            return users
        except asyncio.TimeoutError:
            logger.error(f"[SadStory] 获取群成员列表超时: group_id={group_id}")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 获取群成员列表失败: {e}")
            return []

    async def _fetch_random_bystanders(self, bot, group_id: int, count: int, exclude_ids: set) -> list:
        """随机抽样获取旁观者，避免加载全部成员"""
        try:
            members = await asyncio.wait_for(
                bot.get_group_member_list(group_id=group_id),
                timeout=30.0
            )
            candidates = []
            for m in members:
                uid = str(m.get("user_id", ""))
                if uid in exclude_ids:
                    continue
                nickname = m.get("card", "") if self.use_card_as_name else ""
                if not nickname:
                    nickname = m.get("nickname", f"用户{uid[-4:]}")
                candidates.append({"nickname": nickname, "user_id": uid})
            random.shuffle(candidates)
            result = candidates[:count]
            logger.info(f"[SadStory] 从群 {group_id} 随机抽样 {len(result)} 个旁观者")
            return result
        except asyncio.TimeoutError:
            logger.error(f"[SadStory] 获取群成员列表超时: group_id={group_id}")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 获取群成员列表失败: {e}")
            return []

    def _get_available_users(self, user_pool: list | None = None) -> list:
        if user_pool:
            return user_pool
        if self.use_virtual_users:
            return [
                {"nickname": "路人甲", "user_id": "10001"},
                {"nickname": "深夜失眠的人", "user_id": "10002"},
                {"nickname": "吃瓜群众", "user_id": "10003"},
                {"nickname": "曾经沧海", "user_id": "10004"},
                {"nickname": "匿名网友", "user_id": "10005"},
                {"nickname": "故事收集者", "user_id": "10006"},
            ]
        return []

    # ==================== 冷却检查 ====================

    async def _check_and_set_cooldown(self, group_id: str) -> bool:
        """原子化冷却检查+设置，防止竞态条件"""
        if self.cooldown_seconds <= 0:
            return True
        async with self._cooldown_lock:
            expired = [gid for gid, last in self.cooldown_map.items()
                      if (time.monotonic() - last) >= self.cooldown_seconds]
            for gid in expired:
                self.cooldown_map.pop(gid, None)
            last = self.cooldown_map.get(group_id, 0)
            if (time.monotonic() - last) >= self.cooldown_seconds:
                self.cooldown_map[group_id] = time.monotonic()
                return True
            return False

    async def _clear_cooldown(self, group_id: str):
        """清除冷却（生成失败时调用），加锁保持一致性"""
        async with self._cooldown_lock:
            self.cooldown_map.pop(group_id, None)

    def _check_permission(self, event: AiocqhttpMessageEvent) -> bool:
        """检查用户是否有权限使用指令。列表为空则所有人可用。"""
        if not self.allowed_users:
            return True
        sender_id = str(event.get_sender_id())
        return sender_id in self.allowed_users

    async def _is_admin(self, event: AiocqhttpMessageEvent) -> bool:
        sender_id = str(event.get_sender_id())
        core_config = self.context.get_config()
        admins = core_config.get("admins_id", []) if core_config else []
        return sender_id in [str(a) for a in admins]

    async def _check_daily_usage(self, event: AiocqhttpMessageEvent) -> tuple[bool, int, int]:
        """检查用户每日使用次数
        返回: (是否允许使用, 今日已用次数, 每日上限)
        """
        if self.daily_usage_limit <= 0:
            return True, 0, 0
        sender_id = str(event.get_sender_id())
        if await self._is_admin(event):
            return True, 0, self.daily_usage_limit
        current_usage = await self.db.get_user_daily_usage(sender_id)
        if current_usage >= self.daily_usage_limit:
            return False, current_usage, self.daily_usage_limit
        return True, current_usage, self.daily_usage_limit

    async def _increment_daily_usage(self, event: AiocqhttpMessageEvent) -> int:
        """增加用户每日使用次数，返回新的使用次数"""
        sender_id = str(event.get_sender_id())
        return await self.db.increment_user_daily_usage(sender_id)

    # ==================== Prompt 风格管理 ====================

    async def _get_active_prompt_style(self, dual_mode: bool = False) -> str:
        """从数据库已启用的风格中随机选一个，没有则回退到内置默认"""
        enabled = await self.db.get_enabled_styles()
        if enabled:
            chosen = random.choice(enabled)
            # 双主角模式下，检查自定义风格是否支持双主角变量
            if dual_mode:
                if "{protagonist_a}" in chosen and "{protagonist_b}" in chosen:
                    return chosen
                # 自定义风格不支持双主角，回退到内置
                logger.warning("[SadStory] 自定义风格不支持双主角变量，回退到内置风格")
                return STORY_PROMPT_DUAL_CASUAL if self.use_casual_style else STORY_PROMPT_DUAL_LITERARY
            return chosen
        if dual_mode:
            return STORY_PROMPT_DUAL_CASUAL if self.use_casual_style else STORY_PROMPT_DUAL_LITERARY
        return STORY_PROMPT_CASUAL if self.use_casual_style else STORY_PROMPT_LITERARY


    # ==================== 故事生成 ====================

    def _get_at_user_ids(self, event: AiocqhttpMessageEvent) -> list[str]:
        ids = []
        seen = set()
        all_segs = event.get_messages()
        logger.debug(f"[SadStory] 消息段: {[(type(s).__name__, getattr(s, 'qq', None), getattr(s, 'sender_id', None)) for s in all_segs]}")
        for seg in all_segs:
            if isinstance(seg, At) and str(seg.qq) != event.get_self_id():
                uid = str(seg.qq)
                if uid not in seen:
                    ids.append(uid)
                    seen.add(uid)
                if len(ids) >= 2:
                    break
        if not ids:
            for seg in all_segs:
                if isinstance(seg, Reply) and seg.sender_id:
                    ids.append(str(seg.sender_id))
                    break
        logger.debug(f"[SadStory] 解析到的 at_ids: {ids}")
        return ids

    def _extract_at_names_from_plain(self, event: AiocqhttpMessageEvent) -> list[str]:
        names = []
        for seg in event.get_messages():
            if hasattr(seg, 'text') and seg.text:
                at_matches = re.findall(r'@([^\s@]+)', seg.text)
                names.extend(at_matches[:2 - len(names)])
                if len(names) >= 2:
                    break
        logger.info(f"[SadStory] 从 Plain 提取的 @昵称: {names}")
        return names


    async def _resolve_user_info(self, bot, group_id: int, user_id: str) -> dict:
        nickname = ""
        try:
            info = await asyncio.wait_for(
                bot.get_group_member_info(group_id=group_id, user_id=int(user_id)),
                timeout=10.0
            )
            if info:
                nickname = info.get("card", "") or info.get("nickname", "")
        except asyncio.TimeoutError:
            logger.warning(f"[SadStory] get_group_member_info 超时: user_id={user_id}")
        except Exception as e:
            logger.debug(f"[SadStory] get_group_member_info 失败 (非群员或无效): {e}")

        if not nickname:
            try:
                info = await asyncio.wait_for(
                    bot.get_stranger_info(user_id=int(user_id)),
                    timeout=10.0
                )
                if info:
                    nickname = info.get("nickname", "")
            except asyncio.TimeoutError:
                logger.debug(f"[SadStory] get_stranger_info 超时: user_id={user_id}")
            except Exception as e:
                logger.debug(f"[SadStory] get_stranger_info 失败: {e}")

        if not nickname:
            nickname = f"用户{str(user_id)[-4:]}"

        return {"nickname": nickname, "user_id": str(user_id)}


    # ==================== 合并转发构建 ====================



    # ==================== 命令处理 ====================

    @filter.command("sadstory")
    async def sadstory(self, event: AiocqhttpMessageEvent):
        if not self._check_permission(event):
            return

        self._reload_config()
        await self._import_webui_data()

        group_id_str = event.get_group_id()
        if not group_id_str or group_id_str == "0":
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        allowed, used, limit = await self._check_daily_usage(event)
        if not allowed:
            yield event.plain_result(f"今日使用次数已达上限（{used}/{limit}次），请明天再来~")
            return

        if not await self._check_and_set_cooldown(group_id_str):
            yield event.plain_result(f"太快了，休息一下吧~ ({self.cooldown_seconds}秒冷却)")
            return

        success = False
        try:
            theme = event.message_str.partition(" ")[2].strip()

            forced_protagonists = []
            group_id = int(group_id_str)

            # 纯数字 QQ 提取 (仅限管理员)
            if await self._is_admin(event):
                parts = theme.split()
                leading_qqs = []
                for p in parts:
                    if p.isdigit() and 5 <= len(p) <= 11:
                        leading_qqs.append(p)
                        if len(leading_qqs) >= 2:
                            break
                    else:
                        break
                if leading_qqs:
                    for str_qq in leading_qqs:
                        info = await self._resolve_user_info(event.bot, group_id, str_qq)
                        forced_protagonists.append(info)
                    theme = " ".join(parts[len(leading_qqs):]).strip()

            if len(theme) > 100:
                theme = theme[:100]

            at_ids = self._get_at_user_ids(event)
            if at_ids:
                for uid in at_ids:
                    # 去重，防止之前提取 QQ 时已经添加过
                    if not any(p['user_id'] == str(uid) for p in forced_protagonists):
                        info = await self._resolve_user_info(event.bot, group_id, uid)
                        forced_protagonists.append(info)
                        if len(forced_protagonists) >= 2:
                            break
                logger.info(f"[SadStory] @获取到的主角: {[(p['nickname'], p['user_id']) for p in forced_protagonists]}")
                theme = re.sub(r'@\S+', '', theme).strip()
                if len(forced_protagonists) == 1:
                    if group_id not in self.group_users_map:
                        fetched = await self._fetch_group_users(event.bot, group_id)
                        if fetched:
                            async with self._group_users_lock:
                                self.group_users_map[group_id] = fetched
                    at_names = self._extract_at_names_from_plain(event)
                    if at_names:
                        pool = self.custom_protagonists + self.custom_bystanders
                        if self.source_group_id:
                            pool += self.group_users_map.get(self.source_group_id, [])
                        pool += self.group_users_map.get(group_id, [])
                        existing_ids = {p['user_id'] for p in forced_protagonists}
                        for name in at_names:
                            for u in pool:
                                if u['user_id'] not in existing_ids and (name in u['nickname'] or u['nickname'] in name):
                                    forced_protagonists.append(u)
                                    existing_ids.add(u['user_id'])
                                    logger.info(f"[SadStory] 从 Plain 补充主角: {u['nickname']}")
                                    break
                            if len(forced_protagonists) >= 2:
                                break
            else:
                at_names = self._extract_at_names_from_plain(event)
                if at_names:
                    if group_id not in self.group_users_map:
                        fetched = await self._fetch_group_users(event.bot, group_id)
                        if fetched:
                            async with self._group_users_lock:
                                self.group_users_map[group_id] = fetched
                    pool = self.custom_protagonists + self.custom_bystanders
                    if self.source_group_id:
                        pool += self.group_users_map.get(self.source_group_id, [])
                    pool += self.group_users_map.get(group_id, [])
                    for name in at_names:
                        for u in pool:
                            if name in u['nickname'] or u['nickname'] in name:
                                if u not in forced_protagonists:
                                    forced_protagonists.append(u)
                                break
                    logger.info(f"[SadStory] 从 Plain 匹配的主角: {[(p['nickname'], p['user_id']) for p in forced_protagonists]}")
                    theme = re.sub(r'@\S+', '', theme).strip()

            if not self.use_virtual_users:
                is_dual_mode = len(forced_protagonists) == 2
                if is_dual_mode:
                    exclude_ids = {p["user_id"] for p in forced_protagonists}
                    bystander_needed = self.bystander_count + 5
                    bystanders = await self._fetch_random_bystanders(event.bot, group_id, bystander_needed, exclude_ids)
                    final_user_pool = forced_protagonists + bystanders
                else:
                    pool = self.custom_protagonists + self.custom_bystanders
                    if self.source_group_id:
                        pool += self.group_users_map.get(self.source_group_id, [])
                    if len(pool) < 2 and group_id != self.source_group_id:
                        pool += self.group_users_map.get(group_id, [])
                    if len(pool) < 2:
                        need_fetch = False
                        async with self._group_users_lock:
                            if group_id not in self.group_users_map:
                                need_fetch = True
                        if need_fetch:
                            fetched = await self._fetch_group_users(event.bot, group_id)
                            if fetched:
                                async with self._group_users_lock:
                                    self.group_users_map[group_id] = fetched
                        pool += self.group_users_map.get(group_id, [])
                    if forced_protagonists:
                        existing_ids = {u["user_id"] for u in pool}
                        for fp in forced_protagonists:
                            if fp["user_id"] not in existing_ids:
                                pool.append(fp)
                                existing_ids.add(fp["user_id"])
                    member_map = {u["user_id"]: u for u in self.group_users_map.get(group_id, [])}
                    custom_pool = []
                    custom_ids = {u["user_id"] for u in self.custom_protagonists + self.custom_bystanders}
                    for user in self.custom_protagonists + self.custom_bystanders:
                        user_copy = {"user_id": user["user_id"], "nickname": user.get("nickname", "")}
                        if not user_copy["nickname"] and user_copy["user_id"] in member_map:
                            user_copy["nickname"] = member_map[user_copy["user_id"]]["nickname"]
                        if not user_copy["nickname"]:
                            user_copy["nickname"] = f"用户{user_copy['user_id'][-4:]}"
                        custom_pool.append(user_copy)
                    pool = custom_pool + [u for u in pool if u["user_id"] not in custom_ids]
                    seen_ids = set()
                    unique_pool = []
                    for u in pool:
                        if u["user_id"] not in seen_ids:
                            unique_pool.append(u)
                            seen_ids.add(u["user_id"])
                    final_user_pool = unique_pool
            else:
                final_user_pool = None

            logger.info(f"[SadStory] 当前用户池大小: {len(final_user_pool) if final_user_pool else 0}, 虚拟模式: {self.use_virtual_users}")

            yield event.plain_result("正在生成伪装聊天，请稍候...")

            messages = await self._generate_story(event, theme, forced_protagonists or None, final_user_pool)
            if not messages:
                yield event.plain_result("生成失败了，可能是用户池不足（至少需要2人）或 LLM 服务暂时不可用，请稍后再试~")
                return

            nodes = self._build_forward_nodes(messages)
            await event.bot.send_group_forward_msg(
                group_id=int(group_id_str),
                messages=nodes,
            )
            success = True
            await self._increment_daily_usage(event)
        except Exception as e:
            logger.error(f"[SadStory] sadstory 执行异常: {e}")
            yield event.plain_result(f"执行失败: {e}")
        finally:
            if not success:
                await self._clear_cooldown(group_id_str)

    @filter.command("sadstory_reload")
    async def reload_users(self, event: AiocqhttpMessageEvent):
        """重新加载素材群用户列表。用法：/sadstory_reload"""
        if not self._check_permission(event):
            return

        if not self.source_group_id:
            yield event.plain_result("未配置素材群，请先在 WebUI 插件配置中设置素材群群号")
            return

        try:
            fetched = await self._fetch_group_users(event.bot, self.source_group_id)
            if fetched:
                async with self._group_users_lock:
                    self.group_users_map[self.source_group_id] = fetched
                yield event.plain_result(f"素材群用户已刷新，当前 {len(fetched)} 人")
            else:
                yield event.plain_result("刷新失败，请检查素材群号是否正确以及机器人是否在群内")
        except Exception as e:
            logger.error(f"[SadStory] reload_users 执行异常: {e}")
            yield event.plain_result(f"刷新失败: {e}")





    # ==================== 配置预览与风格指令 ====================

    @filter.command("sadstory_config")
    async def show_config(self, event: AiocqhttpMessageEvent):
        """查看当前所有配置。用法：/sadstory_config"""
        if not self._check_permission(event):
            return
        try:
            self._reload_config()
            lines = []
            lines.append("📋 伪装聊天 当前配置")
            lines.append("─────────────────")
            lines.append(f"消息条数：{self.story_min_messages} ~ {self.story_max_messages}")
            lines.append(f"围观网友数：{self.bystander_count}")
            lines.append(f"冷却时间：{self.cooldown_seconds}秒")
            lines.append(f"每日使用限制：{self.daily_usage_limit}次（管理员无限制）")
            lines.append(f"QQ表情：{'✅ 开启' if self.use_face_emoji else '❌ 关闭'}")
            lines.append(f"虚拟角色：{'✅ 开启' if self.use_virtual_users else '❌ 关闭'}")
            lines.append(f"群名片优先：{'✅ 是' if self.use_card_as_name else '❌ 否'}")
            lines.append(f"LLM模型：{self.chat_provider_id or '默认'}")
            lines.append(f"素材群：{self.source_group_id or '未配置'}")
            lines.append(f"用户池：{len(self.user_pool)}人")
            if self.custom_protagonists:
                lines.append(f"主讲人：{', '.join(u['user_id'] for u in self.custom_protagonists)}")
            if self.custom_bystanders:
                lines.append(f"网友：{', '.join(u['user_id'] for u in self.custom_bystanders)}")

            styles = await self.db.get_styles()
            lines.append("")
            lines.append("─── 写作风格 ───")
            if styles:
                en = sum(1 for _, _, e, _ in styles if e)
                for sid, name, enabled, content in styles:
                    lines.append(f"  [{sid}] {'✅' if enabled else '❌'} {name}（{len(content)}字）")
                lines.append(f"  启用 {en}/{len(styles)}，生成时随机选取")
            else:
                lines.append(f"  未配置，使用内置{'口语化' if self.use_casual_style else '文学'}风格")

            db_tpls = await self.db.get_templates()
            lines.append("")
            lines.append("─── 故事模板 ───")
            lines.append(f"模板参考：{'✅ 开启' if self.use_story_template else '❌ 关闭'}")
            if db_tpls:
                for tpl_id, name, enabled, content in db_tpls:
                    lines.append(f"  [{tpl_id}] {'✅' if enabled else '❌'} {name}（{len(content)}字）")
            else:
                lines.append("  暂无模板")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[SadStory] show_config 执行异常: {e}")
            yield event.plain_result(f"获取配置失败: {e}")





    # ==================== LLM 工具调用 ====================



    @filter.command("sadstory_help")
    async def sadstory_help(self, event: AiocqhttpMessageEvent):
        """查看所有指令用法。用法：/sadstory_help [指令名]"""
        message_str = event.message_str.partition(" ")[2].strip().lower()
        is_admin = await self._is_admin(event)
        
        user_help = {
            "sadstory": """【/sadstory】生成伪装聊天
用法：/sadstory [主题] [@主角]
示例：
  /sadstory
  /sadstory 校园暗恋
  /sadstory @小明
  /sadstory 校园暗恋 @小明 @小红
说明：普通用户每日使用次数有限制，管理员无限制""",
            
            "sadstory_nest": """【/sadstory_nest】生成嵌套转发聊天
用法：/sadstory_nest @外层发送者 @主角A [@主角B] [主题]
示例：
  /sadstory_nest @咖啡 @守望者
  /sadstory_nest @咖啡 @守望者 @小明 感人的事
说明：
  - 外层发送者：转发消息的人
  - 主角：内层故事的主要角色
  - 主题：可选，故事方向
  - 普通用户每日使用次数有限制，管理员无限制""",
            
            "sadstory_style": """【/sadstory_style】查看写作风格列表
用法：/sadstory_style
说明：显示所有可用的写作风格""",
            
            "sadstory_listtpl": """【/sadstory_listtpl】查看故事模板列表
用法：/sadstory_listtpl
说明：显示所有故事模板""",
            
            "sadstory_config": """【/sadstory_config】查看当前配置
用法：/sadstory_config
说明：显示所有插件配置信息""",
        }
        
        admin_help = {
            "sadstory_addstyle": """【/sadstory_addstyle】添加写作风格 🔒管理员
用法：/sadstory_addstyle 风格名
（换行后跟写作指令）
示例：
  /sadstory_addstyle 温柔风
  语气温柔细腻，像深夜电台主播...
说明：仅管理员可用""",
            
            "sadstory_usestyle": """【/sadstory_usestyle】启用/禁用风格
用法：/sadstory_usestyle ID
说明：ID 可通过 /sadstory_style 查看""",
            
            "sadstory_delstyle": """【/sadstory_delstyle】删除写作风格 🔒管理员
用法：/sadstory_delstyle ID
说明：ID 可通过 /sadstory_style 查看
仅管理员可用""",
            
            "sadstory_aistyle": """【/sadstory_aistyle】AI 生成写作风格
用法：/sadstory_aistyle 风格描述
示例：/sadstory_aistyle 温柔治愈风，像深夜电台主播讲故事""",
            
            "sadstory_addtpl": """【/sadstory_addtpl】添加故事模板 🔒管理员
用法：/sadstory_addtpl 模板名
（换行后跟模板内容）
示例：
  /sadstory_addtpl 校园故事
  她是有点偏执的那种...
说明：仅管理员可用""",
            
            "sadstory_usetpl": """【/sadstory_usetpl】启用/禁用模板
用法：/sadstory_usetpl ID
说明：ID 可通过 /sadstory_listtpl 查看""",
            
            "sadstory_deltpl": """【/sadstory_deltpl】删除故事模板 🔒管理员
用法：/sadstory_deltpl ID
说明：ID 可通过 /sadstory_listtpl 查看
仅管理员可用""",
            
            "sadstory_aitpl": """【/sadstory_aitpl】AI 生成故事模板
用法：/sadstory_aitpl 故事描述
示例：/sadstory_aitpl 大学毕业后才发现暗恋的人也喜欢自己""",
            
            "sadstory_reload": """【/sadstory_reload】重新加载素材群用户
用法：/sadstory_reload
说明：从配置的素材群重新获取用户列表""",
        }
        
        help_content = {**user_help, **admin_help} if is_admin else user_help
        
        if message_str and message_str in help_content:
            yield event.plain_result(help_content[message_str])
        elif message_str:
            available = ", ".join(sorted(help_content.keys()))
            yield event.plain_result(f"❌ 未找到指令 '{message_str}'\n\n可用指令：{available}\n\n输入 /sadstory_help [指令名] 查看详细用法")
        else:
            if is_admin:
                all_cmds = """【伪装聊天插件 - 指令帮助】🔒管理员

📌 基础指令
  /sadstory - 生成伪装聊天
  /sadstory_nest - 生成嵌套转发聊天

📝 模板管理
  /sadstory_listtpl - 查看模板列表
  /sadstory_addtpl - 添加模板 🔒
  /sadstory_usetpl - 启用/禁用模板
  /sadstory_deltpl - 删除模板 🔒
  /sadstory_aitpl - AI 生成模板

🎨 风格管理
  /sadstory_style - 查看风格列表
  /sadstory_addstyle - 添加风格 🔒
  /sadstory_usestyle - 启用/禁用风格
  /sadstory_delstyle - 删除风格 🔒
  /sadstory_aistyle - AI 生成风格

⚙️ 其他
  /sadstory_config - 查看配置
  /sadstory_reload - 重载用户列表

💡 输入 /sadstory_help [指令名] 查看详细用法
   示例：/sadstory_help sadstory_nest"""
            else:
                all_cmds = """【伪装聊天插件 - 使用说明】

━━━━ /sadstory ━━━━
生成一段伪装的群聊记录

用法：
  /sadstory                    随机生成一个故事
  /sadstory 校园暗恋           指定主题生成
  /sadstory @小明              指定主角
  /sadstory 校园暗恋 @小明     指定主题+主角
  /sadstory 校园暗恋 @小明 @小红   双主角模式

说明：
  • 不艾特人：随机选择主角
  • 艾特1人：该用户为主角
  • 艾特2人：双主角模式，两人互动

━━━━ /sadstory_nest ━━━━
生成嵌套转发聊天（更真实）

用法：
  /sadstory_nest @转发者 @主角
  /sadstory_nest @转发者 @主角A @主角B
  /sadstory_nest @转发者 @主角 感人的故事

说明：
  • 第一个艾特：外层转发消息的人
  • 第二个艾特起：内层故事主角
  • 最后可加主题文字

━━━━ 其他指令 ━━━━
  /sadstory_config - 查看当前配置

💡 每日使用次数有限制，管理员无限制"""
            yield event.plain_result(all_cmds)

    @filter.command("sadstory_nest")
    async def sadstory_nest(self, event: AiocqhttpMessageEvent):
        async for result in self.nest_handler.handle_nest_command(event):
            yield result

    # ==================== 人设捕捉系统 ====================

    def _extract_pure_text_from_msg(self, message_elements: list) -> str:
        text = ""
        for seg in message_elements:
            if seg.get("type") == "text":
                text += seg.get("data", {}).get("text", "")
        return text.strip()

    @filter.command("sadstory_capture")
    async def capture_persona(self, event: AiocqhttpMessageEvent):
        """抓取并总结用户人设。用法：/sadstory_capture @目标 或 /sadstory_capture QQ号 [最大抓取条数,默认50]"""
        if not await self._is_admin(event):
            yield event.plain_result("🔒 你没有权限使用这件可怕的法器（仅限系统管理员）")
            return

        raw_msg = event.message_str.partition(" ")[2].strip()
        if not raw_msg:
            yield event.plain_result("用法：/sadstory_capture @目标 或 /sadstory_capture QQ号 [提取句数(默认50)]")
            return

        at_ids = self._get_at_user_ids(event)
        target_id = None

        if at_ids:
            target_id = at_ids[0]
            raw_msg = re.sub(r'\[CQ:at,qq=\d+\]', '', raw_msg).strip()
            raw_msg = re.sub(r'\[At:\d+\]', '', raw_msg).strip()
            raw_msg = re.sub(r'@\S+', '', raw_msg).strip()
        else:
            parts = raw_msg.split()
            if parts and parts[0].isdigit():
                target_id = parts[0]
                parts = parts[1:]
                raw_msg = " ".join(parts).strip()

        if not target_id:
            yield event.plain_result("未识别到目标账号，请 @ 他或拼写正确QQ号")
            return

        target_count = 50
        if raw_msg.isdigit():
            target_count = int(raw_msg)
            if target_count < 10 or target_count > 100:
                yield event.plain_result("提取句数必须在 10 到 100 之间")
                return

        group_id = int(event.get_group_id() or "0")
        if group_id == 0:
            yield event.plain_result("此命令只能在群聊中使用")
            return

        yield event.plain_result(f"正在从群内疆狂翻找目标 {target_id} 的历史语录（目标{target_count}条），请稍候...")

        message_seq = 0
        all_texts = []
        max_rounds = 10

        for r in range(max_rounds):
            payloads = {"group_id": group_id, "count": 200}
            if message_seq != 0:
                payloads["message_seq"] = message_seq
            try:
                result = await event.bot.api.call_action("get_group_msg_history", **payloads)
                round_messages = result.get("messages", [])
                if not round_messages:
                    break
                message_seq = round_messages[0].get("message_id", 0)
                for msg in reversed(round_messages):
                    sender_id = str(msg.get("sender", {}).get("user_id", ""))
                    if sender_id == str(target_id):
                        text = self._extract_pure_text_from_msg(msg.get("message", []))
                        if text and len(text) > 1:
                            all_texts.append(text)
                            if len(all_texts) >= target_count:
                                break
                if len(all_texts) >= target_count:
                    break
            except Exception as e:
                logger.error(f"[SadStory] 获取群历史消息失败: {e}")
                break

        if not all_texts:
            yield event.plain_result(f"抱歉，往前翻找了 {(r+1)*200} 条群消息，完全没找到该用户的任何文字发言！是个究极潜水怪。")
            return

        yield event.plain_result(f"淘金成功！在往前翻了 {r+1} 页群历史后，成功提取到他的 {len(all_texts)} 句话。正在交由大模型做人格测写，预计10秒...")

        chat_history_str = "\n".join([f"他说：{t}" for t in all_texts])
        system_prompt = (
            "你是一个幽默风趣的群友画像师。你的任务是根据用户提供的数十条同一人的真实群聊历史发言，用轻松搞笑的语气概括这个人的说话风格。\n"
            "要求：\n"
            "1. 请在 100 字以内完成，语气轻松幽默，像朋友间的善意调侃，不要人身攻击或恶意侮辱。\n"
            "2. 总结内容必须包含：说话习惯/口头禅、聊天时的情绪状态、一个有趣的互联网人格标签（如话唠、冷笑话大师、表情包战士、深夜emo选手等）。\n"
            "3. 只返回画像内容，不带有任何 Markdown 符号或标题解释。"
        )

        try:
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=f"以下是这个人的一批群聊记录：\n{chat_history_str}",
                    system_prompt=system_prompt
                ),
                timeout=120.0
            )
            persona_card = llm_resp.completion_text.strip()

            info = await self._resolve_user_info(event.bot, group_id, target_id)
            nickname = info.get("nickname", target_id)

            await self.db.save_persona(str(target_id), nickname, persona_card)

            yield event.plain_result(
                f"✅ 人格夺取成功并已录入数据库！\n\n"
                f"【捕获网名】：{nickname}\n"
                f"【生成人设】：{persona_card}\n\n"
                f"该用户以后只要被你 /sadstory 抓去做主角，大模型将强行被灌输此人设，无需二次扫描！"
            )
        except Exception as e:
            logger.error(f"[SadStory] 人设总结失败: {e}")
            yield event.plain_result(f"人格测写失败: 大模型抽风了或超时 ({e})")

    @filter.command("sadstory_listp")
    async def list_personas(self, event: AiocqhttpMessageEvent):
        """列出所有保存在数据库中的灵魂人设"""
        if not await self._is_admin(event):
            yield event.plain_result("🔒 仅管理员可查看人设档案。")
            return
        try:
            personas = await self.db.get_all_personas()
            if not personas:
                yield event.plain_result("当前人设库没有任何档案。请使用 /sadstory_capture 捕捉。")
                return
            lines = [f"🗂️ 独家人设档案室（共 {len(personas)} 份）"]
            for pid, nick, card in personas:
                preview = card[:30] + "..." if len(card) > 30 else card
                lines.append(f"👤 [{pid}] {nick} -> {preview}")
            lines.append("以后这些人当主角必定触发人格附体。")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[SadStory] 获取人设列表失败: {e}")
            yield event.plain_result(f"查询失败: {e}")

    @filter.command("sadstory_delp")
    async def delete_persona(self, event: AiocqhttpMessageEvent):
        """删除某个被困在数据库里的人设。用法：/sadstory_delp QQ号 或 @某人"""
        if not await self._is_admin(event):
            yield event.plain_result("🔒 仅管理员可释放人设档案。")
            return
        raw = event.message_str.partition(" ")[2].strip()
        at_ids = self._get_at_user_ids(event)
        target_id = at_ids[0] if at_ids else raw.split()[0] if raw else ""
        if not target_id:
            yield event.plain_result("用法：/sadstory_delp QQ号 或 @某人")
            return
        success = await self.db.delete_persona(str(target_id))
        if success:
            yield event.plain_result(f"成功将 QQ {target_id} 的灵魂解绑，他终于自由了！下次生成使用默认性格。")
        else:
            yield event.plain_result(f"数据库中没有找到 QQ {target_id} 的人设记录。")
