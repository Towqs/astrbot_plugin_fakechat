import asyncio
import random
import re
from astrbot.api.event import filter
from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from .nest import NestChatGenerator


class NestCommandHandler:
    def __init__(self, plugin):
        self.plugin = plugin
        self.nest_generator = NestChatGenerator({
            "nest_count_min": plugin.nest_count_min,
            "nest_count_max": plugin.nest_count_max,
            "inner_msg_min": plugin.inner_msg_min,
            "inner_msg_max": plugin.inner_msg_max,
            "use_face_emoji": plugin.use_face_emoji,
        })

    def _check_permission(self, event: AiocqhttpMessageEvent) -> bool:
        return self.plugin._check_permission(event)

    async def _check_and_set_cooldown(self, group_id: str) -> bool:
        return await self.plugin._check_and_set_cooldown(group_id)

    async def _clear_cooldown(self, group_id: str):
        await self.plugin._clear_cooldown(group_id)

    async def _resolve_user_info(self, bot, group_id: int, user_id: str) -> dict:
        return await self.plugin._resolve_user_info(bot, group_id, user_id)

    def _get_at_user_ids(self, event: AiocqhttpMessageEvent) -> list:
        return self.plugin._get_at_user_ids(event)

    async def handle_nest_command(self, event: AiocqhttpMessageEvent):
        if not self._check_permission(event):
            return

        self.plugin._reload_config()
        await self.plugin._import_webui_data()

        group_id_str = event.get_group_id()
        if not group_id_str or group_id_str == "0":
            yield event.plain_result("这个命令只能在群聊中使用哦~")
            return

        if not await self._check_and_set_cooldown(group_id_str):
            yield event.plain_result(f"太快了，休息一下吧~ ({self.plugin.cooldown_seconds}秒冷却)")
            return

        success = False
        try:
            message_str = event.message_str.partition(" ")[2].strip()
            at_ids = self._get_at_user_ids(event)
            group_id = int(group_id_str)

            if len(at_ids) < 2:
                yield event.plain_result(
                    "用法：/sadstory_nest @外层发送者 @主角A [@主角B] [主题]\n"
                    "示例：\n"
                    "  /sadstory_nest @咖啡 @守望者卢瑞恩\n"
                    "  /sadstory_nest @咖啡 @守望者卢瑞恩 校园暗恋"
                )
                return

            outer_sender_id = at_ids[0]
            protagonist_ids = at_ids[1:]

            outer_sender = await self._resolve_user_info(event.bot, group_id, outer_sender_id)
            protagonists = []
            for uid in protagonist_ids:
                info = await self._resolve_user_info(event.bot, group_id, uid)
                protagonists.append(info)

            logger.info(f"[SadStory] 嵌套模式 - 外层发送者: {outer_sender['nickname']}, 主角: {[p['nickname'] for p in protagonists]}")

            theme = re.sub(r'@\S+', '', message_str).strip()
            if len(theme) > 100:
                theme = theme[:100]

            is_dual_mode = len(protagonists) == 2
            is_single_mode = len(protagonists) == 1

            if not self.plugin.use_virtual_users:
                exclude_ids = {p["user_id"] for p in protagonists}
                exclude_ids.add(outer_sender["user_id"])
                bystander_needed = self.plugin.bystander_count + 5
                bystanders = await self.plugin._fetch_random_bystanders(
                    event.bot, group_id, bystander_needed, exclude_ids
                )
                user_pool = protagonists + bystanders
            else:
                user_pool = [
                    {"nickname": "路人甲", "user_id": "10001"},
                    {"nickname": "路人乙", "user_id": "10002"},
                    {"nickname": "路人丙", "user_id": "10003"},
                ]
                bystanders = user_pool[len(protagonists):]

            logger.info(f"[SadStory] 嵌套模式用户池大小: {len(user_pool)}")

            yield event.plain_result("正在生成嵌套聊天记录，请稍候...")

            main_messages = await self.plugin._generate_story(
                event, theme, protagonists if is_dual_mode else (protagonists if is_single_mode else None), user_pool
            )
            if not main_messages:
                yield event.plain_result("生成失败了，可能是用户池不足或 LLM 服务暂时不可用，请稍后再试~")
                return

            nest_count = random.randint(self.plugin.nest_count_min, self.plugin.nest_count_max)
            nest_messages = []

            for i in range(nest_count):
                inner_messages = await self.nest_generator.generate_inner_chat_by_llm(
                    self.plugin.context,
                    self.plugin.chat_provider_id,
                    event.unified_msg_origin,
                    protagonists,
                    bystanders,
                    theme=theme,
                    msg_count=random.randint(self.plugin.inner_msg_min, self.plugin.inner_msg_max)
                )
                if inner_messages:
                    nest_node = self.nest_generator.build_nest_node(outer_sender, inner_messages)
                    nest_messages.append(nest_node)
                    logger.info(f"[SadStory] 生成嵌套聊天记录 {i+1}/{nest_count}")

            final_messages = self.nest_generator.merge_with_main_story(main_messages, nest_messages)

            nodes = self._build_forward_nodes_with_nest(final_messages)
            await event.bot.send_group_forward_msg(
                group_id=int(group_id_str),
                messages=nodes,
            )
            success = True
        except Exception as e:
            logger.error(f"[SadStory] sadstory_nest 执行异常: {e}")
            yield event.plain_result(f"执行失败: {e}")
        finally:
            if not success:
                await self._clear_cooldown(group_id_str)

    def _build_forward_nodes_with_nest(self, messages: list) -> list:
        nodes = []
        for msg in messages:
            if msg.get("is_nest"):
                nodes.append({
                    "type": "node",
                    "data": {
                        "user_id": str(msg["data"]["user_id"]),
                        "nickname": msg["data"]["nickname"],
                        "content": msg["data"]["content"],
                    }
                })
            else:
                if self.plugin.use_face_emoji:
                    content_segments = self.plugin._parse_content_segments(msg["content"])
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
