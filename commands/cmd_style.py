import json
import asyncio
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.event.filter import PermissionType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

class StyleCommandsMixin:
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
