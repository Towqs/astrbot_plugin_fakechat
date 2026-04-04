import os
import json
import asyncio
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.event.filter import PermissionType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from ..configs.constants import TEMPLATES_DIR

class TemplateCommandsMixin:
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
