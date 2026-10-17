import os
import tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from croniter import croniter

from daily_rss.db import Database
from daily_rss.html_cleaner import clean_html
from daily_rss.mailer import Mailer
from daily_rss.config import Config


def test_html_cleaner():
    html = """
    <div>
        <h1>Hello World</h1>
        <p>This is a <a href="https://example.com">link</a> and a &amp; test.</p>
        <script>alert('bad');</script>
        <style>body { color: red; }</style>
        <br/>
        <ul>
            <li>Point 1</li>
            <li>Point 2</li>
        </ul>
    </div>
    """
    cleaned = clean_html(html)
    assert "Hello World" in cleaned
    assert "Point 1" in cleaned
    assert "alert" not in cleaned
    assert "body { color: red; }" not in cleaned
    assert "&amp;" not in cleaned
    assert "&" in cleaned
    print("✓ test_html_cleaner passed")


def test_database_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)

        entries = [
            {"id": 101, "title": "Article 1", "url": "https://a.com", "published_at": "2025-05-18T10:00:00Z", "feed": {"title": "Feed 1"}},
            {"id": 102, "title": "Article 2", "url": "https://b.com", "published_at": "2025-05-18T11:00:00Z", "feed": {"title": "Feed 2"}},
        ]

        # 初始未读条目应为 2
        unprocessed = db.filter_unprocessed(entries)
        assert len(unprocessed) == 2

        # 标记 101 已读
        db.mark_as_processed([entries[0]], "2025-05-18")

        # 再次过滤，应只剩 102
        unprocessed = db.filter_unprocessed(entries)
        assert len(unprocessed) == 1
        assert unprocessed[0]["id"] == 102

        # 重复插入不报错
        db.mark_as_processed([entries[0]], "2025-05-18")
        assert db.get_total_processed_count() == 1

        print("✓ test_database_filtering passed")


def test_mailer_html_render():
    mailer = Mailer(
        host="smtp.test.com",
        port=465,
        username="bot@test.com",
        password="secret",
    )
    md = """# Title
## Section
- Item 1
- Item 2

[Link](https://example.com)
"""
    html = mailer.markdown_to_html(md)
    assert "<h1>Title</h1>" in html
    assert "<h2>Section</h2>" in html
    assert '<a href="https://example.com">Link</a>' in html
    assert "Daily RSS Bot" in html
    print("✓ test_mailer_html_render passed")


def test_cron_parsing():
    cron_expr = "0 8 * * *"
    tz = ZoneInfo("Asia/Shanghai")
    base_time = datetime(2025, 5, 18, 7, 0, tzinfo=tz)
    cron = croniter(cron_expr, base_time)
    next_time = cron.get_next(datetime)
    assert next_time.hour == 8
    assert next_time.minute == 0
    assert next_time.day == 18
    print("✓ test_cron_parsing passed")


if __name__ == "__main__":
    test_html_cleaner()
    test_database_filtering()
    test_mailer_html_render()
    test_cron_parsing()
    print("All tests passed successfully!")
