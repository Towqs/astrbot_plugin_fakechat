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
STORY_PROMPT_CASUAL = """你是一个伤感故事创作者。请根据以下要求生成一段伤感故事，模拟QQ群里有人连续发消息讲故事的场景。

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
STORY_PROMPT_LITERARY = """你是一个伤感故事创作者。请根据以下要求生成一段伤感故事，模拟QQ群里有人连续发消息讲故事的场景。

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


@register("astrbot_plugin_sadstory", "Towqs", "伤感故事插件 - 以合并转发形式在群聊中展示伤感故事", "0.4.1")
class SadStoryPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.user_pool = []  # 最终用户池：自定义角色 + 素材群成员
        self.group_users = []  # 从素材群拉取的成员
        self.cooldown_map = {}
        data_dir = StarTools.get_data_dir("astrbot_plugin_sadstory")
        self.db = SadStoryDB(Path(data_dir) / "sadstory.db")

    async def initialize(self):
        await self.db.init()
        self._reload_config()
        await self._import_webui_data()
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
        """同步读取 WebUI 基础配置"""
        cfg = self.context.get_config()

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
        cfg = self.context.get_config()
        imported = 0

        raw_styles = cfg.get("add_writing_styles", [])
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

        raw_tpls = cfg.get("add_story_templates", [])
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

        if imported:
            logger.info(f"[SadStory] 从 WebUI 导入了 {imported} 条数据到数据库")

    def _load_templates(self) -> list:
        """加载所有已启用的模板：数据库中的 + templates/ 目录下的文件（同步包装）"""
        # 注意：数据库模板在 _generate_story 中异步加载
        # 这里只加载文件模板
        templates = []
        if os.path.isdir(TEMPLATES_DIR):
            for fname in sorted(os.listdir(TEMPLATES_DIR)):
                if fname.endswith(".txt"):
                    fpath = os.path.join(TEMPLATES_DIR, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                        if content:
                            templates.append(content)
                    except Exception as e:
                        logger.warning(f"[SadStory] 加载模板 {fname} 失败: {e}")
        return templates

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

    # ==================== Prompt 风格管理 ====================

    async def _get_active_prompt_style(self) -> str:
        """从数据库已启用的风格中随机选一个，没有则回退到内置默认"""
        enabled = await self.db.get_enabled_styles()
        if enabled:
            return random.choice(enabled)
        return STORY_PROMPT_CASUAL if self.use_casual_style else STORY_PROMPT_LITERARY

    # ==================== 故事生成 ====================

    def _get_at_user_id(self, event: AiocqhttpMessageEvent) -> str | None:
        """从消息中获取被 @ 或被引用的用户 ID"""
        # 先检查 @
        for seg in event.get_messages():
            if isinstance(seg, At) and str(seg.qq) != event.get_self_id():
                return str(seg.qq)
        # 再检查引用
        for seg in event.get_messages():
            if isinstance(seg, Reply) and seg.sender_id:
                return str(seg.sender_id)
        return None

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

    async def _generate_story(self, event: AiocqhttpMessageEvent, theme: str = "", forced_protagonist: dict = None) -> list:
        users = self._get_available_users()
        if len(users) < 2:
            return []

        # 如果有强制指定的主讲人（@ 或引用）
        if forced_protagonist:
            protagonist = forced_protagonist
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
        elif self.custom_protagonists:
            protagonist = random.choice(self.custom_protagonists)
            other_users = [u for u in users if u["user_id"] != protagonist["user_id"]]
        else:
            random.shuffle(users)
            protagonist = users[0]
            other_users = users[1:]

        bystander_count = min(self.bystander_count, len(other_users))
        if bystander_count == 0:
            return []
        random.shuffle(other_users)
        bystanders = other_users[:bystander_count]

        bystander_names = "、".join([u["nickname"] for u in bystanders])
        theme_line = f"6. 故事主题/关键词：{theme}" if theme else ""

        templates = []
        if self.use_story_template:
            templates = await self.db.get_enabled_templates()
            templates += self._load_templates()  # 文件模板
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

        story_prompt = await self._get_active_prompt_style()
        prompt = story_prompt.format(
            protagonist=protagonist["nickname"],
            bystanders=bystander_names,
            min_msg=self.story_min_messages,
            max_msg=self.story_max_messages,
            theme_line=theme_line,
            reference_section=reference_section,
            emoji_instruction=EMOJI_INSTRUCTION if self.use_face_emoji else "",
        )

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

            role_map = {protagonist["nickname"]: protagonist}
            for b in bystanders:
                role_map[b["nickname"]] = b

            messages = []
            for item in story_data:
                speaker = item.get("speaker", "")
                content = item.get("content", "")
                if not speaker or not content:
                    continue
                user_info = role_map.get(speaker, random.choice(bystanders))
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

    @filter.command("sadstory", permission=True)
    async def sadstory(self, event: AiocqhttpMessageEvent):
        """发送一段伤感故事（合并转发形式）。用法：/sadstory [主题]，仅管理员可用"""
        self._reload_config()
        await self._import_webui_data()

        group_id_str = event.get_group_id()
        if not group_id_str or group_id_str == "0":
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        if not self._check_cooldown(group_id_str):
            yield event.plain_result(f"故事讲太快了，休息一下吧~ ({self.cooldown_seconds}秒冷却)")
            return

        theme = event.message_str.replace("/sadstory", "").strip()

        # 检查是否 @ 或引用了某人作为主讲人
        forced_protagonist = None
        at_uid = self._get_at_user_id(event)
        if at_uid:
            forced_protagonist = await self._resolve_user_info(event.bot, int(group_id_str), at_uid)
            # 从 theme 中去掉 @ 部分的文本残留
            theme = re.sub(r'@\S+\s*', '', theme).strip()

        # 如果素材群有配置且用户池为空，尝试拉取
        if self.source_group_id and not self.group_users:
            fetched = await self._fetch_group_users(event.bot, self.source_group_id)
            if fetched:
                self.group_users = fetched
                self._resolve_qq_lists(fetched)

        # 非虚拟模式下，如果用户池仍为空，从当前群拉取真实成员
        if not self.use_virtual_users and not self.user_pool:
            fetched = await self._fetch_group_users(event.bot, int(group_id_str))
            if fetched:
                self.group_users = fetched
                self._resolve_qq_lists(fetched)

        logger.info(f"[SadStory] 当前用户池大小: {len(self.user_pool)}, 虚拟模式: {self.use_virtual_users}")

        yield event.plain_result("正在酝酿一个伤感故事，请稍候...")

        # 如果强制指定了主讲人，确保该用户在用户池中
        if forced_protagonist:
            if not any(u["user_id"] == forced_protagonist["user_id"] for u in self.user_pool):
                self.user_pool.append(forced_protagonist)

        messages = await self._generate_story(event, theme, forced_protagonist)
        if not messages:
            yield event.plain_result("故事生成失败了，可能是用户池不足（至少需要2人）或 LLM 服务暂时不可用，请稍后再试~")
            return

        nodes = self._build_forward_nodes(messages)
        try:
            await event.bot.send_group_forward_msg(
                group_id=int(group_id_str),
                messages=nodes,
            )
            self._set_cooldown(group_id_str)
        except Exception as e:
            logger.error(f"[SadStory] 发送合并转发失败: {e}")
            yield event.plain_result(f"故事发送失败了: {e}")

    @filter.command("sadstory_reload", permission=True)
    async def reload_users(self, event: AiocqhttpMessageEvent):
        """重新加载素材群用户列表。用法：/sadstory_reload，仅管理员可用"""
        self._reload_config()

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

    @filter.command("sadstory_addtpl", permission=True)
    async def add_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """添加故事模板。用法：/sadstory_addtpl 模板名（换行后跟模板内容），仅管理员可用"""
        raw = event.message_str
        parts = raw.split("\n", 1)
        first_line = parts[0].replace("/sadstory_addtpl", "").strip()
        content = parts[1].strip() if len(parts) > 1 else ""

        if not first_line:
            yield event.plain_result("用法：/sadstory_addtpl 模板名\n（换行后跟模板内容）\n\n示例：\n/sadstory_addtpl 校园故事\n她是有点偏执的那种...")
            return

        if not content:
            yield event.plain_result("模板内容不能为空，请在模板名后换行输入故事内容")
            return

        tpl_id = await self.db.add_template(first_line, content)
        yield event.plain_result(f"模板「{first_line}」已保存到数据库（ID:{tpl_id}，{len(content)}字）")

    @filter.command("sadstory_listtpl", permission=True)
    async def list_templates(self, event: AiocqhttpMessageEvent):
        """查看所有故事模板。用法：/sadstory_listtpl，仅管理员可用"""
        self._reload_config()
        db_tpls = await self.db.get_templates()
        lines = []
        idx = 1

        if db_tpls:
            lines.append(f"📋 数据库模板（{len(db_tpls)}个）：")
            for tpl_id, name, enabled, content in db_tpls:
                status = "✅" if enabled else "❌"
                preview = content[:40].replace("\n", " ") + ("..." if len(content) > 40 else "")
                lines.append(f"  {idx}. {status} [{tpl_id}] {name}：{preview}")
                idx += 1

        file_templates = []
        if os.path.isdir(TEMPLATES_DIR):
            file_templates = [f for f in sorted(os.listdir(TEMPLATES_DIR)) if f.endswith(".txt")]
        if file_templates:
            lines.append(f"📁 文件模板（{len(file_templates)}个，始终启用）：")
            for fname in file_templates:
                fpath = os.path.join(TEMPLATES_DIR, fname)
                size = os.path.getsize(fpath)
                name = fname.replace(".txt", "")
                lines.append(f"  {idx}. ✅ {name}（{size}字节）")
                idx += 1

        if not lines:
            yield event.plain_result("暂无故事模板\n用 /sadstory_addtpl 添加")
            return

        lines.insert(0, f"📝 故事模板列表（共{idx - 1}个）：")
        lines.append(f"\n模板参考当前{'已启用 ✅' if self.use_story_template else '已关闭 ❌'}")
        yield event.plain_result("\n".join(lines))

    @filter.command("sadstory_usetpl", permission=True)
    async def use_template(self, event: AiocqhttpMessageEvent):
        """启用/禁用指定模板。用法：/sadstory_usetpl ID，仅管理员可用"""
        arg = event.message_str.replace("/sadstory_usetpl", "").strip()
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

    @filter.command("sadstory_deltpl", permission=True)
    async def delete_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """删除故事模板。用法：/sadstory_deltpl ID 或文件名，仅管理员可用"""
        arg = event.message_str.replace("/sadstory_deltpl", "").strip()
        if not arg:
            yield event.plain_result("用法：/sadstory_deltpl ID（数据库模板）或 /sadstory_deltpl 文件名（文件模板）")
            return
        try:
            tpl_id = int(arg)
            name = await self.db.delete_template(tpl_id)
            if name:
                yield event.plain_result(f"模板「{name}」已从数据库删除")
                return
            yield event.plain_result(f"ID {tpl_id} 不存在")
            return
        except ValueError:
            pass
        fpath = os.path.join(TEMPLATES_DIR, f"{arg}.txt")
        if not os.path.isfile(fpath):
            yield event.plain_result(f"模板「{arg}」不存在，用 /sadstory_listtpl 查看列表")
            return
        try:
            os.remove(fpath)
            yield event.plain_result(f"文件模板「{arg}」已删除")
        except Exception as e:
            yield event.plain_result(f"删除失败: {e}")

    # ==================== 配置预览与风格指令 ====================

    @filter.command("sadstory_config", permission=True)
    async def show_config(self, event: AiocqhttpMessageEvent):
        """查看当前所有配置。用法：/sadstory_config，仅管理员可用"""
        self._reload_config()
        lines = []
        lines.append("📋 伤感故事 当前配置")
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
        tpl_count = 0
        for tpl_id, name, enabled, content in db_tpls:
            tpl_count += 1
            lines.append(f"  [{tpl_id}] {'✅' if enabled else '❌'} {name}（{len(content)}字）")
        if os.path.isdir(TEMPLATES_DIR):
            for fname in sorted(os.listdir(TEMPLATES_DIR)):
                if fname.endswith(".txt"):
                    tpl_count += 1
                    lines.append(f"  ✅ {fname.replace('.txt', '')}（文件）")
        if tpl_count == 0:
            lines.append("  暂无模板")

        yield event.plain_result("\n".join(lines))

    @filter.command("sadstory_style", permission=True)
    async def show_styles(self, event: AiocqhttpMessageEvent):
        """查看写作风格列表。用法：/sadstory_style，仅管理员可用"""
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

    @filter.command("sadstory_addstyle", permission=True)
    async def add_style(self, event: AiocqhttpMessageEvent):
        """添加写作风格。用法：/sadstory_addstyle 风格名（换行后跟内容），仅管理员可用"""
        raw = event.message_str
        parts = raw.split("\n", 1)
        first_line = parts[0].replace("/sadstory_addstyle", "").strip()
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

    @filter.command("sadstory_usestyle", permission=True)
    async def toggle_style(self, event: AiocqhttpMessageEvent):
        """启用/禁用写作风格。用法：/sadstory_usestyle ID，仅管理员可用"""
        arg = event.message_str.replace("/sadstory_usestyle", "").strip()
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

    @filter.command("sadstory_delstyle", permission=True)
    async def delete_style(self, event: AiocqhttpMessageEvent):
        """删除写作风格。用法：/sadstory_delstyle ID，仅管理员可用"""
        arg = event.message_str.replace("/sadstory_delstyle", "").strip()
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

    async def terminate(self):
        await self.db.close()
        logger.info("[SadStory] 插件已卸载")
