"""Markdown 归档文件生成。调用 html2markdown CLI 将 HTML 转为 Markdown。"""
import os
import subprocess
import sys
from typing import List, Optional
from urllib.parse import quote

from email_agent.utils import format_size

_HTML2MD_EXE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "html-to-markdown", "html2markdown.exe"
)


def html_to_markdown(html_content: str) -> str:
    """调用 html2markdown CLI 将 HTML 转为 Markdown。

    要求 ``html-to-markdown/html2markdown.exe`` 存在（仅支持 Windows）。
    """
    if sys.platform != "win32":
        raise RuntimeError(
            "html2markdown.exe 仅支持 Windows 平台。"
            "在 Linux/macOS 上请使用 html2text 库作为替代。"
        )
    result = subprocess.run(
        [_HTML2MD_EXE, "--plugin-table", "--plugin-strikethrough"],
        input=html_content,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"html2markdown 转换失败: {result.stderr}")
    return result.stdout.strip()


def build_md(
    subject:      str,
    from_addr:    str,
    date_raw:     str,
    to_addr:      str,
    cc_addr:      str,
    bcc_addr:     str,
    mid:          str,
    md_body:      str,
    attachments:  Optional[list] = None,
    att_rel_dir:  Optional[str] = None,
    mime_count:   int = 0,
    mime_text:    str = "",
) -> str:
    """组装 Markdown 归档文件。

    Parameters 与 ``build_html`` 一致，仅输出格式不同。
    """
    attachments = attachments or []

    # ── 附件统计 ──
    inline_count = sum(1 for a in attachments if a.get("disposition") == "inline")
    att_count    = sum(1 for a in attachments if a.get("disposition") == "attachment")

    # ── 组装 ──
    lines: List[str] = []

    # YAML front matter
    lines.append("---")
    lines.append(f'subject: "{_md_escape(subject)}"')
    lines.append(f'from: "{_md_escape(from_addr)}"')
    lines.append(f'date: "{_md_escape(date_raw)}"')
    lines.append(f'to: "{_md_escape(to_addr)}"')
    if cc_addr and cc_addr != "(无)":
        lines.append(f'cc: "{_md_escape(cc_addr)}"')
    if bcc_addr and bcc_addr != "(无)":
        lines.append(f'bcc: "{_md_escape(bcc_addr)}"')
    lines.append(f'mid: "{mid}"')
    lines.append("---")
    lines.append("")

    # 邮件头
    lines.append(f"# {_md_escape(subject)}")
    lines.append("")
    lines.append(f"**发件人:** {_md_escape(from_addr)}  ")
    lines.append(f"**日期:** {_md_escape(date_raw)}  ")
    lines.append(f"**收件人:** {_md_escape(to_addr)}  ")
    if cc_addr and cc_addr != "(无)":
        lines.append(f"**抄送:** {_md_escape(cc_addr)}  ")
    if bcc_addr and bcc_addr != "(无)":
        lines.append(f"**密送:** {_md_escape(bcc_addr)}  ")
    lines.append(f"**邮件 ID:** {mid}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 正文（已转为 Markdown）
    lines.append(md_body)
    lines.append("")

    # 附件清单
    att_table = _build_md_attachment_table(
        attachments, att_rel_dir, inline_count, att_count
    )
    if att_table:
        lines.append(att_table)

    # MIME 结构
    if mime_text:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(
            f"<details>\n"
            f"<summary>MIME 结构（{mime_count} 个 part）</summary>\n\n"
            f"```\n{mime_text}\n```\n\n"
            f"</details>"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本地归档 - Email Agent 生成*")
    lines.append("")

    return "\n".join(lines)


def _md_escape(value: str) -> str:
    """转义 Markdown 表格分隔符，防止误解析。"""
    return value.replace("|", "\\|") if value else ""


def _build_md_attachment_table(attachments: list, att_rel_dir: Optional[str],
                               inline_count: int, att_count: int) -> str:
    """构建 Markdown 附件清单表格。"""
    if not attachments:
        return ""

    lines = []
    lines.append(f"## 附件清单（{inline_count} 个内嵌，{att_count} 个附件）")
    lines.append("")
    lines.append("| # | 类型 | 文件名 | MIME | 大小 |")
    lines.append("|---|------|--------|------|------|")

    for i, att in enumerate(attachments, 1):
        is_inline = att.get("disposition") == "inline"
        tag = "内嵌" if is_inline else "附件"
        fname = att.get("filename", "")
        mime = att.get("mime_type", "")
        size_str = format_size(att.get("size", 0))

        if att.get("saved_path") and att_rel_dir:
            saved_fname = os.path.basename(att["saved_path"])
            href = f"../attachments/{quote(att_rel_dir, safe='/')}/{quote(saved_fname, safe='/')}"
            fname_cell = f"[{_md_escape(fname)}]({href})"
        else:
            fname_cell = _md_escape(fname)

        lines.append(f"| {i} | {tag} | {fname_cell} | {mime} | {size_str} |")

    lines.append("")
    return "\n".join(lines)
