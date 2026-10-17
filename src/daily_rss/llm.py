from __future__ import annotations

import logging
from typing import Any, Dict, List
import httpx

from daily_rss.html_cleaner import clean_html
from daily_rss.miniflux import CategoryGroup

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位世界顶级的人工智能、计算机系统与前沿科技主编兼情报分析师。
你的任务是将用户在 Miniflux 阅读器中订阅并分类整理的 RSS 资讯，提炼成一份高密度、逻辑严谨、极具可读性的「每日 RSS 科技深度简报」。

用户的订阅源已经按照专业的知识架构进行了分组（Categories）。请务必**严格保留并对齐用户的原生分组体系**，输出 Markdown 格式的日报：

### 报告排版结构要求：
1. **主标题**：`# 📰 每日 RSS 深度科技简报 (YYYY-MM-DD)`
2. **今日全局核心速览 (Executive Summary)**：
   - 跨板块综合提炼 3~5 条今日最重要、最具前瞻性或影响力的重磅动态（如：核心大模型发布、突破性算法、重要工程版本发布、基础设施进展）。
3. **按订阅板块深度精选 (Deep Dive by Categories)**：
   - **严格使用输入中的原生分类名称作为二级标题**，例如：`## 📂 00-Core&Frontier`、`## 📂 10-PostTraining`、`## 📂 20-EngineeringReleases` 等；
   - 每个分类板块开头，给出 1 句话的该领域「今日态势概括」；
   - 针对不同分类类型，突出不同的侧重点：
     * **工程与发布类 (Engineering / Releases)**：突出版本核心变更、性能提升、新增 API 或重要 bug 修复；
     * **算法与论文类 (Post-Training / Systems)**：突出要解决的核心痛点、方法创新点及关键实验结论；
     * **博客与观点类 (Blogs / Community)**：突出作者的核心立论、行业洞察与反思；
   - 重点条目格式：
     * `### [{文章标题}]({原文链接})`
     * `*来源: {订阅源名称} | 发布时间: {发布时间}*`
     * **核心要点**：用 1~3 点精炼提炼，直奔主题，避免空洞废话。
4. **语言风格**：专业严谨、中文自然流畅、术语准确。
"""


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        max_entries: int = 60,
        max_content_chars: int = 1500,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.max_entries = max_entries
        self.max_content_chars = max_content_chars
        self.timeout = timeout

    def format_grouped_entries_for_prompt(self, category_groups: List[CategoryGroup]) -> str:
        """
        按照用户的 Miniflux 原生分类（Category -> Feed -> Entry）构建层级输入提示词
        """
        sections: List[str] = []

        for cat in category_groups:
            if not cat.selected_entries:
                continue

            cat_header = (
                f"================================================================================\n"
                f"📂 分类板块: 【{cat.category_title}】 "
                f"(本次精选 {len(cat.selected_entries)} 篇 / 近期累计待读 {cat.total_unprocessed_count} 篇)\n"
                f"================================================================================"
            )
            cat_items: List[str] = [cat_header]

            for feed_id, feed_group in cat.feeds.items():
                feed_header = f"  📡 订阅源: [{feed_group.feed_title}]"
                cat_items.append(feed_header)

                for idx, entry in enumerate(feed_group.entries, 1):
                    title = entry.get("title", "无标题").strip()
                    url = entry.get("url", "").strip()
                    published_at = entry.get("published_at", "")

                    raw_content = entry.get("content") or entry.get("summary") or ""
                    cleaned = clean_html(raw_content)
                    if len(cleaned) > self.max_content_chars:
                        cleaned = cleaned[: self.max_content_chars] + "...[内容已截断]"

                    item_text = (
                        f"    ({idx}) 标题: {title}\n"
                        f"        发布时间: {published_at}\n"
                        f"        原文链接: {url}\n"
                        f"        正文摘要:\n{cleaned}\n"
                    )
                    cat_items.append(item_text)

            sections.append("\n".join(cat_items))

        return "\n\n".join(sections)

    def generate_daily_report(
        self,
        category_groups: List[CategoryGroup],
        report_date: str,
    ) -> str:
        """调用 LLM 生成对齐 Miniflux 分组结构的日报"""
        total_selected = sum(len(c.selected_entries) for c in category_groups)
        total_unprocessed = sum(c.total_unprocessed_count for c in category_groups)

        if total_selected == 0:
            return f"# 📰 每日 RSS 深度科技简报 ({report_date})\n\n近三天无未读新条目。"

        logger.info(
            "Formatting %d category groups (%d selected entries out of %d unprocessed) for LLM...",
            len(category_groups),
            total_selected,
            total_unprocessed,
        )

        formatted_context = self.format_grouped_entries_for_prompt(category_groups)

        user_prompt = (
            f"今天是 {report_date}。以下是你在 Miniflux 中各个订阅分组的最新条目，"
            f"共涵盖 {len(category_groups)} 个专业分类，精选纳入 {total_selected} 篇条目。\n\n"
            f"请严格按照每个分类板块，为我生成高质量的今日科技简报：\n\n"
            f"{formatted_context}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DailyRSSBot/1.0",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.5,
        }

        endpoint = f"{self.base_url}/chat/completions"
        logger.info(
            "Calling LLM API at %s (model: %s, payload size: %d chars)...",
            endpoint,
            self.model_name,
            len(user_prompt),
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error("LLM API returned error: %d - %s", resp.status_code, resp.text)
                resp.raise_for_status()

            data = resp.json()
            report_content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

        if not report_content:
            raise ValueError("LLM returned empty report content")

        logger.info("Successfully generated report (%d characters)", len(report_content))
        return report_content
