import json
import os
import random
import re
import time
from pathlib import Path

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import At, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.star_tools import StarTools

from astrbot.api import AstrBotConfig
from .db import SadStoryDB

# 插件目录（用于读取故事模板）
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(PLUGIN_DIR, "templates")

# QQ Face 表情映射：中文名 -> face id
# 参考 OneBot v11 标准 QQ 表情 ID
FACE_MAP = {
    # 伤感类
    "流泪": 5, "哭": 5, "大哭": 9, "难过": 15, "委屈": 106,
    "心碎": 67, "伤心": 5, "痛哭": 9, "哭泣": 5, "快哭了": 107,
    "飙泪": 210,
    # 叹气/无奈
    "叹气": 34, "无奈": 34, "叹息": 34, "唉": 34, "衰": 34,
    # 笑
    "微笑": 14, "笑": 14, "偷笑": 18, "呲牙": 13, "笑哭": 176,
    "苦笑": 176, "尴尬": 10, "捂脸": 180, "憨笑": 26,
    "坏笑": 101, "奸笑": 178,
    # 社交
    "抱抱": 134, "拥抱": 134, "亲亲": 109,
    "握手": 78, "强": 136, "赞": 76, "点赞": 76,
    "鼓掌": 99, "OK": 146, "ok": 146,
    "胜利": 139, "拳头": 142,
    # 思考/沉默
    "沉默": 39, "沉思": 39, "思考": 30, "想": 30,
    "疑问": 30, "问号": 30,
    # 惊讶
    "震惊": 0, "惊讶": 0, "吃惊": 0, "卧槽": 0,
    "惊恐": 24, "吓": 110,
    # 其他情绪
    "发呆": 3, "呆": 3,
    "害羞": 6, "害怕": 24, "恐惧": 24,
    "生气": 11, "怒": 11, "愤怒": 11, "发怒": 11,
    "鄙视": 105, "白眼": 20,
    "阴险": 108,
    # 告别/动作
    "再见": 36, "拜拜": 36,
    # 物品/自然
    "玫瑰": 63, "花": 63, "凋谢": 64,
    "月亮": 75, "太阳": 74,
    "爱心": 66, "心": 66, "红心": 66,
    "礼物": 69,
    "咖啡": 60, "啤酒": 113,
    # 状态
    "晕": 32, "头晕": 32,
    "睡": 8, "困": 23, "睡觉": 8, "哈欠": 104,
    "奋斗": 28, "加油": 28,
    "可怜": 111, "祈祷": 111,
    "冷汗": 96, "流汗": 25, "擦汗": 97,
    "抠鼻": 98,
}

# LLM Prompt 模板 — 口语化风格
STORY_PROMPT_CASUAL = """你是一个伪装聊天创作者。请根据以下要求生成一段伪装聊天，模拟QQ群里有人连续发消息讲故事的场景。

角色列表：
- 主角（讲故事的人）：{protagonist}
- 围观网友（偶尔插嘴）：{bystanders}

风格参考（非常重要，请仔细模仿）：
- 主角一条一条地发消息讲故事，每条消息就1-2句话，很短很碎，像在群里打字聊天
- 语气口语化、随意，像真人在群里讲自己的经历，不要文学腔
- 可以有"我就这样"、"就很诡异"、"太痛苦了"这种口头禅式的短句
- 可以有自嘲、吐槽、情绪爆发的段落
- 围观网友只是偶尔插嘴，大部分消息都是主角在讲，网友评论不要太多（总共3-6条就够了）
- 网友的反应要自然：比如"卧槽"、"然后呢"、"破防了"、"你怎么不追上去啊"、"哭了"这种
- 故事要有完整的起承转合，结尾要有余韵，让人意难平
- 主角偶尔可以 @ 某个围观网友说"别跟别人说"之类的，增加真实感
{emoji_instruction}
{theme_line}
{reference_section}
总消息条数控制在 {min_msg} 到 {max_msg} 条之间，其中主角的消息占绝大多数。

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""

# LLM Prompt 模板 — 文学风格
STORY_PROMPT_LITERARY = """你是一个伪装聊天创作者。请根据以下要求生成一段伪装聊天，模拟QQ群里有人连续发消息讲故事的场景。

角色列表：
- 主角（讲故事的人）：{protagonist}
- 围观网友（偶尔插嘴）：{bystanders}

风格要求：
- 主角一条一条地发消息讲故事，每条消息1-3句话
- 语言优美、细腻，带有文学色彩，注重意境和情感描写
- 善用比喻、意象，营造氛围感
- 围观网友偶尔插嘴，大部分消息都是主角在讲，网友评论不要太多（总共3-6条就够了）
- 网友的反应要真诚：比如"后来呢"、"太难过了"、"抱抱你"、"看哭了"这种
- 故事要有完整的起承转合，结尾要有余韵，让人意难平
{emoji_instruction}
{theme_line}
{reference_section}
总消息条数控制在 {min_msg} 到 {max_msg} 条之间，其中主角的消息占绝大多数。

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""

# 表情使用说明（注入到 prompt 中）
EMOJI_INSTRUCTION = """- 可以在台词中适当插入QQ表情来增加真实感，格式为 [表情:名称]
- 可用的表情：流泪、大哭、难过、委屈、心碎、快哭了、飙泪、叹气、无奈、衰、微笑、偷笑、呲牙、笑哭、苦笑、捂脸、憨笑、抱抱、亲亲、握手、赞、鼓掌、OK、思考、疑问、震惊、惊恐、吓、发呆、害羞、生气、鄙视、白眼、再见、玫瑰、凋谢、爱心、啤酒、咖啡、晕、睡、困、哈欠、奋斗、可怜、冷汗、擦汗
- 表情不要太多，大约每5-8条消息穿插1个就够了，要自然
- 有些消息可以只发一个表情不带文字，比如围观网友回复一个 [表情:流泪]
- 示例："我当时真的绷不住了[表情:大哭]"、"[表情:抱抱]"、"后来就再也没见过她[表情:叹气]"
"""

# LLM Prompt 模板 — 双主角口语化风格
STORY_PROMPT_DUAL_CASUAL = """你是一个伪装聊天创作者。请根据以下要求生成一段伪装聊天，模拟QQ群里两个人在群里互动聊天的场景。

角色列表：
- 主角A：{protagonist_a}
- 主角B：{protagonist_b}
- 围观网友（偶尔插嘴）：{bystanders}

风格参考（非常重要，请仔细模仿）：
- 两个主角在群里你一句我一句地聊天、互动、讲故事
- 每条消息就1-2句话，很短很碎，像在群里打字聊天
- 语气口语化、随意，像真人在群里对话
- 两人之间可以有调侃、吐槽、回忆、感慨等互动
- 围观网友只是偶尔插嘴，大部分消息都是两个主角在互动，网友评论不要太多（总共3-6条就够了）
- 网友的反应要自然：比如"你俩好甜"、"磕到了"、"然后呢"、"破防了"这种
- 故事要有完整的起承转合，结尾要有余韵
{emoji_instruction}
{theme_line}
{reference_section}
总消息条数控制在 {min_msg} 到 {max_msg} 条之间，其中两个主角的消息占绝大多数。

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""

# LLM Prompt 模板 — 双主角文学风格
STORY_PROMPT_DUAL_LITERARY = """你是一个伪装聊天创作者。请根据以下要求生成一段伪装聊天，模拟QQ群里两个人在群里深夜对话的场景。

角色列表：
- 主角A：{protagonist_a}
- 主角B：{protagonist_b}
- 围观网友（偶尔插嘴）：{bystanders}

风格参考（非常重要，请仔细模仿）：
- 两个主角在群里你一句我一句地对话，像深夜里两个人在倾诉
- 每条消息1-3句话，文字细腻、有画面感
- 语气温柔、克制，带着回忆和感慨的味道
- 两人之间有默契、有试探、有欲言又止的感觉
- 围观网友偶尔插嘴，反应要真诚：比如"后来呢"、"太难过了"、"看哭了"这种
- 故事要有完整的起承转合，结尾要有余韵，让人意难平
{emoji_instruction}
{theme_line}
{reference_section}
总消息条数控制在 {min_msg} 到 {max_msg} 条之间，其中两个主角的消息占绝大多数。

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""


@register("astrbot_plugin_sadstory", "Towqs", "伪装聊天插件 - 以合并转发形式在群聊中展示伪装聊天", "0.5.8")
class SadStoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.user_pool = []
        self.group_users = []
        self.cooldown_map = {}
        data_dir = StarTools.get_data_dir("astrbot_plugin_sadstory")
        self.db = SadStoryDB(Path(data_dir) / "sadstory.db")

    async def initialize(self):
        await self.db.init()
        self._reload_config()
        await self._import_webui_data()
        await self._import_file_templates()
        logger.info(f"[SadStory] 插件初始化完成，主讲人: {len(self.custom_protagonists)}个, 网友: {len(self.custom_bystanders)}个")

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
        self.cooldown_seconds = self._parse_int(cfg.get("cooldown_seconds", ""), 60)
        self.story_min_messages = self._parse_int(cfg.get("story_min_messages", ""), 30)
        self.story_max_messages = self._parse_int(cfg.get("story_max_messages", ""), 80)
        self.bystander_count = self._parse_int(cfg.get("bystander_count", ""), 3)
        self.chat_provider_id = str(cfg.get("chat_provider_id", "")).strip()
        self.use_virtual_users = self._parse_bool(cfg.get("use_virtual_users", False))
        self.use_story_template = self._parse_bool(cfg.get("use_story_template", True))
        self.use_face_emoji = self._parse_bool(cfg.get("use_face_emoji", True))
        self.use_casual_style = self._parse_bool(cfg.get("use_casual_style", True))

        # 解析允许使用的QQ号列表
        raw_allowed = cfg.get("allowed_user_list", [])
        self.allowed_users = set()
        if isinstance(raw_allowed, list):
            for item in raw_allowed:
                qq = str(item).strip()
                if qq:
                    self.allowed_users.add(qq)

        # 解析主讲人QQ号列表
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

        logger.info(f"[SadStory] 配置加载: 主讲人={len(self.custom_protagonists)}, 网友={len(self.custom_bystanders)}, 素材群={self.source_group_id}")
        # 合并用户池
        self.user_pool = self.custom_protagonists + self.custom_bystanders + self.group_users

    async def _import_webui_data(self):
        """从 WebUI 的 template_list 配置导入写作风格和故事模板到数据库，导入后清空"""
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
                    await self.db.add_template(name, content, enabled=True)
                    imported += 1
            except Exception as e:
                logger.warning(f"[SadStory] 导入文件模板 {fname} 失败: {e}")
        if imported:
            logger.info(f"[SadStory] 从 templates/ 目录导入了 {imported} 个文件模板到数据库")

    @staticmethod
    def _parse_int(s, default: int = 0) -> int:
        try:
            return int(s) if s is not None and str(s).strip() else default
        except (ValueError, TypeError):
            return default

    # ==================== 用户池管理 ====================

    async def _fetch_group_users(self, bot, group_id: int) -> list:
        try:
            members = await bot.get_group_member_list(group_id=group_id)
            users = []
            for m in members:
                uid = str(m.get("user_id", ""))
                nickname = m.get("card", "") if self.use_card_as_name else ""
                if not nickname:
                    nickname = m.get("nickname", f"用户{uid[-4:]}")
                users.append({"nickname": nickname, "user_id": uid})
            logger.info(f"[SadStory] 从群 {group_id} 获取到 {len(users)} 个用户")
            return users
        except Exception as e:
            logger.error(f"[SadStory] 获取群成员列表失败: {e}")
            return []

    def _resolve_qq_lists(self, all_members: list):
        """根据群成员列表补充自定义角色的昵称（如果未手动填写）"""
        member_map = {u["user_id"]: u for u in all_members}

        for user in self.custom_protagonists + self.custom_bystanders:
            if not user["nickname"] and user["user_id"] in member_map:
                user["nickname"] = member_map[user["user_id"]]["nickname"]
            if not user["nickname"]:
                user["nickname"] = f"用户{user['user_id'][-4:]}"

        # 重新合并用户池
        self.user_pool = self.custom_protagonists + self.custom_bystanders + self.group_users

    def _get_available_users(self) -> list:
        if self.user_pool:
            return self.user_pool
        # 虚拟模式：返回预设假角色（灰色头像）
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

    def _check_cooldown(self, group_id: str) -> bool:
        if self.cooldown_seconds <= 0:
            return True
        last = self.cooldown_map.get(group_id, 0)
        return (time.time() - last) >= self.cooldown_seconds

    def _set_cooldown(self, group_id: str):
        self.cooldown_map[group_id] = time.time()

    def _check_permission(self, event: AiocqhttpMessageEvent) -> bool:
        """检查用户是否有权限使用指令。列表为空则所有人可用。"""
        if not self.allowed_users:
            return True
        sender_id = str(event.get_sender_id())
        return sender_id in self.allowed_users

    # ==================== Prompt 风格管理 ====================

    async def _get_active_prompt_style(self, dual_mode: bool = False) -> str:
        """从数据库已启用的风格中随机选一个，没有则回退到内置默认"""
        enabled = await self.db.get_enabled_styles()
        if enabled:
            return random.choice(enabled)
        if dual_mode:
            return STORY_PROMPT_DUAL_CASUAL if self.use_casual_style else STORY_PROMPT_DUAL_LITERARY
        return STORY_PROMPT_CASUAL if self.use_casual_style else STORY_PROMPT_LITERARY


    # ==================== 故事生成 ====================

    def _get_at_user_ids(self, event: AiocqhttpMessageEvent) -> list[str]:
        """从消息中获取被 @ 的用户 ID 列表（最多2个）"""
        ids = []
        all_segs = event.get_messages()
        logger.debug(f"[SadStory] 消息段列表: {[(type(s).__name__, getattr(s, 'qq', None)) for s in all_segs]}")
        for seg in all_segs:
            if isinstance(seg, At) and str(seg.qq) != event.get_self_id():
                ids.append(str(seg.qq))
                if len(ids) >= 2:
                    break
        # 没有 @ 时，回退到引用消息
        if not ids:
            for seg in all_segs:
                if isinstance(seg, Reply) and seg.sender_id:
                    ids.append(str(seg.sender_id))
                    break
        logger.debug(f"[SadStory] 解析到的 at_ids: {ids}")
        return ids


    async def _resolve_user_info(self, bot, group_id: int, user_id: str) -> dict:
        """根据 user_id 获取昵称信息"""
        try:
            info = await bot.get_group_member_info(group_id=group_id, user_id=int(user_id))
            if info:
                nickname = info.get("card", "") or info.get("nickname", "") or f"用户{user_id[-4:]}"
                return {"nickname": nickname, "user_id": user_id}
        except Exception:
            pass
        return {"nickname": f"用户{user_id[-4:]}", "user_id": user_id}

    async def _generate_story(self, event: AiocqhttpMessageEvent, theme: str = "", forced_protagonists: list[dict] | None = None) -> list:
        users = list(self._get_available_users())  # 拷贝，避免 shuffle 污染共享状态
        if len(users) < 2:
            return []

        dual_mode = forced_protagonists is not None and len(forced_protagonists) == 2

        # 双主角模式
        if dual_mode:
            protagonist_a, protagonist_b = forced_protagonists[0], forced_protagonists[1]
            other_users = [u for u in users if u["user_id"] not in {protagonist_a["user_id"], protagonist_b["user_id"]}]
        # 单主角模式（强制指定）
        elif forced_protagonists and len(forced_protagonists) == 1:
            protagonist = forced_protagonists[0]
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
        # 单主角模式（配置指定）
        elif self.custom_protagonists:
            protagonist = random.choice(self.custom_protagonists)
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
        # 单主角模式（随机）
        else:
            random.shuffle(users)
            protagonist = users[0]
            other_users = users[1:]

        bystander_count = max(1, min(self.bystander_count, len(other_users)))  # 至少1个旁观者
        if not other_users:
            return []
        random.shuffle(other_users)
        bystanders = other_users[:bystander_count]

        bystander_names = "、".join([u["nickname"] for u in bystanders])
        theme_line = f"6. 故事主题/关键词：{theme}" if theme else ""

        templates = []
        if self.use_story_template:
            templates = await self.db.get_enabled_templates()
        reference_section = ""
        if templates:
            ref = random.choice(templates)
            if len(ref) > 2000:
                ref = ref[:2000] + "\n...(省略)"
            ref = ref.replace("{", "{{").replace("}", "}}")
            reference_section = f"""
以下是一个参考故事的风格示例（请参考其叙事风格和情感表达，但不要抄袭内容，要创作全新的故事）：
---
{ref}
---
"""

        story_prompt = await self._get_active_prompt_style(dual_mode=dual_mode)

        # 构建格式化变量
        if dual_mode:
            format_vars = {
                "protagonist_a": protagonist_a["nickname"],
                "protagonist_b": protagonist_b["nickname"],
                "bystanders": bystander_names,
                "min_msg": self.story_min_messages,
                "max_msg": self.story_max_messages,
                "theme_line": theme_line,
                "reference_section": reference_section,
                "emoji_instruction": EMOJI_INSTRUCTION if self.use_face_emoji else "",
            }
        else:
            format_vars = {
                "protagonist": protagonist["nickname"],
                "bystanders": bystander_names,
                "min_msg": self.story_min_messages,
                "max_msg": self.story_max_messages,
                "theme_line": theme_line,
                "reference_section": reference_section,
                "emoji_instruction": EMOJI_INSTRUCTION if self.use_face_emoji else "",
            }

        try:
            prompt = story_prompt.format_map(
                type("SafeDict", (dict,), {"__missing__": lambda self, key: f"{{{key}}}"})
                (format_vars)
            )
        except Exception as e:
            logger.warning(f"[SadStory] 风格模板格式化失败，回退到内置风格: {e}")
            if dual_mode:
                fallback = STORY_PROMPT_DUAL_CASUAL if self.use_casual_style else STORY_PROMPT_DUAL_LITERARY
            else:
                fallback = STORY_PROMPT_CASUAL if self.use_casual_style else STORY_PROMPT_LITERARY
            prompt = fallback.format(**format_vars)

        try:
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(
                    event.unified_msg_origin
                )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            raw = llm_resp.completion_text.strip()

            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                logger.error("[SadStory] LLM 输出中未找到 JSON 数组")
                return []

            story_data = json.loads(raw[start:end])

            # 构建角色映射
            if dual_mode:
                role_map = {
                    protagonist_a["nickname"]: protagonist_a,
                    protagonist_b["nickname"]: protagonist_b,
                }
                fallback_user = protagonist_a
            else:
                role_map = {protagonist["nickname"]: protagonist}
                fallback_user = protagonist
            for b in bystanders:
                role_map[b["nickname"]] = b

            messages = []
            for item in story_data:
                speaker = item.get("speaker", "")
                content = item.get("content", "")
                if not speaker or not content:
                    continue
                user_info = role_map.get(speaker, fallback_user)
                messages.append({
                    "nickname": user_info["nickname"],
                    "user_id": user_info["user_id"],
                    "content": content,
                })
            return messages

        except json.JSONDecodeError as e:
            logger.error(f"[SadStory] JSON 解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 生成故事失败: {e}")
            return []


    # ==================== 合并转发构建 ====================

    @staticmethod
    def _parse_content_segments(content: str) -> list:
        """将含有 [表情:xxx] 标记的文本解析为消息段数组"""
        segments = []
        pattern = r'\[表情[:：]([^\]]+)\]'
        last_end = 0

        for match in re.finditer(pattern, content):
            before = content[last_end:match.start()]
            if before:
                segments.append({"type": "text", "data": {"text": before}})
            face_name = match.group(1).strip()
            face_id = FACE_MAP.get(face_name)
            if face_id is not None:
                segments.append({"type": "face", "data": {"id": str(face_id)}})
            else:
                segments.append({"type": "text", "data": {"text": match.group(0)}})
            last_end = match.end()

        remaining = content[last_end:]
        if remaining:
            segments.append({"type": "text", "data": {"text": remaining}})
        if not segments:
            segments.append({"type": "text", "data": {"text": content}})
        return segments

    def _build_forward_nodes(self, messages: list) -> list:
        nodes = []
        for msg in messages:
            if self.use_face_emoji:
                content_segments = self._parse_content_segments(msg["content"])
            else:
                content_segments = [{"type": "text", "data": {"text": msg["content"]}}]
            nodes.append({
                "type": "node",
                "data": {
                    "user_id": str(msg["user_id"]),
                    "nickname": msg["nickname"],
                    "content": content_segments,
                }
            })
        return nodes

    # ==================== 命令处理 ====================

    @filter.command("sadstory")
    async def sadstory(self, event: AiocqhttpMessageEvent):
        """发送一段伪装聊天（合并转发形式）。用法：/sadstory [主题]"""
        self._reload_config()

        if not self._check_permission(event):
            return

        await self._import_webui_data()

        group_id_str = event.get_group_id()
        if not group_id_str or group_id_str == "0":
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        if not self._check_cooldown(group_id_str):
            yield event.plain_result(f"太快了，休息一下吧~ ({self.cooldown_seconds}秒冷却)")
            return

        self._set_cooldown(group_id_str)  # 通过检查后立即预占冷却

        theme = event.message_str.partition(" ")[2].strip()
        if len(theme) > 100:
            theme = theme[:100]

        # 检查是否 @ 或引用了某人作为主角
        forced_protagonists = []
        at_ids = self._get_at_user_ids(event)
        if at_ids:
            for uid in at_ids:
                info = await self._resolve_user_info(event.bot, int(group_id_str), uid)
                forced_protagonists.append(info)
            # 从 theme 中去掉 @ 部分的文本残留
            theme = re.sub(r'@\S+\s*', '', theme).strip()

        # 虚拟模式下跳过素材群拉取
        if not self.use_virtual_users:
            # 如果素材群有配置且用户池为空，尝试拉取
            if self.source_group_id and not self.group_users:
                fetched = await self._fetch_group_users(event.bot, self.source_group_id)
                if fetched:
                    self.group_users = fetched
                    self._resolve_qq_lists(fetched)

            # 如果用户池仍为空，从当前群拉取真实成员
            if not self.user_pool:
                fetched = await self._fetch_group_users(event.bot, int(group_id_str))
                if fetched:
                    self.group_users = fetched
                    self._resolve_qq_lists(fetched)

        logger.info(f"[SadStory] 当前用户池大小: {len(self.user_pool)}, 虚拟模式: {self.use_virtual_users}")

        yield event.plain_result("正在生成伪装聊天，请稍候...")

        # 确保所有强制主角都在用户池中
        for p in forced_protagonists:
            if not any(u["user_id"] == p["user_id"] for u in self.user_pool):
                self.user_pool.append(p)

        messages = await self._generate_story(event, theme, forced_protagonists or None)
        if not messages:
            yield event.plain_result("生成失败了，可能是用户池不足（至少需要2人）或 LLM 服务暂时不可用，请稍后再试~")
            return

        nodes = self._build_forward_nodes(messages)
        try:
            await event.bot.send_group_forward_msg(
                group_id=int(group_id_str),
                messages=nodes,
            )
        except Exception as e:
            logger.error(f"[SadStory] 发送合并转发失败: {e}")
            yield event.plain_result(f"发送失败了: {e}")

    @filter.command("sadstory_reload")
    async def reload_users(self, event: AiocqhttpMessageEvent):
        """重新加载素材群用户列表。用法：/sadstory_reload"""
        self._reload_config()

        if not self._check_permission(event):
            return

        if not self.source_group_id:
            yield event.plain_result("未配置素材群，请先在 WebUI 插件配置中设置素材群群号")
            return

        fetched = await self._fetch_group_users(event.bot, self.source_group_id)
        if fetched:
            self.group_users = fetched
            self._resolve_qq_lists(fetched)
            yield event.plain_result(f"用户池已刷新，当前共 {len(self.user_pool)} 个用户")
        else:
            yield event.plain_result("刷新失败，请检查素材群号是否正确以及机器人是否在群内")

    @filter.command("sadstory_addtpl")
    async def add_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """添加故事模板。用法：/sadstory_addtpl 模板名（换行后跟模板内容）"""
        if not self._check_permission(event):
            return
        raw = event.message_str
        # 去掉命令名，取第一个空格后的内容
        after_cmd = raw.partition(" ")[2]
        parts = after_cmd.split("\n", 1)
        first_line = parts[0].strip()
        content = parts[1].strip() if len(parts) > 1 else ""

        if not first_line:
            yield event.plain_result("用法：/sadstory_addtpl 模板名\n（换行后跟模板内容）\n\n示例：\n/sadstory_addtpl 校园故事\n她是有点偏执的那种...")
            return

        if not content:
            yield event.plain_result("模板内容不能为空，请在模板名后换行输入故事内容")
            return

        tpl_id = await self.db.add_template(first_line, content)
        yield event.plain_result(f"模板「{first_line}」已保存到数据库（ID:{tpl_id}，{len(content)}字）")

    @filter.command("sadstory_listtpl")
    async def list_templates(self, event: AiocqhttpMessageEvent):
        """查看所有故事模板。用法：/sadstory_listtpl"""
        if not self._check_permission(event):
            return
        self._reload_config()
        db_tpls = await self.db.get_templates()

        if not db_tpls:
            yield event.plain_result("暂无故事模板\n用 /sadstory_addtpl 添加")
            return

        lines = [f"📝 故事模板列表（共{len(db_tpls)}个）："]
        for tpl_id, name, enabled, content in db_tpls:
            status = "✅" if enabled else "❌"
            preview = content[:40].replace("\n", " ") + ("..." if len(content) > 40 else "")
            lines.append(f"  {status} [{tpl_id}] {name}（{len(content)}字）：{preview}")

        lines.append(f"\n模板参考当前{'已启用 ✅' if self.use_story_template else '已关闭 ❌'}")
        lines.append("用 /sadstory_usetpl ID 切换启用状态")
        yield event.plain_result("\n".join(lines))

    @filter.command("sadstory_usetpl")
    async def use_template(self, event: AiocqhttpMessageEvent):
        """启用/禁用指定模板。用法：/sadstory_usetpl ID"""
        if not self._check_permission(event):
            return
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_usetpl ID\n（ID 可通过 /sadstory_listtpl 查看方括号内的数字）")
            return
        try:
            tpl_id = int(arg)
        except ValueError:
            yield event.plain_result("请输入模板 ID（数字）")
            return
        result = await self.db.toggle_template(tpl_id)
        if not result:
            yield event.plain_result(f"ID {tpl_id} 不存在，用 /sadstory_listtpl 查看列表")
            return
        name, new_enabled = result
        status = "已启用 ✅" if new_enabled else "已禁用 ❌"
        yield event.plain_result(f"模板「{name}」{status}")

    @filter.command("sadstory_deltpl")
    async def delete_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """删除故事模板。用法：/sadstory_deltpl ID"""
        if not self._check_permission(event):
            return
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_deltpl ID\n（ID 可通过 /sadstory_listtpl 查看方括号内的数字）")
            return
        try:
            tpl_id = int(arg)
        except ValueError:
            yield event.plain_result("请输入模板 ID（数字）")
            return
        name = await self.db.delete_template(tpl_id)
        if name:
            yield event.plain_result(f"模板「{name}」已删除")
        else:
            yield event.plain_result(f"ID {tpl_id} 不存在，用 /sadstory_listtpl 查看列表")

    # ==================== 配置预览与风格指令 ====================

    @filter.command("sadstory_config")
    async def show_config(self, event: AiocqhttpMessageEvent):
        """查看当前所有配置。用法：/sadstory_config"""
        if not self._check_permission(event):
            return
        self._reload_config()
        lines = []
        lines.append("📋 伪装聊天 当前配置")
        lines.append("─────────────────")
        lines.append(f"消息条数：{self.story_min_messages} ~ {self.story_max_messages}")
        lines.append(f"围观网友数：{self.bystander_count}")
        lines.append(f"冷却时间：{self.cooldown_seconds}秒")
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

    @filter.command("sadstory_style")
    async def show_styles(self, event: AiocqhttpMessageEvent):
        """查看写作风格列表。用法：/sadstory_style"""
        if not self._check_permission(event):
            return
        styles = await self.db.get_styles()
        lines = []
        if styles:
            en = sum(1 for _, _, e, _ in styles if e)
            lines.append(f"🎨 写作风格（共{len(styles)}个，启用{en}个）：")
            for sid, name, enabled, content in styles:
                status = "✅" if enabled else "❌"
                preview = content[:60].replace("\n", "↵ ") + ("..." if len(content) > 60 else "")
                lines.append(f"  [{sid}] {status} {name}：{preview}")
            lines.append("\n生成时从已启用的风格中随机选取")
        else:
            fallback = "口语化" if self.use_casual_style else "文学"
            lines.append(f"🎨 写作风格：未配置，使用内置{fallback}风格")
            lines.append("用 /sadstory_addstyle 添加自定义风格")
        yield event.plain_result("\n".join(lines))

    @filter.command("sadstory_addstyle")
    async def add_style(self, event: AiocqhttpMessageEvent):
        """添加写作风格。用法：/sadstory_addstyle 风格名（换行后跟内容）"""
        if not self._check_permission(event):
            return
        raw = event.message_str
        after_cmd = raw.partition(" ")[2]
        parts = after_cmd.split("\n", 1)
        first_line = parts[0].strip()
        content = parts[1].strip() if len(parts) > 1 else ""
        if not first_line:
            yield event.plain_result(
                "用法：/sadstory_addstyle 风格名\n（换行后跟写作指令）\n\n"
                "可用变量：{protagonist} {bystanders} {min_msg} {max_msg}\n"
                "  {theme_line} {reference_section} {emoji_instruction}\n\n"
                "提示：末尾记得加 JSON 输出格式要求"
            )
            return
        if not content:
            yield event.plain_result("写作指令不能为空，请在风格名后换行输入")
            return
        sid = await self.db.add_style(first_line, content)
        yield event.plain_result(f"风格「{first_line}」已保存（ID:{sid}，{len(content)}字）")

    @filter.command("sadstory_usestyle")
    async def toggle_style(self, event: AiocqhttpMessageEvent):
        """启用/禁用写作风格。用法：/sadstory_usestyle ID"""
        if not self._check_permission(event):
            return
        logger.debug(f"[SadStory] sadstory_usestyle message_str={event.message_str!r}")
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_usestyle ID\n（ID 可通过 /sadstory_style 查看方括号内的数字）")
            return
        try:
            sid = int(arg)
        except ValueError:
            yield event.plain_result("请输入风格 ID（数字）")
            return
        result = await self.db.toggle_style(sid)
        if not result:
            yield event.plain_result(f"ID {sid} 不存在，用 /sadstory_style 查看列表")
            return
        name, new_enabled = result
        status = "已启用 ✅" if new_enabled else "已禁用 ❌"
        enabled_styles = await self.db.get_enabled_styles()
        fallback_hint = ""
        if not enabled_styles:
            fallback_hint = f"\n\n⚠️ 当前没有启用的风格，将使用内置{'口语化' if self.use_casual_style else '文学'}风格"
        yield event.plain_result(f"风格「{name}」{status}{fallback_hint}")

    @filter.command("sadstory_delstyle")
    async def delete_style(self, event: AiocqhttpMessageEvent):
        """删除写作风格。用法：/sadstory_delstyle ID"""
        if not self._check_permission(event):
            return
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_delstyle ID\n（ID 可通过 /sadstory_style 查看）")
            return
        try:
            sid = int(arg)
        except ValueError:
            yield event.plain_result("请输入风格 ID（数字）")
            return
        name = await self.db.delete_style(sid)
        if name:
            yield event.plain_result(f"风格「{name}」已删除")
        else:
            yield event.plain_result(f"ID {sid} 不存在")

    # ==================== LLM 工具调用 ====================

    @filter.command("sadstory_aistyle")
    async def ai_add_style(self, event: AiocqhttpMessageEvent):
        """让 AI 生成并写入写作风格。用法：/sadstory_aistyle 风格描述"""
        if not self._check_permission(event):
            return
        desc = event.message_str.partition(" ")[2].strip()
        if not desc:
            yield event.plain_result(
                "用法：/sadstory_aistyle 风格描述\n"
                "示例：/sadstory_aistyle 温柔治愈风，像深夜电台主播讲故事\n"
                "AI 会根据描述自动生成符合规范的写作风格并写入数据库"
            )
            return

        yield event.plain_result("正在让 AI 生成写作风格，请稍候...")

        gen_prompt = (
            "你是伪装聊天插件的写作风格生成助手。请根据用户描述生成一个完整的写作风格 prompt。\n\n"
            "写作风格 prompt 的规范：\n"
            "1. 必须包含占位变量：{protagonist}（主角名）、{bystanders}（围观网友名）、{min_msg}（最少消息数）、{max_msg}（最多消息数）\n"
            "2. 可选变量：{theme_line}（主题行）、{reference_section}（参考故事段）、{emoji_instruction}（表情说明）\n"
            "3. 需要描述角色列表、风格要求、消息条数控制\n"
            '4. 末尾必须要求输出 JSON 数组格式：[{{"speaker": "角色名", "content": "台词内容"}}, ...]\n\n'
            "请严格按以下 JSON 格式输出，不要输出任何其他内容：\n"
            '{"style_name": "风格名称（简短）", "style_content": "完整的写作指令内容"}\n\n'
            f"用户描述：{desc}"
        )

        try:
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
            llm_resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=gen_prompt)
            raw = llm_resp.completion_text.strip()
            # 提取 JSON
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                yield event.plain_result("AI 生成的内容格式异常，请重试")
                return
            data = json.loads(raw[start:end])
            style_name = str(data.get("style_name", "")).strip()
            style_content = str(data.get("style_content", "")).strip()
            if not style_name or not style_content:
                yield event.plain_result("AI 生成的风格名称或内容为空，请重试")
                return
            # 校验必需占位符
            required = ["{protagonist}", "{bystanders}", "{min_msg}", "{max_msg}"]
            missing = [v for v in required if v not in style_content]
            if missing:
                yield event.plain_result(f"AI 生成的风格缺少必需变量 {', '.join(missing)}，请重试或手动添加")
                return
            sid = await self.db.add_style(style_name, style_content)
            yield event.plain_result(f"风格「{style_name}」已写入数据库（ID:{sid}，{len(style_content)}字）")
        except json.JSONDecodeError:
            logger.error("[SadStory] AI 生成风格 JSON 解析失败")
            yield event.plain_result("AI 生成的内容无法解析，请重试")
        except Exception as e:
            logger.error(f"[SadStory] AI 生成风格失败: {e}")
            yield event.plain_result(f"AI 生成失败: {e}")

    @filter.command("sadstory_aitpl")
    async def ai_add_template(self, event: AiocqhttpMessageEvent):
        """让 AI 生成并写入故事模板。用法：/sadstory_aitpl 故事描述"""
        if not self._check_permission(event):
            return
        desc = event.message_str.partition(" ")[2].strip()
        if not desc:
            yield event.plain_result(
                "用法：/sadstory_aitpl 故事描述\n"
                "示例：/sadstory_aitpl 大学毕业后才发现暗恋的人也喜欢自己\n"
                "AI 会根据描述生成一篇完整的故事模板并写入数据库"
            )
            return

        yield event.plain_result("正在让 AI 生成故事模板，请稍候...")

        gen_prompt = (
            "你是伪装聊天插件的故事模板生成助手。请根据用户描述创作一篇完整的伪装聊天范文。\n\n"
            "故事模板的规范：\n"
            "1. 模拟QQ群聊天的形式，主角一条一条发消息讲故事\n"
            "2. 穿插围观网友的评论和反应\n"
            "3. 故事要有完整的起承转合，情感真挚\n"
            "4. 结尾要有余韵，让人意难平\n"
            "5. 内容至少200字以上\n\n"
            "请严格按以下 JSON 格式输出，不要输出任何其他内容：\n"
            '{"tpl_name": "模板名称（简短概括主题）", "tpl_content": "完整的故事范文内容"}\n\n'
            f"用户描述：{desc}"
        )

        try:
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
            llm_resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=gen_prompt)
            raw = llm_resp.completion_text.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                yield event.plain_result("AI 生成的内容格式异常，请重试")
                return
            data = json.loads(raw[start:end])
            tpl_name = str(data.get("tpl_name", "")).strip()
            tpl_content = str(data.get("tpl_content", "")).strip()
            if not tpl_name or not tpl_content:
                yield event.plain_result("AI 生成的模板名称或内容为空，请重试")
                return
            if len(tpl_content) < 50:
                yield event.plain_result("AI 生成的故事模板内容太短，请重试")
                return
            tpl_id = await self.db.add_template(tpl_name, tpl_content)
            yield event.plain_result(f"故事模板「{tpl_name}」已写入数据库（ID:{tpl_id}，{len(tpl_content)}字）")
        except json.JSONDecodeError:
            logger.error("[SadStory] AI 生成模板 JSON 解析失败")
            yield event.plain_result("AI 生成的内容无法解析，请重试")
        except Exception as e:
            logger.error(f"[SadStory] AI 生成模板失败: {e}")
            yield event.plain_result(f"AI 生成失败: {e}")

    async def terminate(self):
        await self.db.close()
        logger.info("[SadStory] 插件已卸载")
