from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from daily_rss.config import Config, load_config
from daily_rss.db import Database
from daily_rss.llm import LLMClient
from daily_rss.mailer import Mailer
from daily_rss.miniflux import MinifluxClient
from daily_rss.scheduler import Scheduler

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class DailyRSSApp:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(self.config.data_dir / "processed.db")
        self.miniflux = MinifluxClient(
            base_url=self.config.miniflux_base_url,
            api_key=self.config.miniflux_api_key,
        )
        self.llm = LLMClient(
            base_url=self.config.llm_base_url,
            api_key=self.config.llm_api_key,
            model_name=self.config.llm_model_name,
            max_entries=self.config.llm_max_entries,
            max_content_chars=self.config.llm_max_content_chars,
        )
        self.mailer = Mailer(
            host=self.config.smtp_host,
            port=self.config.smtp_port,
            username=self.config.smtp_username,
            password=self.config.smtp_password,
            use_ssl=self.config.smtp_use_ssl,
            use_tls=self.config.smtp_use_tls,
            from_email=self.config.email_from,
            from_name=self.config.email_from_name,
            subject_prefix=self.config.email_subject_prefix,
        )

    def get_current_date_str(self) -> str:
        try:
            tz = ZoneInfo(self.config.tz)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).strftime("%Y-%m-%d")

    def show_categories(self) -> None:
        """打印 Miniflux 中的所有分组及未读统计"""
        logger.info("Fetching categories from Miniflux...")
        cats = self.miniflux.get_categories()
        print(f"\n{'='*70}")
        print(f"Miniflux 分组清单 (共 {len(cats)} 个分类)")
        print(f"{'='*70}")
        print(f"{'ID':<6} | {'分类名称':<28} | {'Feeds 订阅数':<12} | {'未读条目数'}")
        print(f"{'-'*70}")
        for c in cats:
            cid = c.get("id")
            title = c.get("title", "")
            feed_count = c.get("feed_count", 0)
            unread = c.get("total_unread", 0)
            print(f"{cid:<6} | {title:<28} | {feed_count:<12} | {unread}")
        print(f"{'='*70}\n")

    def run_daily_job(self, dry_run: bool = False) -> None:
        """核心处理链路：Miniflux抓取 -> SQLite过滤 -> 层级聚类与配额 -> LLM生成 -> 邮件推送 -> 写入SQLite"""
        report_date = self.get_current_date_str()
        logger.info("=== Starting Daily RSS Pipeline for date: %s ===", report_date)

        if not self.config.miniflux_base_url or not self.config.miniflux_api_key:
            raise ValueError("MINIFLUX_BASE_URL or MINIFLUX_API_KEY is not configured.")

        # 1. 抓取近 N 天的条目
        raw_entries = self.miniflux.fetch_recent_entries(
            days_limit=self.config.miniflux_days_limit,
            status=self.config.miniflux_status,
        )

        if not raw_entries:
            logger.info("No entries found in Miniflux within the past %d days.", self.config.miniflux_days_limit)
            return

        # 2. 对比本地 SQLite，过滤掉程序已经处理过的条目
        unprocessed = self.db.filter_unprocessed(raw_entries)
        if not unprocessed:
            logger.info("All %d recent entries have already been processed previously. Nothing to do.", len(raw_entries))
            return

        # 3. 按 Miniflux 原生分组进行层级聚类与配额控制
        category_groups = self.miniflux.group_and_quota_entries(
            entries=unprocessed,
            max_per_category=self.config.miniflux_max_per_category,
            include_categories=self.config.miniflux_include_categories,
            exclude_categories=self.config.miniflux_exclude_categories,
        )

        total_selected = sum(len(c.selected_entries) for c in category_groups)
        total_raw_unprocessed = sum(c.total_unprocessed_count for c in category_groups)

        logger.info(
            "Grouped into %d categories. Total unprocessed: %d, selected after quota: %d",
            len(category_groups),
            total_raw_unprocessed,
            total_selected,
        )

        # 演练模式输出预览
        if dry_run:
            logger.info("[DRY RUN] Showing categorized breakdown without calling LLM or writing DB:")
            print(f"\n{'='*75}")
            print(f"📊 [DRY RUN] 待处理条目分类概览 (共 {len(category_groups)} 个分类，精选 {total_selected}/{total_raw_unprocessed} 篇)")
            print(f"{'='*75}")
            for cat in category_groups:
                print(f"\n📂 分类: 【{cat.category_title}】 (待读累计 {cat.total_unprocessed_count} 篇，本期纳入 {len(cat.selected_entries)} 篇):")
                for fid, fg in cat.feeds.items():
                    print(f"   📡 订阅源: [{fg.feed_title}] ({len(fg.entries)} 篇)")
                    for e in fg.entries[:3]:
                        print(f"      • {e.get('title')} ({e.get('published_at')})")
                        print(f"        链接: {e.get('url')}")
                    if len(fg.entries) > 3:
                        print(f"      ... 及其余 {len(fg.entries) - 3} 篇")
            print(f"\n{'='*75}\n")
            return

        if total_selected == 0:
            logger.info("No entries to process after category filtering.")
            return

        # 4. 调用 LLM 生成日报
        if not self.config.llm_api_key:
            raise ValueError("LLM_API_KEY is not configured.")

        report_markdown = self.llm.generate_daily_report(category_groups, report_date)

        # 5. 本地归档保存 Markdown
        self.config.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.config.reports_dir / f"daily-{report_date}.md"
        report_path.write_text(report_markdown, encoding="utf-8")
        logger.info("Saved local markdown report to: %s", report_path)

        # 6. 邮件推送
        if self.config.is_email_configured:
            logger.info("Sending report to %s via email...", ", ".join(self.config.email_to))
            self.mailer.send_report(
                recipients=self.config.email_to,
                report_markdown=report_markdown,
                report_date=report_date,
            )
        else:
            logger.warning(
                "SMTP email configuration is incomplete. Report saved locally but NOT sent via email. "
                "Please configure SMTP_* and EMAIL_TO in your .env file."
            )

        # 7. 处理成功，将这些选取的条目标记进 SQLite（标记为程序已读）
        entries_to_mark = [e for c in category_groups for e in c.selected_entries]
        self.db.mark_as_processed(entries_to_mark, report_date)
        logger.info("=== Daily RSS Pipeline completed successfully for %s! ===", report_date)

    def test_miniflux(self) -> None:
        """测试 Miniflux 连接"""
        logger.info("Testing Miniflux connection to %s...", self.config.miniflux_base_url)
        info = self.miniflux.test_connection()
        username = info.get("username", "unknown")
        logger.info("Miniflux connection successful! Logged in as user: %s (ID: %s)", username, info.get("id"))

    def test_email(self) -> None:
        """测试邮件发送"""
        if not self.config.is_email_configured:
            logger.error("Cannot test email: SMTP configuration is incomplete in .env.")
            return

        logger.info("Sending test email to %s...", ", ".join(self.config.email_to))
        test_md = (
            "# 📧 Daily RSS Bot 测试邮件\n\n"
            "这是一封来自 Daily RSS 定时程序的测试邮件。\n\n"
            "- **SMTP 服务器**: " + self.config.smtp_host + "\n"
            "- **当前时区**: " + self.config.tz + "\n"
            "- **测试时间**: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
            "如果你收到了这封邮件，说明邮件推送配置正常！"
        )
        self.mailer.send_report(
            recipients=self.config.email_to,
            report_markdown=test_md,
            report_date=self.get_current_date_str(),
        )
        logger.info("Test email sent successfully!")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily-rss",
        description="基于 Miniflux 分组架构与大语言模型的每日资讯简报生成器",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="输出详细调试日志",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="子命令",
        description="可用操作：",
    )

    # 1. run 子命令
    run_parser = subparsers.add_parser(
        "run",
        help="执行一次资讯简报生成任务（抓取 -> 过滤 -> LLM生成 -> 邮件推送 -> 标记已读）",
    )
    run_parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="演练模式：按分类树状打印待处理条目预览，不调用 LLM、不发邮件、不写数据库",
    )

    # 2. daemon 子命令
    subparsers.add_parser(
        "daemon",
        help="以常驻守护进程模式启动，按照 ON_SCHEDULE 配置定时循环执行",
    )

    # 3. categories 子命令
    subparsers.add_parser(
        "categories",
        aliases=["cat", "ls"],
        help="列出 Miniflux 中的所有分组、订阅源数量与未读条目数",
    )

    # 4. test 子命令及子目标
    test_parser = subparsers.add_parser(
        "test",
        help="测试外部依赖项与配置连通性",
    )
    test_subparsers = test_parser.add_subparsers(
        dest="test_target",
        title="测试目标",
        required=True,
    )
    test_subparsers.add_parser(
        "miniflux",
        help="测试 Miniflux API 连接状态与身份认证",
    )
    test_subparsers.add_parser(
        "email",
        help="向 EMAIL_TO 发送一封测试排版邮件验证 SMTP 配置",
    )

    return parser


def main() -> None:
    parser = build_parser()

    # 如果没有提供任何参数，打印帮助信息并退出
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    setup_logging(args.verbose)

    config = load_config()
    app = DailyRSSApp(config)

    if args.command == "run":
        app.run_daily_job(dry_run=args.dry_run)
    elif args.command == "daemon":
        scheduler = Scheduler(cron_expr=config.on_schedule, tz_name=config.tz)
        scheduler.run_forever(job_func=lambda: app.run_daily_job(dry_run=False))
    elif args.command in ("categories", "cat", "ls"):
        app.show_categories()
    elif args.command == "test":
        if args.test_target == "miniflux":
            app.test_miniflux()
        elif args.test_target == "email":
            app.test_email()
        else:
            parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
