from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo
from croniter import croniter

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, cron_expr: str, tz_name: str = "Asia/Shanghai"):
        self.cron_expr = cron_expr.strip()
        self.tz_name = tz_name
        try:
            self.tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning("Invalid timezone '%s', falling back to UTC", tz_name)
            self.tz = ZoneInfo("UTC")

        # 校验 cron 表达式格式
        if not croniter.is_valid(self.cron_expr):
            raise ValueError(f"Invalid cron expression: '{self.cron_expr}'")

        self._stop_requested = False

    def _setup_signal_handlers(self) -> None:
        def _handle_exit(signum, frame):
            logger.info("Shutdown signal received (%s). Exiting scheduler...", signum)
            self._stop_requested = True

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

    def run_forever(self, job_func: Callable[[], None]) -> None:
        """根据 Cron 规则持续循环调度任务"""
        self._setup_signal_handlers()
        logger.info(
            "Scheduler started. Cron schedule: '%s', Timezone: %s",
            self.cron_expr,
            self.tz.key,
        )

        while not self._stop_requested:
            now = datetime.now(self.tz)
            cron = croniter(self.cron_expr, now)
            next_run: datetime = cron.get_next(datetime)

            sleep_seconds = max(0.0, (next_run - now).total_seconds())
            logger.info(
                "Next scheduled run at: %s (in %.1f hours / %.0f seconds)",
                next_run.strftime("%Y-%m-%d %H:%M:%S %Z"),
                sleep_seconds / 3600,
                sleep_seconds,
            )

            # 分段休眠，以便响应终止信号
            while sleep_seconds > 0 and not self._stop_requested:
                chunk = min(sleep_seconds, 1.0)
                time.sleep(chunk)
                sleep_seconds -= chunk

            if self._stop_requested:
                break

            logger.info("Triggering scheduled daily RSS job...")
            try:
                job_func()
            except Exception as e:
                logger.exception("Error occurred during scheduled job execution: %s", e)

        logger.info("Scheduler exited cleanly.")
