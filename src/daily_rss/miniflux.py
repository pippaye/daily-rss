from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import httpx

logger = logging.getLogger(__name__)


@dataclass
class FeedGroup:
    feed_id: int
    feed_title: str
    site_url: str
    entries: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CategoryGroup:
    category_id: int
    category_title: str
    total_unprocessed_count: int
    feeds: Dict[int, FeedGroup] = field(default_factory=dict)
    selected_entries: List[Dict[str, Any]] = field(default_factory=list)


class MinifluxClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {
            "X-Auth-Token": self.api_key,
            "User-Agent": "DailyRSSBot/1.0 (+https://github.com/ashenye/daily-rss)",
            "Accept": "application/json",
        }

    def test_connection(self) -> Dict[str, Any]:
        """测试 Miniflux 连接与鉴权"""
        url = f"{self.base_url}/v1/me"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def get_categories(self) -> List[Dict[str, Any]]:
        """获取所有分类及其条目统计"""
        url = f"{self.base_url}/v1/categories?counts=true"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def fetch_recent_entries(
        self,
        days_limit: int = 3,
        status: Optional[str] = None,
        max_total: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        拉取近 N 天的条目。
        :param days_limit: 过去的天数（如 3 天）
        :param status: 条目状态（如 'unread'，若为 None 则拉取所有状态）
        :param max_total: 最大拉取上限保护
        """
        now_ts = int(time.time())
        published_after = now_ts - (days_limit * 86400)
        since_dt = datetime.fromtimestamp(published_after, tz=timezone.utc)
        logger.info(
            "Fetching entries published after %s UTC (past %d days)...",
            since_dt.strftime("%Y-%m-%d %H:%M:%S"),
            days_limit,
        )

        entries: List[Dict[str, Any]] = []
        limit = 100
        offset = 0

        with httpx.Client(timeout=self.timeout) as client:
            while len(entries) < max_total:
                params: Dict[str, Any] = {
                    "published_after": published_after,
                    "order": "published_at",
                    "direction": "desc",
                    "limit": limit,
                    "offset": offset,
                }
                if status:
                    params["status"] = status

                url = f"{self.base_url}/v1/entries"
                resp = client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()

                data = resp.json()
                batch_entries = data.get("entries", [])
                if not batch_entries:
                    break

                entries.extend(batch_entries)
                offset += len(batch_entries)

                total_available = data.get("total", 0)
                if len(entries) >= total_available or len(batch_entries) < limit:
                    break

        logger.info("Successfully fetched %d entries from Miniflux", len(entries))
        return entries

    @staticmethod
    def group_and_quota_entries(
        entries: List[Dict[str, Any]],
        max_per_category: int = 15,
        include_categories: Optional[List[str]] = None,
        exclude_categories: Optional[List[str]] = None,
    ) -> List[CategoryGroup]:
        """
        将扁平的条目列表按用户的 Miniflux 原生结构（Category -> Feed -> Entry）聚类，
        并应用分类过滤与单分类配额保护（Quota）。
        """
        include_set: Set[str] = {c.lower() for c in (include_categories or []) if c.strip()}
        exclude_set: Set[str] = {c.lower() for c in (exclude_categories or []) if c.strip()}

        # 1. 按 category_id 聚集所有条目
        cat_buckets: Dict[int, Dict[str, Any]] = {}

        for entry in entries:
            feed_info = entry.get("feed") or {}
            category_info = feed_info.get("category") or {}

            cat_id = category_info.get("id", 0)
            cat_title = category_info.get("title", "未分类").strip()
            cat_title_lower = cat_title.lower()

            # 排除规则校验
            if exclude_set and (cat_title_lower in exclude_set or str(cat_id) in exclude_set):
                continue
            # 包含规则校验
            if include_set and (cat_title_lower not in include_set and str(cat_id) not in include_set):
                continue

            if cat_id not in cat_buckets:
                cat_buckets[cat_id] = {
                    "id": cat_id,
                    "title": cat_title,
                    "entries": [],
                }
            cat_buckets[cat_id]["entries"].append(entry)

        # 2. 对每个分类按配额截取，并按 Feed 聚合
        category_groups: List[CategoryGroup] = []

        # 按分类标题自然排序（如 00-Core..., 10-Post..., 20-Eng...）
        sorted_cat_ids = sorted(cat_buckets.keys(), key=lambda cid: cat_buckets[cid]["title"])

        for cid in sorted_cat_ids:
            bucket = cat_buckets[cid]
            all_cat_entries = bucket["entries"]
            total_count = len(all_cat_entries)

            # 单分类配额保护：取最新的 max_per_category 篇
            selected = all_cat_entries[:max_per_category]

            # 在分类内按 Feed 归纳
            feeds_map: Dict[int, FeedGroup] = {}
            for e in selected:
                f_info = e.get("feed") or {}
                f_id = f_info.get("id", 0)
                f_title = f_info.get("title", "默认订阅源").strip()
                site_url = f_info.get("site_url", "")

                if f_id not in feeds_map:
                    feeds_map[f_id] = FeedGroup(
                        feed_id=f_id,
                        feed_title=f_title,
                        site_url=site_url,
                        entries=[],
                    )
                feeds_map[f_id].entries.append(e)

            category_groups.append(
                CategoryGroup(
                    category_id=cid,
                    category_title=bucket["title"],
                    total_unprocessed_count=total_count,
                    feeds=feeds_map,
                    selected_entries=selected,
                )
            )

        return category_groups
