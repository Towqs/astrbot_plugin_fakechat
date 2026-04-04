import re
import asyncio
from typing import Any
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.event.filter import PermissionType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

class PersonaCommandsMixin:
    
    def _extract_pure_text(self, message_elements: list) -> str:
        text = ""
        for seg in message_elements:
            if seg.get("type") == "text":
                text += seg.get("data", {}).get("text", "")
        return text.strip()

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_capture")
    async def capture_persona(self, event: AiocqhttpMessageEvent):
        """抓取并总结用户人设。用法：/sadstory_capture @目标 或 /sadstory_capture QQ号 [最大抓取条数,默认50]"""
        raw_msg = event.message_str.partition(" ")[2].strip()
        if not raw_msg:
            yield event.plain_result("用法：/sadstory_capture @目标 或 /sadstory_capture QQ号 [提取句数(默认50)]")
            return

        at_ids = self._get_at_user_ids(event)
        target_id = None
        
        if at_ids:
            target_id = at_ids[0]
            raw_msg = re.sub(r'\[CQ:at,qq=\d+\]', '', raw_msg).strip()
            raw_msg = re.sub(r'@\S+', '', raw_msg).strip()
        else:
            parts = raw_msg.split()
            if parts and parts[0].isdigit():
                target_id = parts[0]
                parts = parts[1:]
                raw_msg = " ".join(parts).strip()

        if not target_id:
            yield event.plain_result("未识别到目标账号，请 @ 他或拼写正确QQ号")
            return
            
        target_count = 50
        if raw_msg.isdigit():
            target_count = int(raw_msg)
            if target_count < 10 or target_count > 100:
                yield event.plain_result("提取句数必须在 10 到 100 之间")
                return

        group_id = int(event.get_group_id() or "0")
        if group_id == 0:
            yield event.plain_result("此命令只能在群聊中使用")
            return

        yield event.plain_result(f"正在从群内疯狂翻找目标 {target_id} 的历史语录（目标{target_count}条），请稍候...")
        
        message_seq = 0
        all_texts = []
        max_rounds = 10 # 最多翻2000条群消息以防止死循环 (10 * 200 = 2000)
        
        for r in range(max_rounds):
            payloads = {
                "group_id": group_id,
                "count": 200,
            }
            if message_seq != 0:
                payloads["message_seq"] = message_seq

            try:
                result = await event.bot.api.call_action("get_group_msg_history", **payloads)
                round_messages = result.get("messages", [])
                if not round_messages:
                    break
                
                # message_id 通常是递增的，获取这批数据中最老的 seq
                message_seq = round_messages[0].get("message_id", 0) - 1
                if message_seq < 0: message_seq = 0
                
                for msg in reversed(round_messages): # 从新到旧遍历
                    sender_id = str(msg.get("sender", {}).get("user_id", ""))
                    if sender_id == str(target_id):
                        text = self._extract_pure_text(msg.get("message", []))
                        if text and len(text) > 1: # 过滤太短或者是纯图片的
                            all_texts.append(text)
                            if len(all_texts) >= target_count:
                                break
                                
                if len(all_texts) >= target_count:
                    break
            except Exception as e:
                logger.error(f"[SadStory] 获取群历史消息失败: {e}")
                break

        if not all_texts:
            yield event.plain_result(f"抱歉，往前翻找了 {r*200} 条群消息，完全没找到该用户的任何文字发言！是个究极潜水怪。")
            return

        yield event.plain_result(f"淘金成功！在往前翻了 {r+1} 页群历史后，成功提取到他的 {len(all_texts)} 句话。正在交由大模型做人格测写，预计10秒...")
        
        chat_history_str = "\\n".join([f"他说：{t}" for t in all_texts])
        system_prompt = (
            "你是一个极度犀利且毒舌的人物心理侧写师。你的任务是根据用户提供的数十条同一人的真实群聊历史发言，用最敏锐、通俗的词汇概括这张人的人设。\n"
            "要求：\n"
            "1. 请在 100 字以内完成，绝对不要啰嗦和寒暄。\n"
            "2. 总结内容必须包含：口头禅/口语习惯、情绪稳定性、潜在的互联网人格标签（如逗比、暴躁哥、谜语人、嘴臭王者等）。\n"
            "3. 只返回侧写内容，不带有任何 Markdown 符号或标题解释。"
        )
        
        try:
            if self.chat_provider_id:
                provider_id = self.chat_provider_id
            else:
                provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
                
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id, 
                    prompt=f"以下是这个人的一批群聊记录：\n{chat_history_str}",
                    system_prompt=system_prompt
                ),
                timeout=120.0
            )
            persona_card = llm_resp.completion_text.strip()
            
            # 获取名字保存
            info = await self._resolve_user_info(event.bot, group_id, target_id)
            nickname = info.get("nickname", target_id)
            
            await self.db.save_persona(str(target_id), nickname, persona_card)
            
            yield event.plain_result(f"✅ 人格夺取成功并已录入数据库！\n\n【捕获网名】：{nickname}\n【生成人设】：{persona_card}\n\n该用户以后只要被你 /sadstory 抓去做主角，大模型将强行被灌输此人设，无需二次扫描！")
            
        except Exception as e:
            logger.error(f"[SadStory] 人设总结失败: {e}")
            yield event.plain_result(f"人格测写失败: 大模型抽风了或超时 ({e})")
            
    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_listp")
    async def list_personas(self, event: AiocqhttpMessageEvent):
        """列出所有保存在数据库中的灵魂人设"""
        try:
            personas = await self.db.get_all_personas()
            if not personas:
                yield event.plain_result("当前人设库没有任何档案。请使用 /sadstory_capture 捕捉。")
                return
                
            lines = [f"🗂️ 独家人设档案室（共 {len(personas)} 份）"]
            for pid, nick, card in personas:
                preview = card[:30] + "..." if len(card) > 30 else card
                lines.append(f"👤 [{pid}] {nick} -> {preview}")
            lines.append("以后这些人当主角必定触发人格附体。")
            yield event.plain_result("\\n".join(lines))
        except Exception as e:
            logger.error(f"[SadStory] 获取人设列表失败: {e}")
            yield event.plain_result(f"查询失败: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("sadstory_delp")
    async def delete_persona(self, event: AiocqhttpMessageEvent):
        """删除某个被困在数据库里的人设。用法：/sadstory_delp QQ号 或 @某人"""
        raw = event.message_str.partition(" ")[2].strip()
        at_ids = self._get_at_user_ids(event)
        target_id = at_ids[0] if at_ids else raw.split()[0] if raw else ""
        
        if not target_id:
            yield event.plain_result("用法：/sadstory_delp QQ号 或 @某人")
            return
            
        success = await self.db.delete_persona(str(target_id))
        if success:
            yield event.plain_result(f"成功将 QQ {target_id} 的灵魂解绑，他终于自由了！下次生成使用默认性格。")
        else:
            yield event.plain_result(f"数据库中没有找到 QQ {target_id} 的人设记录。")
