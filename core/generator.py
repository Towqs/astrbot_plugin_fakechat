import json
import re
import asyncio
import base64
from astrbot.api import logger
from configs.constants import FACE_MAP

class StoryGeneratorMixin:
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
                
                # ==== 新特性：智能剥离句末标点 ====
                if getattr(self, "remove_ending_punctuation", True):
                    puncs = getattr(self, "punctuations_to_remove", "。，；;~")
                    if puncs:
                        # 仅剔除位于彻底末尾，或紧贴在 <sticker> 标签前方的特定标点
                        pattern = rf'[{re.escape(puncs)}]+\s*(?=<sticker|$)'
                        content = re.sub(pattern, '', content)

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
    def _build_forward_nodes(self, messages: list) -> list:
        nodes = []
        for msg in messages:
            content_segments = []

            if self.use_face_emoji or self.sticker_manager.enabled:
                content_segments.extend(self._parse_content_segments(msg["content"]))
            else:
                content_segments.append({"type": "text", "data": {"text": msg["content"]}})
                
            nodes.append({
                "type": "node",
                "data": {
                    "user_id": str(msg["user_id"]),
                    "nickname": msg["nickname"],
                    "content": content_segments,
                }
            })
        return nodes
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
                        # 兼容 Docker / 容器分离架构，直接转换为 base64 发送
                        try:
                            with open(image_path, "rb") as f:
                                b64_data = base64.b64encode(f.read()).decode()
                            segments.append({"type": "image", "data": {"file": f"base64://{b64_data}"}})
                        except Exception as e:
                            logger.error(f"[SadStory] 无法读取贴纸图片 {image_path}: {e}")
                    else:
                        logger.warning(f"[SadStory] 贴纸图片不存在: {sticker_name}")
            
            last_end = match.end()

        remaining = content[last_end:]
        if remaining:
            segments.append({"type": "text", "data": {"text": remaining}})
        if not segments:
            segments.append({"type": "text", "data": {"text": content}})
        return segments
