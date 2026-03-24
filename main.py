import json
import os
import random
import time

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 插件目录（用于读取故事模板）
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(PLUGIN_DIR, "templates")  # 故事模板统一放在 templates/ 目录下

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
{theme_line}
{reference_section}
总消息条数控制在 {min_msg} 到 {max_msg} 条之间，其中主角的消息占绝大多数。

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "角色名", "content": "台词内容"}},
  ...
]
"""


@register("astrbot_plugin_sadstory", "Towqs", "伤感故事插件 - 以合并转发形式在群聊中展示伤感故事", "0.2.0")
class SadStoryPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.user_pool = []         # 可用的用户列表（自定义 + 素材群）
        self.group_users = []       # 从素材群拉取的用户（单独存，防止重复追加）
        self.cooldown_map = {}      # 群冷却记录 {group_id: last_trigger_time}

    async def initialize(self):
        """插件初始化"""
        self._reload_config()
        logger.info(f"[SadStory] 插件初始化完成，手动配置用户数: {len(self.user_pool)}")

    # ==================== 配置管理 ====================

    def _reload_config(self):
        """从 WebUI 配置读取并解析"""
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

        # 解析自定义用户：格式 "昵称1:QQ号1,昵称2:QQ号2"
        custom_str = cfg.get("custom_users", "")
        custom_users = []
        if custom_str and custom_str.strip():
            for pair in custom_str.split(","):
                pair = pair.strip()
                if ":" in pair:
                    name, uid = pair.split(":", 1)
                    custom_users.append({"nickname": name.strip(), "user_id": uid.strip()})

        # 合并自定义用户 + 素材群用户（不重复追加）
        self.user_pool = custom_users + self.group_users

    def _load_templates(self) -> list:
        """加载 templates/ 目录下所有 .txt 故事模板"""
        templates = []
        if not os.path.isdir(TEMPLATES_DIR):
            return templates
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
    def _parse_list(s: str) -> list:
        """将逗号分隔的字符串解析为列表"""
        if not s or not s.strip():
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    @staticmethod
    def _parse_int(s: str, default: int = 0) -> int:
        """安全解析整数"""
        try:
            return int(s) if s and s.strip() else default
        except ValueError:
            return default

    # ==================== 用户池管理 ====================

    async def _fetch_group_users(self, bot, group_id: int) -> list:
        """从素材群获取用户列表"""
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
        """获取当前可用的用户池"""
        return self.user_pool if self.user_pool else [
            {"nickname": "路人甲", "user_id": "10001"},
            {"nickname": "深夜失眠的人", "user_id": "10002"},
            {"nickname": "吃瓜群众", "user_id": "10003"},
            {"nickname": "曾经沧海", "user_id": "10004"},
            {"nickname": "匿名网友", "user_id": "10005"},
            {"nickname": "故事收集者", "user_id": "10006"},
        ]

    # ==================== 冷却检查 ====================

    def _check_cooldown(self, group_id: str) -> bool:
        """检查群是否在冷却中，返回 True 表示可以触发"""
        if self.cooldown_seconds <= 0:
            return True
        last = self.cooldown_map.get(group_id, 0)
        return (time.time() - last) >= self.cooldown_seconds

    def _set_cooldown(self, group_id: str):
        """设置群冷却"""
        self.cooldown_map[group_id] = time.time()

    # ==================== 故事生成 ====================

    async def _generate_story(self, event: AstrMessageEvent, theme: str = "") -> list:
        """调用 LLM 生成故事，返回消息列表"""
        users = self._get_available_users()
        if len(users) < 2:
            return []

        # 随机分配角色
        random.shuffle(users)
        protagonist = users[0]
        bystander_count = min(self.bystander_count, len(users) - 1)
        bystanders = users[1:1 + bystander_count]

        bystander_names = "、".join([u["nickname"] for u in bystanders])
        theme_line = f"6. 故事主题/关键词：{theme}" if theme else ""

        # 加载参考故事模板
        templates = self._load_templates()
        reference_section = ""
        if templates:
            # 随机选一个模板作为参考
            ref = random.choice(templates)
            # 截取前2000字避免 prompt 过长
            if len(ref) > 2000:
                ref = ref[:2000] + "\n...(省略)"
            # 转义花括号，防止 .format() 报错
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
        )

        try:
            # 使用自定义 LLM 模型或默认模型
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(
                    event.unified_msg_origin
                )
            llm_resp = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=provider_id,
                prompt=prompt,
                max_steps=1,
                tool_call_timeout=60,
            )
            raw = llm_resp.completion_text.strip()

            # 尝试提取 JSON 数组
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                logger.error(f"[SadStory] LLM 输出中未找到 JSON 数组")
                return []

            story_data = json.loads(raw[start:end])

            # 构建角色名到用户信息的映射
            role_map = {protagonist["nickname"]: protagonist}
            for b in bystanders:
                role_map[b["nickname"]] = b

            # 组装消息列表
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

    def _build_forward_nodes(self, messages: list) -> list:
        """将消息列表构建为合并转发 node 消息段"""
        nodes = []
        for msg in messages:
            nodes.append({
                "type": "node",
                "data": {
                    "user_id": str(msg["user_id"]),
                    "nickname": msg["nickname"],
                    "content": msg["content"],
                }
            })
        return nodes

    # ==================== 命令处理 ====================

    @filter.command("sadstory", permission=True)
    async def sadstory(self, event: AstrMessageEvent):
        """发送一段伤感故事（合并转发形式）。用法：/sadstory [主题]，仅管理员可用"""
        self._reload_config()  # 每次触发时重新读取配置

        # 检查是否为群消息
        group_id = getattr(event, "group_id", None)
        if not group_id:
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        group_id_str = str(group_id)

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
                self.user_pool = self.user_pool + self.group_users

        yield event.plain_result("正在酝酿一个伤感故事，请稍候...")

        # 生成故事
        messages = await self._generate_story(event, theme)
        if not messages:
            yield event.plain_result("故事生成失败了，可能是 LLM 服务暂时不可用，请稍后再试~")
            return

        # 构建合并转发并发送
        nodes = self._build_forward_nodes(messages)
        try:
            await event.bot.send_group_forward_msg(
                group_id=int(group_id),
                messages=nodes,
            )
            self._set_cooldown(group_id_str)
        except Exception as e:
            logger.error(f"[SadStory] 发送合并转发失败: {e}")
            yield event.plain_result(f"故事发送失败了: {e}")

    @filter.command("sadstory_reload", permission=True)
    async def reload_users(self, event: AstrMessageEvent):
        """重新加载素材群用户列表（管理员命令）。用法：/sadstory_reload，仅管理员可用"""
        self._reload_config()

        if not self.source_group_id:
            yield event.plain_result("未配置素材群，请先在 WebUI 插件配置中设置素材群群号")
            return

        fetched = await self._fetch_group_users(event.bot, self.source_group_id)
        if fetched:
            self.group_users = fetched
            self._reload_config()  # 重新合并 user_pool
            yield event.plain_result(f"用户池已刷新，当前共 {len(self.user_pool)} 个用户")
        else:
            yield event.plain_result("刷新失败，请检查素材群号是否正确以及机器人是否在群内")

    async def terminate(self):
        """插件销毁"""
        logger.info("[SadStory] 插件已卸载")
