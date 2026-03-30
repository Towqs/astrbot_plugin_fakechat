import asyncio
import json
import random
import re
from typing import Optional
from astrbot.api import logger


class NestChatGenerator:
    def __init__(self, config: dict, sticker_manager=None):
        self.nest_count_min = config.get("nest_count_min", 1)
        self.nest_count_max = config.get("nest_count_max", 3)
        self.inner_msg_min = config.get("inner_msg_min", 3)
        self.inner_msg_max = config.get("inner_msg_max", 8)
        self.use_face_emoji = config.get("use_face_emoji", False)
        self.sticker_manager = sticker_manager

    def _parse_content_segments(self, content: str) -> list:
        segments = []
        pattern = r'\[表情:([^\]]+)\]'
        last_end = 0
        for match in re.finditer(pattern, content):
            if match.start() > last_end:
                text = content[last_end:match.start()]
                if text:
                    segments.append({"type": "text", "data": {"text": text}})
            emoji_name = match.group(1)
            segments.append({"type": "face", "data": {"id": self._get_face_id(emoji_name)}})
            last_end = match.end()
        if last_end < len(content):
            text = content[last_end:]
            if text:
                segments.append({"type": "text", "data": {"text": text}})
        if not segments:
            segments.append({"type": "text", "data": {"text": content}})
        return segments

    def _get_face_id(self, name: str) -> int:
        face_map = {
            "微笑": 1, "撇嘴": 2, "色": 3, "发呆": 4, "得意": 5,
            "流泪": 6, "害羞": 7, "闭嘴": 8, "睡": 9, "大哭": 10,
            "尴尬": 11, "发怒": 12, "调皮": 13, "呲牙": 14, "惊讶": 15,
            "难过": 16, "酷": 17, "冷汗": 18, "抓狂": 19, "吐": 20,
            "偷笑": 21, "可爱": 22, "白眼": 23, "傲慢": 24, "饥饿": 25,
            "困": 26, "惊恐": 27, "流汗": 28, "憨笑": 29, "大兵": 30,
            "奋斗": 31, "咒骂": 32, "疑问": 33, "嘘": 34, "晕": 35,
            "折磨": 36, "衰": 37, "骷髅": 38, "敲打": 39, "再见": 40,
            "擦汗": 41, "抠鼻": 42, "鼓掌": 43, "糗大了": 44, "坏笑": 45,
            "左哼哼": 46, "右哼哼": 47, "哈欠": 48, "鄙视": 49, "委屈": 50,
            "快哭了": 51, "阴险": 52, "亲亲": 53, "吓": 54, "可怜": 55,
            "菜刀": 56, "西瓜": 57, "啤酒": 58, "篮球": 59, "乒乓": 60,
            "咖啡": 61, "饭": 62, "猪头": 63, "玫瑰": 64, "凋谢": 65,
            "示爱": 66, "爱心": 67, "心碎": 68, "蛋糕": 69, "闪电": 70,
            "炸弹": 71, "刀": 72, "足球": 73, "瓢虫": 74, "便便": 75,
            "月亮": 76, "太阳": 77, "礼物": 78, "拥抱": 79, "强": 80,
            "弱": 81, "握手": 82, "胜利": 83, "抱拳": 84, "勾引": 85,
            "拳头": 86, "差劲": 87, "爱你": 88, "NO": 89, "OK": 90,
            "爱情": 91, "飞吻": 92, "跳跳": 93, "发抖": 94, "怄火": 95,
            "转圈": 96, "磕头": 97, "回头": 98, "跳绳": 99, "挥手": 100,
            "激动": 101, "街舞": 102, "献吻": 103, "左太极": 104, "右太极": 105,
            "双喜": 106, "鞭炮": 107, "灯笼": 108, "发财": 109, "K歌": 110,
            "购物": 111, "邮件": 112, "帅": 113, "喝彩": 114, "祈祷": 115,
            "爆筋": 116, "棒棒糖": 117, "喝奶": 118, "下面": 119, "香蕉": 120,
            "飞机": 121, "开车": 122, "高铁": 123, "火车": 124, "公交": 125,
            "自定义": 126, "帅哥": 127, "美女": 128,
            "苦笑": 207, "笑哭": 240, "狗头": 241, "滑稽": 242,
        }
        return face_map.get(name, 1)

    def build_nest_node(self, outer_user: dict, inner_messages: list) -> dict:
        inner_nodes = []
        for msg in inner_messages:
            if self.use_face_emoji:
                content_segments = self._parse_content_segments(msg["content"])
            else:
                content_segments = [{"type": "text", "data": {"text": msg["content"]}}]
            inner_nodes.append({
                "type": "node",
                "data": {
                    "user_id": str(msg["user_id"]),
                    "nickname": msg["nickname"],
                    "content": content_segments,
                }
            })

        return {
            "type": "node",
            "data": {
                "user_id": str(outer_user["user_id"]),
                "nickname": outer_user["nickname"],
                "content": inner_nodes,
            },
            "is_nest": True
        }

    async def generate_outer_chat_by_llm(
        self,
        context,
        chat_provider_id: str,
        unified_msg_origin: str,
        outer_sender: dict,
        commentators: list,
        nest_count: int,
        story_summary: str = "",
        theme: Optional[str] = None
    ) -> list:
        all_users = [outer_sender] + commentators
        if len(all_users) < 2:
            logger.warning("[SadStory] 外层用户不足，至少需要2人")
            return []

        outer_sender_name = outer_sender["nickname"]
        commentator_names = "、".join([c["nickname"] for c in commentators])

        prompt = self._build_outer_prompt(outer_sender_name, commentator_names, nest_count, story_summary, theme)

        try:
            if chat_provider_id:
                provider_id = chat_provider_id
            else:
                provider_id = await context.get_current_chat_provider_id(unified_msg_origin)
            llm_resp = await asyncio.wait_for(
                context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=120.0
            )
            raw = llm_resp.completion_text.strip()
            messages = self._parse_outer_llm_response(raw, all_users, nest_count)
            return messages
        except asyncio.TimeoutError:
            logger.error("[SadStory] 外层 LLM 生成超时")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 外层 LLM 生成失败: {e}")
            return []

    def _build_outer_prompt(self, outer_sender_name: str, commentator_names: str, nest_count: int, story_summary: str, theme: Optional[str]) -> str:
        if story_summary:
            story_hint = f"转发内容概要：{story_summary}"
        elif theme and theme.strip():
            story_hint = f"转发内容主题：{theme}"
        else:
            story_hint = "转发内容：一个有趣的故事"
        
        return f"""你是一个聊天记录生成器。请生成一段"引导+评论"式的群聊对话。

角色设定：
- 发起人（负责引导话题、转发内容）：{outer_sender_name}
- 围观网友（负责评论互动）：{commentator_names}

{story_hint}

核心要求：
1. 发起人不要像播音员一样陈述，要用真实的群聊口吻和强情绪起手（例如："卧槽兄弟们"、"大半夜给我看破防了"、"气死我了这人"），绝对避免书面语
2. 围观网友的反应要短促、自然。可以使用互联网黑话或表情符号代餐（例如："？"、"速发"、"gkd"、"搬好小板凳"、"前排"）
3. 发起人发 [转发消息] 占位符（表示转发了一条聊天记录，共{nest_count}条）
4. 围观网友看后发表评论，必须**高度关联转发内容中的具体细节**。不要泛泛而谈（如“太感人了”），要具体到点（例如：“看到他连夜找兽医那里我真蚌埠住了”、“这男的说话也太下头了吧”）
5. 每条消息1-2句话，很短很碎，像真人在群里打字

重要：评论内容必须跟转发的聊天记录内容相关！
- 绝不出现长篇大论，把一个完整的意思拆成2-3条短消息连发
- 彻底放弃标点符号规范：句末**不要用句号**；激动时连用符号（"!!!"、"？？？"）；多用空格或逗号断句。


格式要求：
- 在发起人转发内容的位置，用 [转发消息] 作为占位符
- 总消息条数控制在 {nest_count + 4} 到 {nest_count + 8} 条
- 发起人的消息占少数，主要是围观网友的评论，不要全是一个人说完另一个人说，可以有两人同时回复同一句话的交错感

示例结构：
1. 发起人：引起注意的消息
2. 网友：好奇/期待
3. 发起人：[转发消息]
4. 网友：评论1（要跟内容相关！）
5. 网友：评论2（要跟内容相关！）
...

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "说话人昵称", "content": "消息内容"}},
  ...
]"""

    def _parse_outer_llm_response(self, raw: str, all_users: list, nest_count: int) -> list:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        try:
            data = json.loads(raw[start:end])
            if not isinstance(data, list):
                return []

            messages = []
            user_map = {u["nickname"]: u for u in all_users}

            for item in data:
                speaker = item.get("speaker", "")
                content = item.get("content", "")
                if not speaker or not content:
                    continue

                user = user_map.get(speaker)
                if not user:
                    for nick, u in user_map.items():
                        if speaker in nick or nick in speaker:
                            user = u
                            break

                if user:
                    messages.append({
                        "user_id": user["user_id"],
                        "nickname": user["nickname"],
                        "content": content,
                        "is_forward_placeholder": content.strip() == "[转发消息]"
                    })

            return messages
        except json.JSONDecodeError:
            logger.error(f"[SadStory] 外层 JSON 解析失败: {raw[:100]}")
            return []

    async def generate_inner_chat_by_llm(
        self,
        context,
        chat_provider_id: str,
        unified_msg_origin: str,
        protagonists: list,
        bystanders: list,
        theme: Optional[str] = None,
        msg_count: Optional[int] = None
    ) -> list:
        if msg_count is None:
            msg_count = random.randint(self.inner_msg_min, self.inner_msg_max)

        all_users = protagonists + bystanders
        if len(all_users) < 2:
            logger.warning("[SadStory] 嵌套内层用户不足，至少需要2人")
            return []

        protagonist_names = "、".join([p["nickname"] for p in protagonists])
        bystander_names = "、".join([b["nickname"] for b in bystanders]) if bystanders else "无"

        if theme and theme.strip():
            prompt = self._build_theme_inner_prompt(protagonist_names, bystander_names, msg_count, theme)
        else:
            prompt = self._build_random_inner_prompt(protagonist_names, bystander_names, msg_count)

        try:
            if chat_provider_id:
                provider_id = chat_provider_id
            else:
                provider_id = await context.get_current_chat_provider_id(unified_msg_origin)
            llm_resp = await asyncio.wait_for(
                context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=120.0
            )
            raw = llm_resp.completion_text.strip()
            messages = self._parse_llm_response(raw, all_users)
            return messages
        except asyncio.TimeoutError:
            logger.error("[SadStory] 嵌套内层 LLM 生成超时")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 嵌套内层 LLM 生成失败: {e}")
            return []

    async def generate_full_inner_story(
        self,
        context,
        chat_provider_id: str,
        unified_msg_origin: str,
        protagonists: list,
        bystanders: list,
        theme: Optional[str] = None,
        total_msg_count: int = 20
    ) -> list:
        all_users = protagonists + bystanders
        if len(all_users) < 2:
            logger.warning("[SadStory] 内层故事用户不足，至少需要2人")
            return []

        protagonist_names = "、".join([p["nickname"] for p in protagonists])
        bystander_names = "、".join([b["nickname"] for b in bystanders]) if bystanders else "无"

        prompt = self._build_full_story_prompt(protagonist_names, bystander_names, total_msg_count, theme)

        try:
            if chat_provider_id:
                provider_id = chat_provider_id
            else:
                provider_id = await context.get_current_chat_provider_id(unified_msg_origin)
            llm_resp = await asyncio.wait_for(
                context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=180.0
            )
            raw = llm_resp.completion_text.strip()
            messages = self._parse_llm_response(raw, all_users)
            return messages
        except asyncio.TimeoutError:
            logger.error("[SadStory] 完整故事 LLM 生成超时")
            return []
        except Exception as e:
            logger.error(f"[SadStory] 完整故事 LLM 生成失败: {e}")
            return []

    def _get_sticker_instruction(self) -> str:
        if self.sticker_manager:
            return self.sticker_manager.generate_instruction()
        return ""

    def _build_full_story_prompt(self, protagonist_names: str, bystander_names: str, msg_count: int, theme: Optional[str]) -> str:
        theme_instruction = f"故事主题：{theme}" if theme and theme.strip() else "故事主题：随机（可以是感人的、搞笑的、八卦的、温馨的等）"
        sticker_instruction = self._get_sticker_instruction()
        
        return f"""你是一个聊天记录生成器。请生成一段完整的、有情节发展的群聊对话。

角色设定：
- 主角：{protagonist_names}（故事的主要讲述者/经历者）
- 围观网友：{bystander_names}（偶尔插嘴评论）

核心要求：
1. 这是一个完整的故事，要有起承转合
2. 主角通过连续发消息讲述/经历某件事
3. 每条消息1-2句话，很短很碎，像真人在群里打字
4. 故事要有具体内容：可以是分享一段经历、吐槽一件事、讲述一个故事等
5. 围观网友偶尔插嘴评论（总共3-5条即可）
6. {theme_instruction}
{sticker_instruction}
故事结构：
- 开头：引入话题/事件
- 发展：事情的经过
- 高潮：关键转折/情感爆发
- 结尾：结局/感慨

总消息条数：{msg_count} 条左右

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "说话人昵称", "content": "消息内容"}},
  ...
]"""

    def split_story_into_parts(self, messages: list, part_count: int) -> list:
        if not messages or part_count <= 0:
            return []
        
        if part_count == 1:
            return [messages]
        
        total_len = len(messages)
        base_size = total_len // part_count
        remainder = total_len % part_count
        
        parts = []
        start = 0
        
        for i in range(part_count):
            size = base_size + (1 if i < remainder else 0)
            if start + size <= total_len:
                parts.append(messages[start:start + size])
                start += size
            elif start < total_len:
                parts.append(messages[start:])
                break
        
        while len(parts) < part_count and parts:
            parts.append([])
        
        return [p for p in parts if p]

    def get_story_summary(self, messages: list) -> str:
        if not messages:
            return "一个有趣的故事"
        
        contents = [msg["content"] for msg in messages[:5]]
        return " ".join(contents)[:200]

    def _build_theme_inner_prompt(self, protagonist_names: str, bystander_names: str, msg_count: int, theme: str) -> str:
        sticker_instruction = self._get_sticker_instruction()
        return f"""你是一个聊天记录生成器。请生成一段真实的群聊对话。

角色设定：
- 主角：{protagonist_names}
- 围观网友：{bystander_names}

核心要求：
1. 模拟真实群聊，一个人可以连发几条消息，另一个人再回应
2. 每条消息1-2句话，很短很碎，像真人在群里打字
3. 对话要有具体内容：可以是吐槽某件事、讨论某个话题、分享经历、互相调侃等
4. 不要只发"哈哈"、"嗯"、"好的"这种无意义的消息
5. 围观网友偶尔插嘴，但主角是主要发言者
6. 主题方向：{theme}
{sticker_instruction}
风格参考：
- 节奏自然：A连发2-3条 → B回1-2条 → A再发
- 语气口语化，像朋友闲聊
- 可以有情绪表达、吐槽、调侃

消息条数：{msg_count} 条左右

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "说话人昵称", "content": "消息内容"}},
  ...
]"""

    def _build_random_inner_prompt(self, protagonist_names: str, bystander_names: str, msg_count: int) -> str:
        sticker_instruction = self._get_sticker_instruction()
        return f"""你是一个聊天记录生成器。请生成一段真实的群聊对话。

角色设定：
- 主角：{protagonist_names}
- 围观网友：{bystander_names}

核心要求：
1. 模拟真实群聊，一个人可以连发几条消息，另一个人再回应
2. 每条消息1-2句话，很短很碎，像真人在群里打字
3. 对话要有具体内容：可以是吐槽某件事、讨论某个话题、分享经历、互相调侃等
4. 不要只发"哈哈"、"嗯"、"好的"这种无意义的消息
5. 围观网友偶尔插嘴，但主角是主要发言者
6. 内容随机：可以是日常闲聊、吐槽、搞笑、八卦等
{sticker_instruction}
风格参考：
- 节奏自然：A连发2-3条 → B回1-2条 → A再发
- 语气口语化，像朋友闲聊
- 可以有情绪表达、吐槽、调侃

消息条数：{msg_count} 条左右

请严格按以下 JSON 数组格式输出，不要输出任何其他内容：
[
  {{"speaker": "说话人昵称", "content": "消息内容"}},
  ...
]"""

    def _parse_llm_response(self, raw: str, all_users: list) -> list:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        try:
            data = json.loads(raw[start:end])
            if not isinstance(data, list):
                return []

            messages = []
            user_map = {u["nickname"]: u for u in all_users}

            for item in data:
                speaker = item.get("speaker", "")
                content = item.get("content", "")
                if not speaker or not content:
                    continue

                user = user_map.get(speaker)
                if not user:
                    for nick, u in user_map.items():
                        if speaker in nick or nick in speaker:
                            user = u
                            break

                if user:
                    messages.append({
                        "user_id": user["user_id"],
                        "nickname": user["nickname"],
                        "content": content
                    })

            return messages
        except json.JSONDecodeError:
            logger.error(f"[SadStory] 嵌套内层 JSON 解析失败: {raw[:100]}")
            return []

    def merge_with_main_story(
        self,
        main_messages: list,
        nest_messages: list,
        insert_positions: Optional[list] = None
    ) -> list:
        if not nest_messages:
            return main_messages

        result = []
        for msg in main_messages:
            result.append(msg)

        total_len = len(result)

        if insert_positions is None:
            insert_positions = []
            nest_len = len(nest_messages)
            if nest_len == 1:
                insert_positions = [total_len // 2]
            else:
                step = max(1, total_len // (nest_len + 1))
                for i in range(1, nest_len + 1):
                    insert_positions.append(min(step * i, total_len))

        insert_positions = sorted(set(insert_positions))

        for i, pos in enumerate(insert_positions):
            if i < len(nest_messages):
                nest_node = nest_messages[i]
                result.insert(pos + i, nest_node)

        return result
