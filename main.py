import json
import os
import random
import re
import time

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

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

# LLM Prompt 模板
STORY_PROMPT = """你是一个伤感故事创作者。请根据以下要求生成一段伤感故事，模拟QQ群里有人连续发消息讲故事的场景。

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

# 表情使用说明（注入到 prompt 中）
EMOJI_INSTRUCTION = """- 可以在台词中适当插入QQ表情来增加真实感，格式为 [表情:名称]
- 可用的表情：流泪、大哭、难过、委屈、心碎、快哭了、飙泪、叹气、无奈、衰、微笑、偷笑、呲牙、笑哭、苦笑、捂脸、憨笑、抱抱、亲亲、握手、赞、鼓掌、OK、思考、疑问、震惊、惊恐、吓、发呆、害羞、生气、鄙视、白眼、再见、玫瑰、凋谢、爱心、啤酒、咖啡、晕、睡、困、哈欠、奋斗、可怜、冷汗、擦汗
- 表情不要太多，大约每5-8条消息穿插1个就够了，要自然
- 有些消息可以只发一个表情不带文字，比如围观网友回复一个 [表情:流泪]
- 示例："我当时真的绷不住了[表情:大哭]"、"[表情:抱抱]"、"后来就再也没见过她[表情:叹气]"
"""


@register("astrbot_plugin_sadstory", "Towqs", "伤感故事插件 - 以合并转发形式在群聊中展示伤感故事", "0.2.9")
class SadStoryPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.user_pool = []
        self.group_users = []
        self.cooldown_map = {}

    async def initialize(self):
        self._reload_config()
        logger.info(f"[SadStory] 插件初始化完成，手动配置用户数: {len(self.user_pool)}")

    # ==================== 配置管理 ====================

    def _reload_config(self):
        cfg = self.context.get_config()

        self.source_group_id = self._parse_int(cfg.get("source_group_id", ""), 0)
        self.include_users = self._parse_list(cfg.get("include_users", ""))
        self.exclude_users = self._parse_list(cfg.get("exclude_users", ""))
        self.use_card_as_name = cfg.get("use_card_as_name", True)
        self.allowed_groups = self._parse_list(cfg.get("allowed_groups", ""))
        self.cooldown_seconds = self._parse_int(cfg.get("cooldown_seconds", ""), 60)
        self.story_min_messages = self._parse_int(cfg.get("story_min_messages", ""), 30)
        self.story_max_messages = self._parse_int(cfg.get("story_max_messages", ""), 80)
        self.bystander_count = self._parse_int(cfg.get("bystander_count", ""), 3)
        self.chat_provider_id = str(cfg.get("chat_provider_id", "")).strip()
        self.use_virtual_users = cfg.get("use_virtual_users", False)
        self.use_story_template = cfg.get("use_story_template", True)
        self.use_face_emoji = cfg.get("use_face_emoji", True)

        # 从 WebUI 配置读取模板列表
        raw_templates = cfg.get("story_templates", [])
        self.config_templates = []
        if isinstance(raw_templates, list):
            for t in raw_templates:
                t = str(t).strip()
                if t:
                    self.config_templates.append(t)

        # 解析自定义用户：格式 "昵称1:QQ号1,昵称2:QQ号2"
        custom_str = cfg.get("custom_users", "")
        custom_users = []
        if custom_str and str(custom_str).strip():
            for pair in str(custom_str).split(","):
                pair = pair.strip()
                if ":" in pair:
                    name, uid = pair.split(":", 1)
                    name, uid = name.strip(), uid.strip()
                    if name and uid:
                        custom_users.append({"nickname": name, "user_id": uid})
                elif "：" in pair:  # 兼容中文冒号
                    name, uid = pair.split("：", 1)
                    name, uid = name.strip(), uid.strip()
                    if name and uid:
                        custom_users.append({"nickname": name, "user_id": uid})

        logger.info(f"[SadStory] 配置加载: 自定义用户={custom_users}, 素材群={self.source_group_id}, 虚拟模式={self.use_virtual_users}")
        self.user_pool = custom_users + self.group_users

    def _load_templates(self) -> list:
        """加载所有模板：WebUI 配置中的 + templates/ 目录下的文件"""
        templates = list(self.config_templates)  # 先加配置里的
        # 再加文件里的
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
        logger.info(f"[SadStory] 模板总数: {len(templates)}（配置: {len(self.config_templates)}, 文件: {len(templates) - len(self.config_templates)}）")
        return templates

    @staticmethod
    def _parse_list(s) -> list:
        s = str(s) if s is not None else ""
        if not s.strip():
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

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
                if self.include_users and uid not in self.include_users:
                    continue
                if uid in self.exclude_users:
                    continue
                nickname = m.get("card", "") if self.use_card_as_name else ""
                if not nickname:
                    nickname = m.get("nickname", f"用户{uid[-4:]}")
                users.append({"nickname": nickname, "user_id": uid})
            logger.info(f"[SadStory] 从群 {group_id} 获取到 {len(users)} 个用户")
            return users
        except Exception as e:
            logger.error(f"[SadStory] 获取群成员列表失败: {e}")
            return []

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
        # 非虚拟模式：返回空，由命令处理中自动拉取真实群成员
        return []

    # ==================== 冷却检查 ====================

    def _check_cooldown(self, group_id: str) -> bool:
        if self.cooldown_seconds <= 0:
            return True
        last = self.cooldown_map.get(group_id, 0)
        return (time.time() - last) >= self.cooldown_seconds

    def _set_cooldown(self, group_id: str):
        self.cooldown_map[group_id] = time.time()

    # ==================== 故事生成 ====================

    async def _generate_story(self, event: AiocqhttpMessageEvent, theme: str = "") -> list:
        users = self._get_available_users()
        if len(users) < 2:
            return []

        random.shuffle(users)
        protagonist = users[0]
        bystander_count = min(self.bystander_count, len(users) - 1)
        bystanders = users[1:1 + bystander_count]

        bystander_names = "、".join([u["nickname"] for u in bystanders])
        theme_line = f"6. 故事主题/关键词：{theme}" if theme else ""

        templates = self._load_templates() if self.use_story_template else []
        reference_section = ""
        if templates:
            ref = random.choice(templates)
            if len(ref) > 2000:
                ref = ref[:2000] + "\n...(省略)"
            ref = ref.replace("{", "{{").replace("}", "}}")
            reference_section = f"""
以下是一个参考故事的风格示例（请模仿这种碎片化、口语化的叙事风格，但不要抄袭内容，要创作全新的故事）：
---
{ref}
---
"""

        prompt = STORY_PROMPT.format(
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
            # 使用 llm_generate 独立调用，不带会话历史，避免上下文污染
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
            # 表情前的文本
            before = content[last_end:match.start()]
            if before:
                segments.append({"type": "text", "data": {"text": before}})

            # 表情本身
            face_name = match.group(1).strip()
            face_id = FACE_MAP.get(face_name)
            if face_id is not None:
                segments.append({"type": "face", "data": {"id": str(face_id)}})
            else:
                # 未知表情名，保留原文
                segments.append({"type": "text", "data": {"text": match.group(0)}})

            last_end = match.end()

        # 剩余文本
        remaining = content[last_end:]
        if remaining:
            segments.append({"type": "text", "data": {"text": remaining}})

        # 如果整个内容没有任何段，兜底
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

        # 使用 AiocqhttpMessageEvent 的 get_group_id() 方法
        group_id_str = event.get_group_id()
        if not group_id_str or group_id_str == "0":
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        # 检查群白名单
        if self.allowed_groups and group_id_str not in self.allowed_groups:
            return

        # 检查冷却
        if not self._check_cooldown(group_id_str):
            yield event.plain_result(f"故事讲太快了，休息一下吧~ ({self.cooldown_seconds}秒冷却)")
            return

        # 获取主题参数
        theme = event.message_str.replace("/sadstory", "").strip()

        # 如果素材群有配置且用户池为空，尝试拉取
        if self.source_group_id and not self.group_users:
            fetched = await self._fetch_group_users(event.bot, self.source_group_id)
            if fetched:
                self.group_users = fetched
                self._reload_config()  # 重新合并 user_pool

        # 非虚拟模式下，如果用户池仍为空，从当前群拉取真实成员
        if not self.use_virtual_users and not self.user_pool:
            fetched = await self._fetch_group_users(event.bot, int(group_id_str))
            if fetched:
                self.group_users = fetched
                self._reload_config()  # 重新合并 user_pool

        logger.info(f"[SadStory] 当前用户池大小: {len(self.user_pool)}, 虚拟模式: {self.use_virtual_users}")

        yield event.plain_result("正在酝酿一个伤感故事，请稍候...")

        messages = await self._generate_story(event, theme)
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
            self._reload_config()
            yield event.plain_result(f"用户池已刷新，当前共 {len(self.user_pool)} 个用户")
        else:
            yield event.plain_result("刷新失败，请检查素材群号是否正确以及机器人是否在群内")

    @filter.command("sadstory_addtpl", permission=True)
    async def add_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """添加故事模板。用法：/sadstory_addtpl 模板名（换行后跟模板内容），仅管理员可用"""
        raw = event.message_str
        # 去掉命令部分，取剩余内容
        parts = raw.split("\n", 1)
        first_line = parts[0].replace("/sadstory_addtpl", "").strip()
        content = parts[1].strip() if len(parts) > 1 else ""

        if not first_line:
            yield event.plain_result("用法：/sadstory_addtpl 模板名\n（换行后跟模板内容）\n\n示例：\n/sadstory_addtpl 校园故事\n她是有点偏执的那种...")
            return

        if not content:
            yield event.plain_result("模板内容不能为空，请在模板名后换行输入故事内容")
            return

        # 确保 templates 目录存在
        os.makedirs(TEMPLATES_DIR, exist_ok=True)

        # 保存模板文件
        safe_name = first_line.replace("/", "_").replace("\\", "_").replace(".", "_")
        fpath = os.path.join(TEMPLATES_DIR, f"{safe_name}.txt")
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            yield event.plain_result(f"模板「{safe_name}」已保存（{len(content)}字）")
        except Exception as e:
            logger.error(f"[SadStory] 保存模板失败: {e}")
            yield event.plain_result(f"保存失败: {e}")

    @filter.command("sadstory_listtpl", permission=True)
    async def list_templates(self, event: AiocqhttpMessageEvent):
        """查看所有故事模板。用法：/sadstory_listtpl，仅管理员可用"""
        self._reload_config()
        lines = []
        idx = 1

        # WebUI 配置中的模板
        if self.config_templates:
            lines.append(f"📋 后台配置模板（{len(self.config_templates)}个）：")
            for t in self.config_templates:
                preview = t[:50].replace("\n", " ") + ("..." if len(t) > 50 else "")
                lines.append(f"  {idx}. {preview}")
                idx += 1

        # 文件模板
        file_templates = []
        if os.path.isdir(TEMPLATES_DIR):
            file_templates = [f for f in sorted(os.listdir(TEMPLATES_DIR)) if f.endswith(".txt")]
        if file_templates:
            lines.append(f"📁 文件模板（{len(file_templates)}个）：")
            for fname in file_templates:
                fpath = os.path.join(TEMPLATES_DIR, fname)
                size = os.path.getsize(fpath)
                name = fname.replace(".txt", "")
                lines.append(f"  {idx}. {name}（{size}字节）")
                idx += 1

        if not lines:
            yield event.plain_result("暂无故事模板")
            return

        lines.insert(0, f"📝 故事模板列表（共{idx - 1}个）：")
        lines.append(f"\n模板参考当前{'已启用 ✅' if self.use_story_template else '已关闭 ❌'}")
        yield event.plain_result("\n".join(lines))

    @filter.command("sadstory_deltpl", permission=True)
    async def delete_template(self, event: AiocqhttpMessageEvent, tpl_name: str = ""):
        """删除故事模板。用法：/sadstory_deltpl 模板名，仅管理员可用"""
        name = event.message_str.replace("/sadstory_deltpl", "").strip()
        if not name:
            yield event.plain_result("用法：/sadstory_deltpl 模板名")
            return

        # 尝试匹配文件
        fpath = os.path.join(TEMPLATES_DIR, f"{name}.txt")
        if not os.path.isfile(fpath):
            yield event.plain_result(f"模板「{name}」不存在，用 /sadstory_listtpl 查看列表")
            return

        try:
            os.remove(fpath)
            yield event.plain_result(f"模板「{name}」已删除")
        except Exception as e:
            yield event.plain_result(f"删除失败: {e}")

    async def terminate(self):
        logger.info("[SadStory] 插件已卸载")
