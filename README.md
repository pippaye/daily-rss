# Daily RSS 每日资讯简报生成器

基于 **Miniflux** RSS 订阅源与 **LLM**（大语言模型）的自动化资讯日报生成程序，通过标准 SMTP 定时推送到你的邮箱。

---

## ✨ 核心特性

- 🛡️ **阅读状态完全隔离**：
  - Miniflux 原生 API 不支持条目级别的自定义 Tag。为了**不破坏你在阅读器中的未读数与收藏夹**，本程序通过本地轻量 SQLite 数据库（`data/processed.db`）独立记录“程序已处理”标记。
- ⏳ **近 3 天智能过滤**：
  - 自动抓取近 3 天（72 小时）内发布的文章，并通过 SQLite 自动排除已处理条目，永不重复推送。
- 🤖 **结构化 LLM 日报**：
  - 自动对 RSS 正文清洗（去除冗余 HTML 标签并安全截断）。
  - 支持所有兼容 OpenAI 规范的 API（OpenAI, Gemini, DeepSeek, Claude, Ollama 等）。
  - 自动输出：**今日速览/核心趋势** + **主题智能分类** + **带原文链接的精炼要点总结**。
- 📧 **精美邮件推送**：
  - 使用优雅的卡片式 HTML 邮件排版，移动端自适应，阅读体验极佳。
  - 同步附带本地 Markdown 归档（保存在 `reports/` 目录下）。
- ⏰ **灵活定时调度**：
  - 基于 Cron 表达式（如 `0 8 * * *`）和时区（如 `Asia/Shanghai`）在后台守护常驻执行。
  - 同时支持 `--now` 立即执行、`--dry-run` 预览调试。

---

## 🚀 快速开始

### 1. 安装环境与依赖

本项目使用 [uv](https://github.com/astral-sh/uv) 进行高效的 Python 依赖管理：

```bash
# 安装依赖
uv sync
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

在 `.env` 中填写你的具体配置：

```env
# Miniflux
MINIFLUX_BASE_URL=https://miniflux.example.com
MINIFLUX_API_KEY=your_token
MINIFLUX_DAYS_LIMIT=3

# LLM (兼容 OpenAI 接口规范)
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
LLM_API_KEY=sk-xxxx

# SMTP 邮件推送
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=your_email@example.com
SMTP_PASSWORD=your_auth_code
SMTP_USE_SSL=true
EMAIL_TO=recipient@example.com

# 定时调度 (每天早晨 8:00)
ON_SCHEDULE="0 8 * * *"
TZ=Asia/Shanghai
```

---

## 🛠️ 命令行用法 (CLI)

程序采用清晰的**子命令（Subcommands）**架构设计：

```bash
# 查看帮助
uv run daily-rss --help

# 1. 抓取与生成简报
uv run daily-rss run                  # 立即执行全流程（抓取 -> 过滤 -> LLM生成 -> 邮件推送 -> 标记已读）
uv run daily-rss run --dry-run        # 演练模式：按分组树状打印待处理条目预览，不调用 LLM、不发邮件、不写数据库

# 2. 查看 Miniflux 分组状态
uv run daily-rss categories           # 查看所有分类的订阅源数与未读条目统计（支持简写: cat, ls）

# 3. 依赖与配置连通性测试
uv run daily-rss test miniflux        # 测试 Miniflux API 连接与登录凭证
uv run daily-rss test email           # 向 EMAIL_TO 发送一封排版测试邮件验证 SMTP 发信

# 4. 常驻定时守护模式
uv run daily-rss daemon               # 按照 ON_SCHEDULE 定时规则（如 0 8 * * *）在后台循环调度
```

---

## 🐳 容器化部署 (Docker & Podman)

生产镜像采用 **多阶段构建（Multi-Stage Build）**：构建阶段通过 `uv` 完成依赖打包，生产运行镜像仅保留 `python:3.12-slim` 与虚拟环境，**容器内零 uv/pip 冗余依赖**，直接运行原生 `daily-rss` 入口。

### 1. 使用 Podman / Podman-Compose (推荐)

```bash
# 构建生产镜像
podman compose build

# 演练模式验证
podman compose run --rm daily-rss daily-rss run --dry-run

# 查看 Miniflux 分组
podman compose run --rm daily-rss daily-rss categories

# 测试 Miniflux 连通性
podman compose run --rm daily-rss daily-rss test miniflux

# 测试邮件发送
podman compose run --rm daily-rss daily-rss test email

# 立即在容器内生成一次日报
podman compose run --rm daily-rss daily-rss run

# 启动常驻定时守护容器（后台运行）
podman compose up -d

# 查看运行日志
podman compose logs -f
```

### 2. 使用 Docker / Docker-Compose

```bash
# 构建并后台启动常驻容器
docker compose up -d --build

# 演练模式
docker compose run --rm daily-rss daily-rss run --dry-run

# 查看日志
docker compose logs -f
```

```
daily-rss/
├── data/                  # 本地 SQLite 数据目录 (processed.db)
├── reports/               # 本地生成的每日 Markdown 归档
├── src/daily_rss/
│   ├── config.py          # 环境变量与配置管理
│   ├── db.py              # SQLite 本地状态维护 (已读标记隔离)
│   ├── html_cleaner.py    # RSS 富文本清洗与结构提取
│   ├── miniflux.py        # Miniflux API 客户端
│   ├── llm.py             # LLM 结构化日报生成
│   ├── mailer.py          # 邮件 HTML 渲染与 SMTP 发送
│   ├── scheduler.py       # Cron 定时调度器
│   └── app.py             # 核心编排与命令行 CLI
├── .env.example           # 配置模板
├── pyproject.toml         # 依赖与打包配置
└── README.md
```
