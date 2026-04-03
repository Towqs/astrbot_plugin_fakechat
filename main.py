import asyncio
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
STORY_PROMPT_CASUAL = """你是一个伪装聊天创作者，精通人类网络社交用语和情绪表达。请模拟QQ群里人们发消息交流讲故事的场景。

角色列表：
- 主角（讲故事的人）：{protagonist}
- 围观网友（偶尔插嘴/吐槽/互动）：{bystanders}

核心风格（非常重要，请仔细模仿）：
1. 【碎片化表达】主角一条一条地发消息讲故事，每条消息仅1-2句话，像真人在群里敲击回车，切忌大段长文。
2. 【纯粹口语化】语气随意、真实，可以使用“我就这样”、“就很奇葩”、“太痛苦了”等真实口语短句，严禁名著文学腔调。
3. 【情绪波动】要有自嘲、吐槽、情绪爆发的段落，可以带有情绪化的标点（如感叹号连用）。
4. 【生动互动】围观网友偶尔插嘴，如“卧槽”、“然后呢”、“破防了”、“你怎么不回他啊”、“看哭了”这种。网友消息总共插入3-6条即可，不要喧宾夺主。
5. 【呼应感】主角偶尔可以 @ 某个网友进行交互，或者说“你们别跟别人说”之类的，增加真实社群感。
{emoji_instruction}{sticker_instruction}
{theme_line}
{reference_section}
总消息条数严格控制在 {min_msg} 到 {max_msg} 条之间，确保故事有一个自然的情绪落脚点。

请严格仅以 JSON 数组格式输出，不要输出任何其他解释性文字，不要包含 Markdown 代码块符号(如 ```json)：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""

# LLM Prompt 模板 — 文学风格
STORY_PROMPT_LITERARY = """你是一个细腻的伪装聊天情感创作者。请模拟QQ群聊场景，撰写一段充满文学质感、发人深省的情感经历倾诉。

角色列表：
- 主角（倾诉者/讲故事的人）：{protagonist}
- 围观网友（给予温暖或共鸣）：{bystanders}

风格要求：
1. 【诗意留白】主角连续发消息倾诉，每条消息1-3句话。语言细腻真挚，注重意境和心理描写，可以略带文艺气息。
2. 【优美意象】善用隐喻，营造氛围感，让文字充满画面感与内心的情绪张力。
3. 【克制互动】网友作为群里的倾听者偶尔给出真诚的反应，例如“后来呢”、“太心酸了”、“抱抱你”、“看哭了”，总计3-6条，主舞台留给主角倾诉。
4. 【起承转合】情感脉络完整，结尾要有绵长的余韵，不强求完美结局，旨在让人久久难以释怀。
{emoji_instruction}{sticker_instruction}
{theme_line}
{reference_section}
总消息条数严格控制在 {min_msg} 到 {max_msg} 条之间。

请严格仅以 JSON 数组格式输出，不要输出任何其他解释性文字，不要包含 Markdown 代码块符号(如 ```json)：
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
STORY_PROMPT_DUAL_CASUAL = """你是一个优秀的伪装聊天创作者。请模拟QQ群里两人在深夜相互互动聊天的真实情景。

角色设定：
- {protagonist_a} 和 {protagonist_b} 是互为熟人/密友的群友，恰好都在线聊天
- 围观吃瓜的网友（偶尔插嘴）：{bystanders}

核心要求（必须遵守）：
1. 【动态节奏】绝对不要机械的一问一答！允许一方连发2-4条碎碎念讲述，另一方再连发回应或打断。
2. 【野生网感】文字极度口语化，像深夜刷手机随手发的消息，允许使用极短句、流行梗、吐槽感叹。
3. 【对话张力】主角之间可以互相调侃、拆台甚至分享各自的经历，聊回同一个话题。
4. 【群聊生态】围观网友偶尔插入简短评论如“笑死”、“你俩够了”、“大半夜的”，总共3-6条即可。
{emoji_instruction}{sticker_instruction}
{theme_line}
{reference_section}
总消息条数严格控制在 {min_msg} 到 {max_msg} 条之间。

请严格仅以 JSON 数组格式输出，不要输出任何解释性文字，不要包含 Markdown 代码块反引号。
重要：speaker 字段必须使用真实的[实际昵称]，绝对禁止使用“主角A”、“主角B”等代号。

示例（假设主角为"小明"和"小红"，网友有"阿杰"）：
[
  {{"speaker": "小明", "content": "刚看到一个视频笑死我了"}},
  {{"speaker": "小明", "content": "一只猫站起来了"}},
  {{"speaker": "小红", "content": "哈哈哈哈哈哈"}},
  {{"speaker": "小红", "content": "发来看看"}},
  {{"speaker": "阿杰", "content": "猫猫站起来！"}},
  {{"speaker": "小明", "content": "[图片]"}},
  {{"speaker": "小红", "content": "这猫成精了"}}
]

请按严格结构输出：
[
  {{"speaker": "实际昵称", "content": "台词内容"}},
  ...
]
"""

# LLM Prompt 模板 — 双主角文学风格
STORY_PROMPT_DUAL_LITERARY = """你是一个伪装聊天创作者。请模拟在深夜的QQ群落里，两人进行一场触及灵魂、细腻真切的隔空对话。

角色设定：
- {protagonist_a} 和 {protagonist_b} 是深夜偶遇在群里的灵魂伴侣或老友，互相倾诉心事
- 默默关注的倾听网友：{bystanders}

核心要求（必须遵守）：
1. 【极致克制】拒绝无病呻吟的青春疼痛文学！绝对禁止夸张做作的词语（如宛若、星辰、宿命等），用平实却击中人心的语言表达遗憾、回忆或迷茫。
2. 【碎碎念与停顿】当一方倾诉时，把一段较长的心里话拆成2-3条短消息连发，模仿边思考边打字的状态。可以多用省略号“...”或顿号代表迟疑。
3. 【温柔共振】倾听的一方不要像心理医生讲大道理，而是多用简短的感同身受回应，如“哎”、“确实”、“太懂了”，或者轻轻分享一句相关的过往经历产生共鸣。
4. 【真实的群落】群聊并非只有两人。围观网友偶尔发出一句“大半夜的别发刀子”、“我都看哭了”，总共插入3-5条增添真实氛围。
{emoji_instruction}{sticker_instruction}
{theme_line}
{reference_section}
总消息条数严格控制在 {min_msg} 到 {max_msg} 条之间。

请严格仅以 JSON 数组格式输出，不要输出任何包裹的 Markdown 代码块（如```json），只保留纯 JSON，不要有任何多余的引语。
重要：speaker 字段必须使用真实的[实际昵称]，绝对禁止使用“主角A”等代称。

示例（假设主角为"林夕"、"雨彤"，网友"夜猫子"）：
[
  {{"speaker": "林夕", "content": "大半夜的，突然翻到以前的相册"}},
  {{"speaker": "林夕", "content": "感觉时间过得真特么快"}},
  {{"speaker": "雨彤", "content": "哎，谁说不是呢"}},
  {{"speaker": "雨彤", "content": "有些东西越看越睡不着"}},
  {{"speaker": "夜猫子", "content": "大半夜不睡觉在这emo是吧 [哭泣]"}}
]
"""


@register("astrbot_plugin_sadstory", "Towqs", "伪装聊天插件 - 以合并转发形式在群聊中展示伪装聊天", "0.6.12")
class SadStoryPlugin(Star):
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
        try:
            info = await asyncio.wait_for(
                bot.get_group_member_info(group_id=group_id, user_id=int(user_id)),
                timeout=10.0
            )
            if info:
                nickname = info.get("card", "") or info.get("nickname", "") or f"用户{user_id[-4:]}"
                return {"nickname": nickname, "user_id": user_id}
        except asyncio.TimeoutError:
            logger.warning(f"[SadStory] get_group_member_info 超时: user_id={user_id}")
        except Exception as e:
            logger.warning(f"[SadStory] get_group_member_info 失败: {e}")
        return {"nickname": f"用户{user_id[-4:]}", "user_id": user_id}

    async def _generate_story(self, event: AiocqhttpMessageEvent, theme: str = "", forced_protagonists: list[dict] | None = None, user_pool: list | None = None) -> list:
        users = list(self._get_available_users(user_pool))
        if len(users) < 2:
            return []

        dual_mode = forced_protagonists is not None and len(forced_protagonists) == 2

        logger.info(f"[SadStory] dual_mode={dual_mode}, forced_protagonists={forced_protagonists}, available_users_count={len(users)}")

        # 双主角模式
        if dual_mode:
            protagonist_a, protagonist_b = forced_protagonists[0], forced_protagonists[1]
            other_users = [u for u in users if u["user_id"] not in {protagonist_a["user_id"], protagonist_b["user_id"]}]
            bystander_count = min(self.bystander_count, len(other_users)) if other_users else 0
        # 单主角模式（强制指定）
        elif forced_protagonists and len(forced_protagonists) == 1:
            protagonist = forced_protagonists[0]
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
            bystander_count = max(1, min(self.bystander_count, len(other_users)))
        # 单主角模式（配置指定）
        elif self.custom_protagonists:
            protagonist = random.choice(self.custom_protagonists)
            if not protagonist.get("nickname"):
                protagonist["nickname"] = f"用户{protagonist['user_id'][-4:]}"
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
            bystander_count = max(1, min(self.bystander_count, len(other_users)))
        # 单主角模式（随机）
        else:
            random.shuffle(users)
            protagonist = users[0]
            other_users = users[1:]
            bystander_count = max(1, min(self.bystander_count, len(other_users)))

        if not other_users and not dual_mode:
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

        sticker_instruction = self.sticker_manager.generate_instruction()

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
                "sticker_instruction": sticker_instruction,
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
                "sticker_instruction": sticker_instruction,
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
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=180.0
            )
            raw = llm_resp.completion_text.strip()
            raw = re.sub(r'\[[\d]{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\].*', '', raw)
            raw = raw.strip()

            start = raw.find("[")
            if start == -1:
                logger.error("[SadStory] LLM 输出中未找到 JSON 数组")
                return []
            
            bracket_stack = []
            end = -1
            in_string = False
            escape_next = False
            
            for i in range(start, len(raw)):
                char = raw[i]
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == '[':
                    bracket_stack.append('[')
                elif char == '{':
                    bracket_stack.append('{')
                elif char == '}':
                    if bracket_stack and bracket_stack[-1] == '{':
                        bracket_stack.pop()
                elif char == ']':
                    if bracket_stack and bracket_stack[-1] == '[':
                        bracket_stack.pop()
                        if not bracket_stack:
                            end = i + 1
                            break
            
            if end == -1:
                logger.error(f"[SadStory] JSON 数组括号不匹配, raw[:100]: {raw[:100]}")
                return []
            
            try:
                story_data = json.loads(raw[start:end])
            except json.JSONDecodeError as e:
                logger.error(f"[SadStory] JSON 解析失败: {e}, raw[{start}:{end}][:100]: {raw[start:end][:100]}")
                return []
            
            if not isinstance(story_data, list) or len(story_data) < self.story_min_messages:
                logger.error(f"[SadStory] JSON 数组提取失败或不足{self.story_min_messages}条")
                return []

            # 构建角色映射（优先使用 user_id，昵称仅作模糊匹配候选）
            id_to_user = {}
            nickname_candidates = []
            if dual_mode:
                id_to_user[protagonist_a["user_id"]] = protagonist_a
                id_to_user[protagonist_b["user_id"]] = protagonist_b
                nickname_candidates.append((protagonist_a["nickname"], protagonist_a))
                nickname_candidates.append((protagonist_b["nickname"], protagonist_b))
                fallback_user = protagonist_a
            else:
                id_to_user[protagonist["user_id"]] = protagonist
                nickname_candidates.append((protagonist["nickname"], protagonist))
                fallback_user = protagonist
            for b in bystanders:
                id_to_user[b["user_id"]] = b
                nickname_candidates.append((b["nickname"], b))

            # 消息条数约束
            max_msgs = self.story_max_messages
            if len(story_data) > max_msgs:
                story_data = story_data[:max_msgs]
                logger.info(f"[SadStory] 裁剪消息至 {max_msgs} 条")

            messages = []
            for item in story_data:
                speaker = item.get("speaker", "")
                content = item.get("content", "")
                if not speaker or not content:
                    continue
                user_info = id_to_user.get(speaker)
                if not user_info:
                    for nick, info in nickname_candidates:
                        if speaker == nick or (isinstance(speaker, str) and isinstance(nick, str) and (speaker in nick or nick in speaker)):
                            user_info = info
                            break
                if not user_info:
                    user_info = fallback_user
                if "<sticker" in content:
                    logger.info(f"[SadStory] 检测到贴纸标签: {content}")
                messages.append({
                    "nickname": user_info["nickname"],
                    "user_id": user_info["user_id"],
                    "content": content,
                })
            return messages

        except json.JSONDecodeError as e:
            logger.error(f"[SadStory] JSON 解析失败: {e}, raw[:200]={raw[:200] if raw else 'N/A'}")
            return []
        except asyncio.TimeoutError:
            logger.error(f"[SadStory] LLM 生成超时 (180s)")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 生成故事失败: {type(e).__name__}: {e}")
            return []


    # ==================== 合并转发构建 ====================

    def _parse_content_segments(self, content: str) -> list:
        segments = []
        pattern = r'\[表情[:：]([^\]]+)\]'
        sticker_pattern = r'<sticker\s+name="([^"]+)".*?/>'
        combined_pattern = f'({pattern}|{sticker_pattern})'
        
        last_end = 0
        for match in re.finditer(combined_pattern, content, re.DOTALL):
            before = content[last_end:match.start()]
            if before:
                segments.append({"type": "text", "data": {"text": before}})
            
            matched = match.group(0)
            if matched.startswith('[表情'):
                face_match = re.match(pattern, matched)
                if face_match:
                    face_name = face_match.group(1).strip()
                    face_id = FACE_MAP.get(face_name)
                    if face_id is not None:
                        segments.append({"type": "face", "data": {"id": str(face_id)}})
                    else:
                        segments.append({"type": "text", "data": {"text": matched}})
            elif matched.startswith('<sticker'):
                name_match = re.search(r'name="([^"]+)"', matched)
                if name_match and self.sticker_manager.enabled:
                    sticker_name = name_match.group(1)
                    image_path = self.sticker_manager._get_sticker_image_path(sticker_name)
                    if image_path:
                        segments.append({"type": "image", "data": {"file": f"file:///{image_path}"}})
                    else:
                        logger.warning(f"[SadStory] 贴纸图片不存在: {sticker_name}")
            
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
            if self.use_face_emoji or self.sticker_manager.enabled:
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
            if len(theme) > 100:
                theme = theme[:100]

            forced_protagonists = []
            at_ids = self._get_at_user_ids(event)
            group_id = int(group_id_str)
            if at_ids:
                for uid in at_ids:
                    info = await self._resolve_user_info(event.bot, group_id, uid)
                    forced_protagonists.append(info)
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

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_addtpl")
    async def add_template(self, event: AiocqhttpMessageEvent):
        """添加故事模板（管理员专用）。用法：/sadstory_addtpl 模板名（换行后跟模板内容）"""
        try:
            raw = event.message_str
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

            if len(content) > 10000:
                yield event.plain_result("模板内容过长，请控制在 10000 字以内")
                return

            tpl_id = await self.db.add_template(first_line, content)
            if tpl_id is None:
                yield event.plain_result(f"模板「{first_line}」已存在，请使用新名称")
                return
            yield event.plain_result(f"模板「{first_line}」已保存到数据库（ID:{tpl_id}，{len(content)}字）")
        except Exception as e:
            logger.error(f"[SadStory] add_template 执行异常: {e}")
            yield event.plain_result(f"添加模板失败: {e}")

    @filter.command("sadstory_listtpl")
    async def list_templates(self, event: AiocqhttpMessageEvent):
        """查看所有故事模板。用法：/sadstory_listtpl"""
        if not self._check_permission(event):
            return
        try:
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
        except Exception as e:
            logger.error(f"[SadStory] list_templates 执行异常: {e}")
            yield event.plain_result(f"获取模板列表失败: {e}")

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
        try:
            result = await self.db.toggle_template(tpl_id)
            if not result:
                yield event.plain_result(f"ID {tpl_id} 不存在，用 /sadstory_listtpl 查看列表")
                return
            name, new_enabled = result
            status = "已启用 ✅" if new_enabled else "已禁用 ❌"
            yield event.plain_result(f"模板「{name}」{status}")
        except Exception as e:
            logger.error(f"[SadStory] use_template 执行异常: {e}")
            yield event.plain_result(f"操作失败: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_deltpl")
    async def delete_template(self, event: AiocqhttpMessageEvent):
        """删除故事模板（管理员专用）。用法：/sadstory_deltpl ID"""
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_deltpl ID\n（ID 可通过 /sadstory_listtpl 查看方括号内的数字）")
            return
        try:
            tpl_id = int(arg)
        except ValueError:
            yield event.plain_result("请输入模板 ID（数字）")
            return
        try:
            name = await self.db.delete_template(tpl_id)
            if name:
                yield event.plain_result(f"模板「{name}」已删除")
            else:
                yield event.plain_result(f"ID {tpl_id} 不存在，用 /sadstory_listtpl 查看列表")
        except Exception as e:
            logger.error(f"[SadStory] delete_template 执行异常: {e}")
            yield event.plain_result(f"删除失败: {e}")

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

    @filter.command("sadstory_style")
    async def show_styles(self, event: AiocqhttpMessageEvent):
        """查看写作风格列表。用法：/sadstory_style"""
        if not self._check_permission(event):
            return
        try:
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
        except Exception as e:
            logger.error(f"[SadStory] show_styles 执行异常: {e}")
            yield event.plain_result(f"获取风格列表失败: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_addstyle")
    async def add_style(self, event: AiocqhttpMessageEvent):
        """添加写作风格（管理员专用）。用法：/sadstory_addstyle 风格名（换行后跟内容）"""
        try:
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
            if len(content) > 5000:
                yield event.plain_result("写作指令过长，请控制在 5000 字以内")
                return
            sid = await self.db.add_style(first_line, content)
            if sid is None:
                yield event.plain_result(f"风格「{first_line}」已存在，请使用新名称")
                return
            yield event.plain_result(f"风格「{first_line}」已保存（ID:{sid}，{len(content)}字）")
        except Exception as e:
            logger.error(f"[SadStory] add_style 执行异常: {e}")
            yield event.plain_result(f"添加风格失败: {e}")

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
        try:
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
        except Exception as e:
            logger.error(f"[SadStory] toggle_style 执行异常: {e}")
            yield event.plain_result(f"操作失败: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_delstyle")
    async def delete_style(self, event: AiocqhttpMessageEvent):
        """删除写作风格（管理员专用）。用法：/sadstory_delstyle ID"""
        arg = event.message_str.partition(" ")[2].strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_delstyle ID\n（ID 可通过 /sadstory_style 查看）")
            return
        try:
            sid = int(arg)
        except ValueError:
            yield event.plain_result("请输入风格 ID（数字）")
            return
        try:
            name = await self.db.delete_style(sid)
            if name:
                yield event.plain_result(f"风格「{name}」已删除")
            else:
                yield event.plain_result(f"ID {sid} 不存在")
        except Exception as e:
            logger.error(f"[SadStory] delete_style 执行异常: {e}")
            yield event.plain_result(f"删除失败: {e}")

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
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=gen_prompt),
                timeout=180.0
            )
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
            if len(style_content) > 5000:
                style_content = style_content[:5000]
                logger.warning("[SadStory] AI 生成风格内容超过5000字，已截断")
            sid = await self.db.add_style(style_name, style_content)
            if sid is None:
                yield event.plain_result(f"风格「{style_name}」已存在，请使用新描述重试")
                return
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
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=gen_prompt),
                timeout=180.0
            )
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
            if len(tpl_content) > 10000:
                yield event.plain_result("AI 生成的故事模板内容过长，请重试")
                return
            tpl_id = await self.db.add_template(tpl_name, tpl_content)
            if tpl_id is None:
                yield event.plain_result(f"故事模板「{tpl_name}」已存在，请使用新描述重试")
                return
            yield event.plain_result(f"故事模板「{tpl_name}」已写入数据库（ID:{tpl_id}，{len(tpl_content)}字）")
        except json.JSONDecodeError:
            logger.error("[SadStory] AI 生成模板 JSON 解析失败")
            yield event.plain_result("AI 生成的内容无法解析，请重试")
        except Exception as e:
            logger.error(f"[SadStory] AI 生成模板失败: {e}")
            yield event.plain_result(f"AI 生成失败: {e}")

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
