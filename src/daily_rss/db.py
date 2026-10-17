from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_parent_dir()
        self.init_schema()

    def _ensure_parent_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """初始化数据表结构并支持字段迁移"""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_entries (
                    entry_id INTEGER PRIMARY KEY,
                    category_id INTEGER,
                    category_title TEXT,
                    feed_id INTEGER,
                    feed_title TEXT,
                    title TEXT,
                    url TEXT,
                    published_at TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    report_date TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_entries_date 
                ON processed_entries(report_date);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_entries_cat 
                ON processed_entries(category_id);
                """
            )

            # 兼容老表结构迁移新增字段
            cursor = conn.execute("PRAGMA table_info(processed_entries)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if "category_id" not in existing_cols:
                conn.execute("ALTER TABLE processed_entries ADD COLUMN category_id INTEGER")
            if "category_title" not in existing_cols:
                conn.execute("ALTER TABLE processed_entries ADD COLUMN category_title TEXT")
            if "feed_id" not in existing_cols:
                conn.execute("ALTER TABLE processed_entries ADD COLUMN feed_id INTEGER")

            conn.commit()
        logger.debug("Database initialized at %s", self.db_path)

    def get_processed_ids(self, ids: Iterable[int]) -> Set[int]:
        """批量查询给定的 ID 中哪些已经在数据库中记录为已处理"""
        id_list = list(ids)
        if not id_list:
            return set()

        processed: Set[int] = set()
        batch_size = 500
        with self._get_connection() as conn:
            for i in range(0, len(id_list), batch_size):
                batch = id_list[i : i + batch_size]
                placeholders = ",".join("?" for _ in batch)
                cursor = conn.execute(
                    f"SELECT entry_id FROM processed_entries WHERE entry_id IN ({placeholders})",
                    batch,
                )
                for row in cursor.fetchall():
                    processed.add(row["entry_id"])
        return processed

    def filter_unprocessed(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤出尚未被程序处理过的条目"""
        if not entries:
            return []
        ids = [e["id"] for e in entries if "id" in e]
        processed_ids = self.get_processed_ids(ids)
        unprocessed = [e for e in entries if e.get("id") not in processed_ids]
        logger.info(
            "Filter result: %d total entries, %d already processed, %d new unprocessed",
            len(entries),
            len(processed_ids),
            len(unprocessed),
        )
        return unprocessed

    def mark_as_processed(self, entries: List[Dict[str, Any]], report_date: str) -> None:
        """将条目标记为已被程序处理，记录分类和订阅源详细信息"""
        if not entries:
            return

        records = []
        for e in entries:
            feed_info = e.get("feed") or {}
            category_info = feed_info.get("category") or {}

            category_id = category_info.get("id")
            category_title = category_info.get("title", "")
            feed_id = feed_info.get("id")
            feed_title = feed_info.get("title", "")

            records.append(
                (
                    e.get("id"),
                    category_id,
                    category_title,
                    feed_id,
                    feed_title,
                    e.get("title", ""),
                    e.get("url", ""),
                    e.get("published_at", ""),
                    report_date,
                )
            )

        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO processed_entries 
                (entry_id, category_id, category_title, feed_id, feed_title, title, url, published_at, report_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

        logger.info("Marked %d entries as processed in local database", len(records))

    def get_total_processed_count(self) -> int:
        """获取历史上已处理的总条目数"""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) AS cnt FROM processed_entries")
            row = cursor.fetchone()
            return row["cnt"] if row else 0
