import asyncio
import json
import random
import re
from typing import Optional
from astrbot.api import logger


class NestChatGenerator:
    def __init__(self, config: dict):
        self.nest_count_min = config.get("nest_count_min", 1)
        self.nest_count_max = config.get("nest_count_max", 3)
        self.inner_msg_min = config.get("inner_msg_min", 3)
        self.inner_msg_max = config.get("inner_msg_max", 8)
        self.use_face_emoji = config.get("use_face_emoji", False)

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
            prompt = self._build_random_inner_prompt(protagonist_names, bystander_names, msg_count)
        else:
            prompt = self._build_theme_inner_prompt(protagonist_names, bystander_names, msg_count, "日常闲聊")

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

    def _build_theme_inner_prompt(self, protagonist_names: str, bystander_names: str, msg_count: int, theme: str) -> str:
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
