from __future__ import annotations

import email.utils
import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import List
import markdown

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    line-height: 1.68;
    color: #24292f;
    background-color: #f6f8fa;
    margin: 0;
    padding: 24px 12px;
  }}
  .container {{
    max-width: 760px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 12px;
    padding: 36px 32px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
    border: 1px solid #e1e4e8;
  }}
  h1 {{
    color: #1f2328;
    font-size: 24px;
    border-bottom: 2px solid #eaecef;
    padding-bottom: 12px;
    margin-top: 0;
  }}
  h2 {{
    color: #0969da;
    font-size: 19px;
    margin-top: 28px;
    padding-bottom: 6px;
    border-bottom: 1px solid #eaecef;
  }}
  h3 {{
    color: #24292f;
    font-size: 16px;
    margin-top: 20px;
    margin-bottom: 6px;
  }}
  a {{
    color: #0969da;
    text-decoration: none;
    font-weight: 500;
  }}
  a:hover {{
    text-decoration: underline;
  }}
  p, li {{
    font-size: 15px;
  }}
  blockquote {{
    margin: 16px 0;
    padding: 10px 16px;
    color: #57606a;
    background-color: #f6f8fa;
    border-left: 4px solid #0969da;
    border-radius: 4px;
  }}
  code {{
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 13px;
    background-color: #eff1f3;
    padding: 2px 6px;
    border-radius: 4px;
  }}
  ul, ol {{
    padding-left: 24px;
  }}
  li {{
    margin-bottom: 6px;
  }}
  hr {{
    height: 1px;
    background-color: #eaecef;
    border: none;
    margin: 28px 0;
  }}
  .footer {{
    margin-top: 36px;
    padding-top: 16px;
    border-top: 1px solid #eaecef;
    font-size: 12px;
    color: #8c959f;
    text-align: center;
  }}
</style>
</head>
<body>
  <div class="container">
    {content}
    <div class="footer">
      本邮件由 Daily RSS Bot 自动生成并推送 · Powered by Miniflux & LLM
    </div>
  </div>
</body>
</html>
"""


class Mailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        use_tls: bool = False,
        from_email: str = "",
        from_name: str = "Daily RSS Bot",
        subject_prefix: str = "[每日 RSS 简报]",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.use_tls = use_tls
        self.from_email = from_email or username
        self.from_name = from_name
        self.subject_prefix = subject_prefix

    def markdown_to_html(self, md_text: str) -> str:
        """将 Markdown 转换为带样式的完整 HTML 邮件内容"""
        body_html = markdown.markdown(
            md_text,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
        return HTML_TEMPLATE.format(content=body_html)

    def send_report(
        self,
        recipients: List[str],
        report_markdown: str,
        report_date: str,
    ) -> None:
        """发送日报邮件"""
        if not recipients:
            logger.warning("No recipients specified. Skipping email send.")
            return

        if not self.host or not self.username or not self.password:
            raise ValueError("SMTP configuration is incomplete (host, username, or password missing).")

        subject = f"{self.subject_prefix} {report_date}"
        html_content = self.markdown_to_html(report_markdown)

        # 构造符合 RFC5322 / RFC2047 规范的 multipart/alternative 邮件
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr((self.from_name, self.from_email), charset="utf-8")
        msg["To"] = ", ".join(recipients)
        msg["Date"] = formatdate(localtime=True)
        domain = self.from_email.split("@")[-1] if "@" in self.from_email else "daily-rss"
        msg["Message-ID"] = make_msgid(domain=domain)

        # 挂载纯文本与 HTML 两个版本
        part_text = MIMEText(report_markdown, "plain", "utf-8")
        part_html = MIMEText(html_content, "html", "utf-8")
        msg.attach(part_text)
        msg.attach(part_html)

        logger.info(
            "Connecting to SMTP server %s:%d (SSL=%s, TLS=%s)...",
            self.host,
            self.port,
            self.use_ssl,
            self.use_tls,
        )

        if self.use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=30)
            if self.use_tls:
                server.starttls()

        try:
            server.login(self.username, self.password)
            server.sendmail(self.from_email, recipients, msg.as_string())
            logger.info("Successfully sent daily report email to %s", ", ".join(recipients))
        finally:
            try:
                server.quit()
            except Exception:
                pass
