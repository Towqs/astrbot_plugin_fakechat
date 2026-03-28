import asyncio
import aiosqlite
from pathlib import Path
from datetime import date
from astrbot.api import logger


class SadStoryDB:

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = None
        self._tx_lock = asyncio.Lock()

    async def init(self):
        async with self._tx_lock:
            if self._conn:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = await aiosqlite.connect(str(self.db_path))
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS writing_styles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        content TEXT NOT NULL
                    )
                """)
                await self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS story_templates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        content TEXT NOT NULL
                    )
                """)
                await self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_daily_usage (
                        user_id TEXT NOT NULL,
                        usage_date TEXT NOT NULL,
                        count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (user_id, usage_date)
                    )
                """)
                await self._conn.commit()
                logger.info("[SadStory] 数据库初始化完成")
            except Exception as e:
                logger.error(f"[SadStory] 数据库初始化失败: {e}")
                if self._conn:
                    await self._conn.close()
                    self._conn = None
                raise

    async def close(self):
        async with self._tx_lock:
            if self._conn:
                await self._conn.close()
                self._conn = None

    async def _safe_rollback(self):
        try:
            await self._conn.rollback()
        except Exception as e:
            logger.warning(f"[SadStory] rollback 失败（可忽略）: {e}")

    async def get_styles(self) -> list[tuple[int, str, bool, str]]:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute("SELECT id, name, enabled, content FROM writing_styles ORDER BY id") as cur:
                return [(r["id"], r["name"], bool(r["enabled"]), r["content"]) async for r in cur]

    async def get_enabled_styles(self) -> list[str]:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute("SELECT content FROM writing_styles WHERE enabled=1") as cur:
                return [r["content"] async for r in cur]

    async def add_style(self, name: str, content: str, enabled: bool = True) -> int | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                cur = await self._conn.execute(
                    "INSERT INTO writing_styles (name, enabled, content) VALUES (?, ?, ?)",
                    (name, int(enabled), content)
                )
                await self._conn.commit()
                return cur.lastrowid
            except aiosqlite.IntegrityError:
                await self._safe_rollback()
                return None

    async def toggle_style(self, style_id: int) -> tuple[str, bool] | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                async with self._conn.execute("SELECT name, enabled FROM writing_styles WHERE id=?", (style_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await self._safe_rollback()
                    return None
                new_enabled = 1 - int(row["enabled"])
                await self._conn.execute("UPDATE writing_styles SET enabled=? WHERE id=?", (new_enabled, style_id))
                await self._conn.commit()
                return (row["name"], bool(new_enabled))
            except Exception as e:
                await self._safe_rollback()
                logger.error(f"[SadStory] toggle_style(id={style_id}) 失败: {e}")
                raise

    async def delete_style(self, style_id: int) -> str | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                async with self._conn.execute("SELECT name FROM writing_styles WHERE id=?", (style_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    return None
                await self._conn.execute("DELETE FROM writing_styles WHERE id=?", (style_id,))
                await self._conn.commit()
                return row["name"]
            except Exception as e:
                await self._safe_rollback()
                logger.error(f"[SadStory] delete_style(id={style_id}) 失败: {e}")
                raise

    async def get_templates(self) -> list[tuple[int, str, bool, str]]:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute("SELECT id, name, enabled, content FROM story_templates ORDER BY id") as cur:
                return [(r["id"], r["name"], bool(r["enabled"]), r["content"]) async for r in cur]

    async def get_enabled_templates(self) -> list[str]:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute("SELECT content FROM story_templates WHERE enabled=1") as cur:
                return [r["content"] async for r in cur]

    async def has_template_by_name(self, name: str) -> bool:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute("SELECT 1 FROM story_templates WHERE name=?", (name,)) as cur:
                return await cur.fetchone() is not None

    async def add_template(self, name: str, content: str, enabled: bool = True) -> int | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                cur = await self._conn.execute(
                    "INSERT INTO story_templates (name, enabled, content) VALUES (?, ?, ?)",
                    (name, int(enabled), content)
                )
                await self._conn.commit()
                return cur.lastrowid
            except aiosqlite.IntegrityError:
                await self._safe_rollback()
                return None

    async def toggle_template(self, tpl_id: int) -> tuple[str, bool] | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                async with self._conn.execute("SELECT name, enabled FROM story_templates WHERE id=?", (tpl_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await self._safe_rollback()
                    return None
                new_enabled = 1 - int(row["enabled"])
                await self._conn.execute("UPDATE story_templates SET enabled=? WHERE id=?", (new_enabled, tpl_id))
                await self._conn.commit()
                return (row["name"], bool(new_enabled))
            except Exception as e:
                await self._safe_rollback()
                logger.error(f"[SadStory] toggle_template(id={tpl_id}) 失败: {e}")
                raise

    async def delete_template(self, tpl_id: int) -> str | None:
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                async with self._conn.execute("SELECT name FROM story_templates WHERE id=?", (tpl_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    return None
                await self._conn.execute("DELETE FROM story_templates WHERE id=?", (tpl_id,))
                await self._conn.commit()
                return row["name"]
            except Exception as e:
                await self._safe_rollback()
                logger.error(f"[SadStory] delete_template(id={tpl_id}) 失败: {e}")
                raise

    async def get_user_daily_usage(self, user_id: str) -> int:
        today = date.today().isoformat()
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            async with self._conn.execute(
                "SELECT count FROM user_daily_usage WHERE user_id=? AND usage_date=?",
                (user_id, today)
            ) as cur:
                row = await cur.fetchone()
                return row["count"] if row else 0

    async def increment_user_daily_usage(self, user_id: str) -> int:
        today = date.today().isoformat()
        async with self._tx_lock:
            if self._conn is None:
                raise RuntimeError("[SadStory] 数据库未初始化")
            try:
                await self._conn.execute("""
                    INSERT INTO user_daily_usage (user_id, usage_date, count) VALUES (?, ?, 1)
                    ON CONFLICT(user_id, usage_date) DO UPDATE SET count = count + 1
                """, (user_id, today))
                await self._conn.commit()
                async with self._conn.execute(
                    "SELECT count FROM user_daily_usage WHERE user_id=? AND usage_date=?",
                    (user_id, today)
                ) as cur:
                    row = await cur.fetchone()
                    return row["count"] if row else 0
            except Exception as e:
                await self._safe_rollback()
                logger.error(f"[SadStory] increment_user_daily_usage 失败: {e}")
                raise
