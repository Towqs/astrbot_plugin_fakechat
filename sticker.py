import os
import json
import random
import re
from astrbot.api import logger
from astrbot.core.message.components import Image, Plain
from astrbot.core.star.star_tools import StarTools

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MEME_MANAGER_DATA_DIR = os.path.join(os.path.dirname(PLUGIN_DIR), "astrbot_plugin_meme_manager_lite", "data")
MEME_STICKERS_FILE = os.path.join(MEME_MANAGER_DATA_DIR, "memes_data.json")


class StickerManager:
    def __init__(self, enabled: bool = False, frequency: int = 10):
        self.enabled = enabled
        self.frequency = frequency
        self._stickers_cache = None
        self._stickers_dir = None

    def _get_stickers_dir(self) -> str:
        if self._stickers_dir is None:
            default_memes_dir = os.path.join(
                os.path.dirname(PLUGIN_DIR), 
                "astrbot_plugin_meme_manager_lite", 
                "default", 
                "memes"
            )
            # 优先尝试从 AstrBot 运行数据目录获取图片
            try:
                data_dir = StarTools.get_data_dir("astrbot_plugin_meme_manager_lite")
                run_memes_dir = os.path.join(data_dir, "memes")
                if os.path.exists(run_memes_dir):
                    self._stickers_dir = run_memes_dir
                    return self._stickers_dir
            except Exception:
                pass

            if os.path.exists(default_memes_dir):
                self._stickers_dir = default_memes_dir
            else:
                self._stickers_dir = default_memes_dir
        return self._stickers_dir

    def _get_sticker_image_path(self, sticker_name: str) -> str:
        stickers_dir = self._get_stickers_dir()
        sticker_dir = os.path.join(stickers_dir, sticker_name)
        if os.path.exists(sticker_dir):
            try:
                image_files = []
                for file in os.listdir(sticker_dir):
                    if file.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                        image_files.append(os.path.join(sticker_dir, file))
                if image_files:
                    return random.choice(image_files)
            except Exception as e:
                logger.warning(f"[SadStory] 读取贴纸目录失败: {e}")
        return None

    def load_stickers(self) -> dict:
        if not self.enabled:
            return {}
        if self._stickers_cache is not None:
            return self._stickers_cache
        
        try:
            # 优先从实际的数据运行目录加载配置
            try:
                data_dir = StarTools.get_data_dir("astrbot_plugin_meme_manager_lite")
                run_data_file = os.path.join(data_dir, "memes_data.json")
                if os.path.exists(run_data_file):
                    with open(run_data_file, "r", encoding="utf-8") as f:
                        self._stickers_cache = json.load(f)
                    logger.info(f"[SadStory] 从数据目录加载了 {len(self._stickers_cache)} 个贴纸")
                    return self._stickers_cache
            except Exception:
                pass

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
        
        # 将更多贴纸放入 prompt 并给予更加规范的要求
        sticker_names = list(stickers.keys())[:30]
        sticker_list = "、".join(sticker_names)
        
        return f"""
【贴纸表情包支持】
当前对话可插入自定义贴纸（千万不可捏造列表外的不存在贴纸）。
✅ 可用贴纸名：{sticker_list}
使用格式：在对话中合适位置插入 <sticker name="贴纸名"/>。此标签可以直接作为独立的一条消息，也可附在句末。
注意：仅在情感较强烈时偶尔使用，避免过度依赖，插入贴纸的概率请控制在 {self.frequency}% 左右。
"""

    def update_config(self, enabled: bool = False, frequency: int = 10):
        self.enabled = enabled
        self.frequency = frequency
        self._stickers_cache = None

    def parse_sticker_tags(self, text: str) -> list:
        if not self.enabled:
            return [Plain(text)]
        
        components = []
        pattern = r"(<sticker\s+name=\"([^\"]+)\".*?/>)"
        parts = re.split(pattern, text, flags=re.DOTALL)
        
        i = 0
        while i < len(parts):
            part = parts[i]
            if re.match(r"<sticker\s+name=\"([^\"]+)\".*?/>", part):
                name_match = re.search(r'name="([^"]+)"', part)
                if name_match:
                    sticker_name = name_match.group(1)
                    image_path = self._get_sticker_image_path(sticker_name)
                    if image_path:
                        components.append(Image.fromFileSystem(image_path))
                    else:
                        logger.warning(f"[SadStory] 贴纸图片不存在: {sticker_name}")
                i += 1
            elif part and part.strip():
                components.append(Plain(part.strip()))
                i += 1
            else:
                i += 1
        
        if not components:
            components.append(Plain(text))
        
        return components
