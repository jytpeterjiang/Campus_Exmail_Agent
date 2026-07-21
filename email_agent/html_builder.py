"""HTML 归档页面生成。接收邮件头 + 预处理正文 + 附件信息，渲染完整 HTML。"""
import html as _html
import os
from typing import List, Optional
from urllib.parse import quote

from email_agent.utils import format_size


# ── CSS 样式表（提取为常量，便于后续迁移到模板文件） ────────

_PAGE_CSS = """
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{
        background:#e8edf2;
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
        color:#333;padding:12px 16px;line-height:1.6;
    }
    .email-container{
        width:96%;margin:0 auto;background:#fff;border-radius:12px;
        box-shadow:0 2px 16px rgba(0,0,0,0.07);
    }
    .email-header{
        background:linear-gradient(135deg,#f7f9fc 0%,#eef1f5 100%);
        border-bottom:1px solid #dee2e8;padding:28px 32px;
    }
    .email-header h2{
        font-size:20px;font-weight:600;color:#1a1a2e;margin-bottom:18px;
        line-height:1.4;word-break:break-word;
    }
    .email-header table{width:100%;border-collapse:collapse;}
    .email-header td{padding:4px 0;font-size:13px;vertical-align:top;}
    .email-header td.hdr-label{
        color:#6b7280;width:64px;font-weight:500;white-space:nowrap;
    }
    .email-header td.hdr-value{color:#1f2937;word-break:break-all;}
    .email-body{padding:32px;overflow-x:auto;}
    .email-body img{max-width:100%;height:auto;}
    .email-footer{
        border-top:1px solid #eee;padding:14px 32px;font-size:11px;
        color:#aaa;text-align:center;
    }
    .meta-bar{
        display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;
        font-size:11px;color:#999;
    }
    details.collapsible{
        margin:0 32px;
    }
    details.collapsible summary{
        cursor:pointer;color:#555;font-size:14px;padding:8px 0;
        user-select:none;
    }
    details.collapsible summary:hover{color:#333;}
    details.collapsible:last-of-type{margin-bottom:20px;}
    @media(max-width:640px){
        body{padding:8px;}
        .email-header{padding:16px;}
        .email-body{padding:16px;}
        details.collapsible{margin:0 16px;}
        details.collapsible:last-of-type{margin-bottom:12px;}
    }
"""


def _build_attachment_table(attachments: list, att_rel_dir: Optional[str],
                            inline_count: int, att_count: int) -> str:
    """构建附件清单 HTML 表格（attachments 为统一 dict 列表）。"""
    if not attachments:
        return ""

    rows = ""
    for i, att in enumerate(attachments, 1):
        is_inline = att.get("disposition") == "inline"
        tag = "内嵌" if is_inline else "附件"
        tag_bg, tag_color = ("#e3f2fd", "#1565c0") if is_inline else ("#fff3e0", "#e65100")
        size_str = format_size(att.get("size", 0))
        fname_escaped = _html.escape(att.get("filename", ""))

        if att.get("saved_path") and att_rel_dir:
            saved_fname = os.path.basename(att.get("saved_path", ""))
            href = f"../attachments/{quote(att_rel_dir, safe='/')}/{quote(saved_fname, safe='/')}"
            fname_cell = (
                f'<a href="{href}" target="_blank"'
                f' style="color:#1565c0;text-decoration:none;">{fname_escaped}</a>'
            )
        else:
            fname_cell = fname_escaped

        rows += (
            f"<tr>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee;'>{i}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee;'>"
            f"<span style='display:inline-block;padding:1px 6px;border-radius:3px;"
            f"font-size:12px;background:{tag_bg};color:{tag_color};'>{tag}</span></td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee;'>{fname_cell}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee;color:#888;'>{att.get('mime_type', '')}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee;'>{size_str}</td>"
            f"</tr>"
        )

    return f"""
        <details class="collapsible" style="margin-top:16px;">
            <summary>附件清单（{inline_count} 个内嵌，{att_count} 个附件）</summary>
            <table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:13px;">
                <tr style="background:#fafafa;">
                    <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ddd;">#</th>
                    <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ddd;">类型</th>
                    <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ddd;">文件名</th>
                    <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ddd;">MIME</th>
                    <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ddd;">大小</th>
                </tr>
                {rows}
            </table>
        </details>"""


def _build_mime_section(mime_count: int, mime_text: str) -> str:
    """构建 MIME 结构折叠区。"""
    return f"""
    <details class="collapsible" style="margin-top:12px;">
        <summary>MIME 结构（{mime_count} 个 part）</summary>
        <pre style="background:#fafafa;padding:12px;border-radius:4px;font-size:12px;
margin-top:8px;overflow-x:auto;line-height:1.6;">{_html.escape(mime_text)}</pre>
    </details>"""


def build_html(
    subject:      str,
    from_addr:    str,
    date_raw:     str,
    to_addr:      str,
    cc_addr:      str,
    bcc_addr:     str,
    mid:          str,
    body_type:    Optional[str],
    body_content: str,
    attachments:  Optional[list] = None,
    att_rel_dir:  Optional[str] = None,
    mime_count:   int = 0,
    mime_text:    str = "",
) -> str:
    """组装完整的 HTML 归档页面。

    Parameters
    ----------
    subject, from_addr, date_raw, to_addr, cc_addr, bcc_addr : str
        解码后的邮件头字段。
    mid : str
        邮件序号 ID。
    body_type : str or None
        ``"text/html"`` 或 ``"text/plain"``。
    body_content : str
        已预处理的正文内容（HTML 类型下 CID 已替换为文件名，纯文本直接传入）。
    attachments : list[dict] or None
        统一的附件信息列表，每项含 ``filename``、``mime_type``、``size``、
        ``disposition``、``saved_path``。
    att_rel_dir : str or None
        附件保存的相对目录名（用于生成链接）。
    """
    attachments = attachments or []

    # ── 正文处理（HTML 类型已完成 CID→文件路径 替换，不需额外处理）──
    if body_type != "text/html":
        body_content = (
            "<pre style='white-space:pre-wrap;font-family:inherit;"
            "margin:0;'>" + _html.escape(body_content or "(无法提取邮件正文)") + "</pre>"
        )

    # ── 附件统计 ──
    inline_count = sum(1 for a in attachments if a.get("disposition") == "inline")
    att_count    = sum(1 for a in attachments if a.get("disposition") == "attachment")

    # ── 附件清单 ──
    att_html = _build_attachment_table(
        attachments, att_rel_dir, inline_count, att_count
    )

    # ── MIME 结构 ──
    mime_html = _build_mime_section(mime_count, mime_text)

    # ── 邮件头（HTML 转义） ──
    esc = lambda v: _html.escape(v) if v and v != "(无)" else ""

    s_subj, s_from, s_date, s_to = map(_html.escape, (subject, from_addr, date_raw, to_addr))
    s_cc, s_bcc = esc(cc_addr), esc(bcc_addr)

    cc_row  = f"<tr><td class='hdr-label'>Cc</td><td class='hdr-value'>{s_cc}</td></tr>" if s_cc else ""
    bcc_row = f"<tr><td class='hdr-label'>Bcc</td><td class='hdr-value'>{s_bcc}</td></tr>" if s_bcc else ""

    # ── 组装 HTML ──
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{s_subj}</title>
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="email-container">
    <div class="email-header">
        <h2>{s_subj}</h2>
        <table>
            <tr><td class="hdr-label">发件人</td><td class="hdr-value">{s_from}</td></tr>
            <tr><td class="hdr-label">日期</td><td class="hdr-value">{s_date}</td></tr>
            <tr><td class="hdr-label">收件人</td><td class="hdr-value">{s_to}</td></tr>
            {cc_row}{bcc_row}
        </table>
        <div class="meta-bar"><span>邮件 ID: {mid}</span></div>
    </div>
    <div class="email-body">
        {body_content}
    </div>
    {att_html}
    {mime_html}
    <div class="email-footer">本地归档 - Email Agent 生成</div>
</div>
</body>
</html>"""
