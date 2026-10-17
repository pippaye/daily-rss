from __future__ import annotations

import html
import re


def clean_html(raw_html: str) -> str:
    """
    将 HTML 文本清洗为纯净的可读文本，用于喂给 LLM。
    - 去除 script, style 等不可见标签
    - 换行保留结构（p, br, h1-h6, li, tr 等）
    - 移除其余标签
    - 解码 HTML 实体
    - 合并过多空白换行
    """
    if not raw_html:
        return ""

    # 去除 script 和 style
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 块级标签转为换行
    text = re.sub(r"<(?:br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)

    # 去除所有其他 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)

    # 解码 HTML 字符实体 (&nbsp;, &lt;, &gt;, &#39; 等)
    text = html.unescape(text)

    # 去除连续空格和制表符
    text = re.sub(r"[ \t]+", " ", text)

    # 合并过多换行
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()
