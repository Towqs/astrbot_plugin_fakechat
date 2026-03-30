import os
import json
from astrbot.api import logger

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MEME_MANAGER_DATA_DIR = os.path.join(os.path.dirname(PLUGIN_DIR), "astrbot_plugin_meme_manager_lite", "data")
MEME_STICKERS_FILE = os.path.join(MEME_MANAGER_DATA_DIR, "memes_data.json")


class StickerManager:
    def __init__(self, enabled: bool = False, frequency: int = 10):
        self.enabled = enabled
        self.frequency = frequency
        self._stickers_cache = None

    def load_stickers(self) -> dict:
        if not self.enabled:
            return {}
        if self._stickers_cache is not None:
            return self._stickers_cache
        
        try:
            if os.path.exists(MEME_STICKERS_FILE):
                with open(MEME_STICKERS_FILE, "r", encoding="utf-8") as f:
                    self._stickers_cache = json.load(f)
                logger.info(f"[SadStory] 加载了 {len(self._stickers_cache)} 个贴纸")
                return self._stickers_cache
            
            default_file = os.path.join(
                os.path.dirname(PLUGIN_DIR), 
                "astrbot_plugin_meme_manager_lite", 
                "default", 
                "memes_data.json"
            )
            if os.path.exists(default_file):
                with open(default_file, "r", encoding="utf-8") as f:
                    self._stickers_cache = json.load(f)
                logger.info(f"[SadStory] 从默认配置加载了 {len(self._stickers_cache)} 个贴纸")
                return self._stickers_cache
        except Exception as e:
            logger.warning(f"[SadStory] 加载贴纸数据失败: {e}")
        
        return {}

    def generate_instruction(self) -> str:
        if not self.enabled:
            return ""
        
        stickers = self.load_stickers()
        if not stickers:
            return ""
        
        sticker_list = []
        for name, desc in stickers.items():
            sticker_list.append(f"  - [{name}]：{desc}")
        
        return f"""
可用贴纸（在消息中插入 <sticker name="贴纸名"/>）：
{chr(10).join(sticker_list)}

贴纸使用规则：
1. 只有在情绪强烈时才使用贴纸，不要每条消息都用
2. 使用频率控制在 {self.frequency}% 以内
3. 选择与当前情绪/场景匹配的贴纸
4. 贴纸放在消息末尾，例如："卧槽太离谱了 <sticker name="angry"/>"
"""

    def update_config(self, enabled: bool = False, frequency: int = 10):
        self.enabled = enabled
        self.frequency = frequency
        self._stickers_cache = None
