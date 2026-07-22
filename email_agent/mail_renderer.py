"""邮件渲染模块 — 将 Markdown 日报转换为美观的 HTML 邮件。

职责：
- 加载 HTML 模板
- 从 Markdown 中提取元数据（标题、副标题、尾注）
- Markdown → HTML 片段转换
- 模板变量填充
- CSS 内联（邮件客户端兼容）

不负责 SMTP 传输 —— 那是 mail_sender 的职责。
"""

import os
from pathlib import Path

try:
    import markdown2
    _HAS_MARKDOWN2 = True
except ImportError:
    _HAS_MARKDOWN2 = False

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "email_base.html")


def render_email_html(md_body: str) -> str:
    """将 Markdown 日报渲染为美观的 HTML 邮件。

    处理流程：
    1. 加载 HTML 模板
    2. 提取 Markdown 元数据（标题、副标题、尾注）
    3. 将正文转换为 HTML 片段
    4. 填充模板变量
    5. CSS 内联以兼容邮件客户端

    Args:
        md_body: AI 生成的日报 Markdown 内容

    Returns:
        完整的 HTML 邮件字符串（可直接作为 MIMEText html 内容）
    """
    # 1. 加载模板
    template = _load_template()

    # 2. 提取元数据
    meta = _extract_metadata(md_body)

    # 3. Markdown → HTML 片段
    content = _md_to_html_fragment(meta["body"])

    # 4. 填充模板
    html = _fill_template(template, meta, content)

    # 5. CSS 内联
    html = _inline_css(html)

    return html


def save_rendered_html(md_body: str, output_path: Path) -> None:
    """将 Markdown 日报渲染为 HTML 并保存到本地文件。

    Args:
        md_body: AI 生成的日报 Markdown 内容
        output_path: HTML 文件的保存路径
    """
    html = render_email_html(md_body)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"📄 HTML 预览已保存到: {output_path}")


# ═══════════════════════════════════════════════════════
#  内部函数
# ═══════════════════════════════════════════════════════

def _load_template() -> str:
    """加载 HTML 邮件模板文件。"""
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _extract_metadata(md_text: str) -> dict:
    """从 Markdown 日报中提取结构化元数据。

    Markdown 格式约定：
        # 邮件日报 · 2026-07-18（周一）   ← 标题
        > 当日邮件摘要                        ← 副标题（可选）
        （空行）
        | 项目 | 数值 |                       ← 正文开始
        ...
        ## 邮件清单
        ...
        ---                                     ← 分隔线
        *本日报由 Email Agent ...*              ← 尾注

    Returns:
        {
            "title": str,       # 标题文字（不含 # 前缀）
            "subtitle": str,    # 副标题文字（不含 > 前缀）
            "footer": str,      # 尾注原始 Markdown
            "body": str,        # 正文 Markdown（不含标题/尾注）
        }
    """
    lines = md_text.strip().split("\n")

    title = ""
    subtitle = ""
    footer = ""
    body_start = 0
    body_end = len(lines)

    # ── 提取标题（第一行，# 开头）──
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body_start = 1

    # ── 提取副标题（紧随标题的 > 引用行）──
    if body_start < len(lines) and lines[body_start].startswith("> "):
        subtitle = lines[body_start][2:].strip()
        body_start += 1

    # ── 跳过标题区和正文之间的空行 ──
    while body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1

    # ── 提取尾注（从末尾最后一个 --- 开始）──
    for i in range(len(lines) - 1, body_start, -1):
        if lines[i].strip() == "---":
            footer = "\n".join(lines[i:]).strip()
            body_end = i
            break

    body = "\n".join(lines[body_start:body_end]).strip()

    return {
        "title": title,
        "subtitle": subtitle,
        "footer": footer,
        "body": body,
    }


def _md_to_html_fragment(md_text: str) -> str:
    """将 Markdown 正文转换为 HTML 片段（不含 <html>/<body> 包裹）。

    使用 markdown2，启用表格、代码块、复选框、精美排版等扩展。
    """
    if not _HAS_MARKDOWN2:
        return f"<pre>{md_text}</pre>"

    return markdown2.markdown(
        md_text,
        extras=[
            "tables",
            "fenced-code-blocks",
            "header-ids",
            "strike",
            "task_list",
            "target-blank-links",
            "smarty-pants",
            "cuddled-lists",
            "break-on-newline",
        ],
    )


def _fill_template(template: str, meta: dict, content: str) -> str:
    """将元数据和 HTML 内容填入模板占位符。

    模板变量：
        {{TITLE}}    — 日报标题
        {{SUBTITLE}} — 副标题（可能为空）
        {{CONTENT}}  — 正文 HTML 片段
        {{FOOTER}}   — 尾注 Markdown（已转 HTML）
    """
    # 尾注也转为 HTML 片段
    footer_html = _md_to_html_fragment(meta.get("footer", ""))

    html = template.replace("{{TITLE}}", meta.get("title", ""))
    html = html.replace("{{SUBTITLE}}", meta.get("subtitle", ""))
    html = html.replace("{{CONTENT}}", content)
    html = html.replace("{{FOOTER}}", footer_html)

    return html


def _inline_css(html: str) -> str:
    """使用 premailer 将 <style> 中的 CSS 内联到 HTML 元素上。

    这是邮件客户端兼容的关键步骤：
    - Gmail / Outlook 会忽略或剥离 <style> 标签
    - 内联 style 属性可保证样式在大多数客户端正常显示

    如果 premailer 未安装，跳过此步骤并打印警告。
    """
    try:
        from premailer import transform
        return transform(
            html,
            remove_classes=False,
            strip_important=False,
        )
    except ImportError:
        print("⚠️ 未安装 premailer，CSS 内联已跳过。安装: pip install premailer")
        return html
