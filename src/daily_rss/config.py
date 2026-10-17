from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# 自动从当前目录或父级加载 .env
load_dotenv()


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # --- Miniflux 配置 ---
    miniflux_base_url: str = field(
        default_factory=lambda: os.getenv("MINIFLUX_BASE_URL", "").rstrip("/")
    )
    miniflux_api_key: str = field(
        default_factory=lambda: os.getenv("MINIFLUX_API_KEY", "")
    )
    # 过滤天数，默认 3 天
    miniflux_days_limit: int = field(
        default_factory=lambda: _get_int("MINIFLUX_DAYS_LIMIT", 3)
    )
    # 默认不过滤状态，通过本地 sqlite 过滤。若指定 "unread" 则仅拉未读
    miniflux_status: Optional[str] = field(
        default_factory=lambda: os.getenv("MINIFLUX_STATUS") or None
    )
    # 分组过滤：仅包含指定分组（名称或ID，逗号隔开），为空则包含全部
    miniflux_include_categories: List[str] = field(
        default_factory=lambda: [
            c.strip() for c in os.getenv("MINIFLUX_INCLUDE_CATEGORIES", "").split(",") if c.strip()
        ]
    )
    # 分组排除：排除指定分组（名称或ID，逗号隔开）
    miniflux_exclude_categories: List[str] = field(
        default_factory=lambda: [
            c.strip() for c in os.getenv("MINIFLUX_EXCLUDE_CATEGORIES", "").split(",") if c.strip()
        ]
    )
    # 每个分类最多纳入的条目上限（防止某个论文源一下子刷出上百篇挤占其他分类）
    miniflux_max_per_category: int = field(
        default_factory=lambda: _get_int("MINIFLUX_MAX_PER_CATEGORY", 15)
    )

    # --- LLM 配置 ---
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    llm_model_name: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
    )
    # 单次日报最多纳入的条目数量（防止超出上下文）
    llm_max_entries: int = field(
        default_factory=lambda: _get_int("LLM_MAX_ENTRIES", 60)
    )
    # 单篇文章文本内容截断字数
    llm_max_content_chars: int = field(
        default_factory=lambda: _get_int("LLM_MAX_CONTENT_CHARS", 1500)
    )

    # --- SMTP 邮件推送配置 ---
    smtp_host: str = field(
        default_factory=lambda: os.getenv("SMTP_HOST", "")
    )
    smtp_port: int = field(
        default_factory=lambda: _get_int("SMTP_PORT", 465)
    )
    smtp_username: str = field(
        default_factory=lambda: os.getenv("SMTP_USERNAME", "")
    )
    smtp_password: str = field(
        default_factory=lambda: os.getenv("SMTP_PASSWORD", "")
    )
    smtp_use_ssl: bool = field(
        default_factory=lambda: _get_bool("SMTP_USE_SSL", True)
    )
    smtp_use_tls: bool = field(
        default_factory=lambda: _get_bool("SMTP_USE_TLS", False)
    )
    # 收件邮箱，多个用逗号隔开
    email_to: List[str] = field(
        default_factory=lambda: [
            e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()
        ]
    )
    email_from: str = field(
        default_factory=lambda: os.getenv("EMAIL_FROM") or os.getenv("SMTP_USERNAME", "")
    )
    email_from_name: str = field(
        default_factory=lambda: os.getenv("EMAIL_FROM_NAME", "Daily RSS Bot")
    )
    email_subject_prefix: str = field(
        default_factory=lambda: os.getenv("EMAIL_SUBJECT_PREFIX", "[每日 RSS 简报]")
    )

    # --- 调度与路径配置 ---
    on_schedule: str = field(
        default_factory=lambda: os.getenv("ON_SCHEDULE", "0 8 * * *").strip().strip('"').strip("'")
    )
    tz: str = field(
        default_factory=lambda: os.getenv("TZ", "Asia/Shanghai")
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")).resolve()
    )
    reports_dir: Path = field(
        default_factory=lambda: Path(os.getenv("REPORTS_DIR", "./reports")).resolve()
    )

    @property
    def is_email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password and self.email_to)


def load_config() -> Config:
    return Config()
