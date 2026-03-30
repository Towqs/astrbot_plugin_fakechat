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
        }, sticker_manager=plugin.sticker_manager)

    def _check_permission(self, event: AiocqhttpMessageEvent) -> bool:
        return self.plugin._check_permission(event)

    async def _check_and_set_cooldown(self, group_id: str) -> bool:
        return await self.plugin._check_and_set_cooldown(group_id)

    async def _clear_cooldown(self, group_id: str):
        await self.plugin._clear_cooldown(group_id)

    async def _check_daily_usage(self, event: AiocqhttpMessageEvent):
        return await self.plugin._check_daily_usage(event)

    async def _increment_daily_usage(self, event: AiocqhttpMessageEvent):
        return await self.plugin._increment_daily_usage(event)

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

        allowed, used, limit = await self._check_daily_usage(event)
        if not allowed:
            yield event.plain_result(f"今日使用次数已达上限（{used}/{limit}次），请明天再来~")
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

            if not self.plugin.use_virtual_users:
                exclude_ids = {p["user_id"] for p in protagonists}
                exclude_ids.add(outer_sender["user_id"])
                bystander_needed = self.plugin.bystander_count * 2 + 5
                all_bystanders = await self.plugin._fetch_random_bystanders(
                    event.bot, group_id, bystander_needed, exclude_ids
                )
                outer_commentators = all_bystanders[:self.plugin.bystander_count]
                inner_bystanders = all_bystanders[self.plugin.bystander_count:self.plugin.bystander_count * 2]
            else:
                outer_commentators = [
                    {"nickname": "路人甲", "user_id": "10001"},
                    {"nickname": "路人乙", "user_id": "10002"},
                ]
                inner_bystanders = [
                    {"nickname": "路人丙", "user_id": "10003"},
                    {"nickname": "路人丁", "user_id": "10004"},
                ]

            if len(outer_commentators) < 2:
                outer_commentators = outer_commentators if outer_commentators else [
                    {"nickname": "路人甲", "user_id": "10001"},
                    {"nickname": "路人乙", "user_id": "10002"},
                ]
            
            if len(inner_bystanders) < 2:
                inner_bystanders = inner_bystanders if inner_bystanders else [
                    {"nickname": "路人丙", "user_id": "10003"},
                    {"nickname": "路人丁", "user_id": "10004"},
                ]

            logger.info(f"[SadStory] 嵌套模式 - 外层围观网友: {[c['nickname'] for c in outer_commentators]}")
            logger.info(f"[SadStory] 嵌套模式 - 内层围观网友: {[c['nickname'] for c in inner_bystanders]}")

            yield event.plain_result("正在生成嵌套聊天记录，请稍候...")

            nest_count = random.randint(self.plugin.nest_count_min, self.plugin.nest_count_max)
            total_inner_msg = nest_count * random.randint(self.plugin.inner_msg_min, self.plugin.inner_msg_max)

            full_story = await self.nest_generator.generate_full_inner_story(
                self.plugin.context,
                self.plugin.chat_provider_id,
                event.unified_msg_origin,
                protagonists,
                inner_bystanders,
                theme=theme,
                total_msg_count=total_inner_msg
            )
            if not full_story:
                yield event.plain_result("故事生成失败，请稍后再试~")
                return

            story_parts = self.nest_generator.split_story_into_parts(full_story, nest_count)
            if not story_parts:
                yield event.plain_result("故事分割失败，请稍后再试~")
                return

            story_summary = self.nest_generator.get_story_summary(full_story)

            outer_messages = await self.nest_generator.generate_outer_chat_by_llm(
                self.plugin.context,
                self.plugin.chat_provider_id,
                event.unified_msg_origin,
                outer_sender,
                outer_commentators,
                nest_count,
                story_summary,
                theme
            )
            if not outer_messages:
                yield event.plain_result("外层消息生成失败，请稍后再试~")
                return

            nest_messages = []
            for i, part in enumerate(story_parts):
                if part:
                    nest_node = self.nest_generator.build_nest_node(outer_sender, part)
                    nest_messages.append(nest_node)
                    logger.info(f"[SadStory] 构建嵌套消息块 {i+1}/{len(story_parts)}")

            final_messages = self._merge_outer_with_nest(outer_messages, nest_messages)

            nodes = self._build_forward_nodes_with_nest(final_messages)
            await event.bot.send_group_forward_msg(
                group_id=int(group_id_str),
                messages=nodes,
            )
            success = True
            await self._increment_daily_usage(event)
        except Exception as e:
            logger.error(f"[SadStory] sadstory_nest 执行异常: {e}")
            yield event.plain_result(f"执行失败: {e}")
        finally:
            if not success:
                await self._clear_cooldown(group_id_str)

    def _merge_outer_with_nest(self, outer_messages: list, nest_messages: list) -> list:
        result = []
        nest_index = 0
        
        for msg in outer_messages:
            if msg.get("is_forward_placeholder"):
                if nest_index < len(nest_messages):
                    result.append(nest_messages[nest_index])
                    nest_index += 1
            else:
                result.append(msg)
        
        while nest_index < len(nest_messages):
            result.append(nest_messages[nest_index])
            nest_index += 1
        
        return result

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
