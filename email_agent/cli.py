"""
CLI 编排入口。
连接 IMAP → 获取最新 N 封邮件 → 解析 → 保存附件 → 生成 HTML/Markdown 归档。
"""
import email.utils
import os
import sys

from email_agent.config import SAVE_ATTACHMENTS, OUTPUT_DIR_NAME, EMAIL as SELF_EMAIL
from email_agent.imap_client import fetch_emails, IMAPError
from email_agent.parser import parse_email, ParseResult, embed_cid_images_as_files
from email_agent.html_builder import build_html
from email_agent.md_builder import build_md, html_to_markdown
from email_agent.local_data import mark_fetch_complete
from email_agent.utils import decode_header_value, sanitize_filename


def _get_output_dir() -> str:
    """获取 output 目录的绝对路径。"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)) or ".", OUTPUT_DIR_NAME)


def _save_attachments(result: ParseResult, save_dir: str) -> None:
    """只将 disposition=attachment 的附件写入磁盘。
    内嵌图片（disposition=inline）由 embed_cid_images_as_files 处理。
    """
    real_att = [a for a in result.attachments if a.disposition == "attachment"]
    if not real_att:
        return
    os.makedirs(save_dir, exist_ok=True)
    for att in real_att:
        if att.data is None:
            continue
        filepath = os.path.join(save_dir, att.filename)
        with open(filepath, "wb") as f:
            f.write(att.data)
        att.saved_path = filepath


def _build_email_dirs(output_dir: str, date_dir: str, safe_name: str, ts_str: str):
    """构建邮件归档所需的目录路径。返回 (html_dir, md_dir, att_save_dir, att_rel_dir)。"""
    att_rel_dir = f"{safe_name}_{ts_str}"
    html_dir = os.path.join(output_dir, date_dir, "html")
    md_dir   = os.path.join(output_dir, date_dir, "markdown")
    att_save_dir = os.path.join(output_dir, date_dir, "attachments", att_rel_dir)
    return html_dir, md_dir, att_save_dir, att_rel_dir


def _merge_attachments(result, inline_files: list) -> list:
    """合并真实附件和内嵌文件为统一的 dict 列表。"""
    att_dicts = [
        {
            "filename":    a.filename,
            "mime_type":   a.mime_type,
            "size":        a.size,
            "disposition": a.disposition,
            "saved_path":  a.saved_path,
        }
        for a in result.attachments
        if a.disposition == "attachment"
    ]
    return att_dicts + inline_files


def _process_email(mid: str, msg, output_dir: str, fmt: str = "both") -> str | None:
    """处理单封邮件：解析 → 落盘 CID 图片 → 保存附件 → 生成 HTML/Markdown。

    Returns
    -------
    str or None
        邮件所属日期目录（如 "2026-07-18"），跳过时返回 None。
    """
    subject   = decode_header_value(msg.get("Subject"))
    from_addr = decode_header_value(msg.get("From"))
    to_addr   = decode_header_value(msg.get("To"))
    cc_addr   = decode_header_value(msg.get("Cc"))
    bcc_addr  = decode_header_value(msg.get("Bcc"))
    date_raw  = msg.get("Date", "(无)")

    # ═══ 跳过自己发送的邮件（如日报回发，避免反馈循环） ═══
    from_addr_pure = email.utils.parseaddr(from_addr)[1].lower()
    self_email = SELF_EMAIL.lower()
    if from_addr_pure == self_email:
        print(f"[跳过] 来自自己的邮件: {subject}", file=sys.stderr)
        return None
    # ═══════════════════════════════════════════════════════

    result = parse_email(msg)

    try:
        email_dt = email.utils.parsedate_to_datetime(date_raw)
        ts_str = email_dt.strftime("%Y_%m_%d_%H_%M_%S")
        date_dir = email_dt.strftime("%Y-%m-%d")
    except Exception:
        ts_str = "unknown_date"
        date_dir = "unknown_date"

    safe_name = sanitize_filename(subject if subject != "(无)" else "无主题")
    html_dir, md_dir, att_save_dir, att_rel_dir = _build_email_dirs(
        output_dir, date_dir, safe_name, ts_str
    )

    # ── CID 图片落盘 + 替换 HTML 中的 cid: 引用 ──
    body_html_with_paths, inline_files = embed_cid_images_as_files(
        result.body_html, result.cid_map, att_save_dir,
        url_prefix=f"../attachments/{att_rel_dir}/"
    )

    # ── 保存真实附件（disposition=attachment）──
    if SAVE_ATTACHMENTS:
        _save_attachments(result, att_save_dir)

    # ── 合并附件列表（统一 dict 格式）──
    all_files = _merge_attachments(result, inline_files)

    # 正文内容（用于 HTML / Markdown 构建）
    body_final = body_html_with_paths if result.body_type == "text/html" else result.body_html

    # ── 生成 HTML ──
    if fmt in ("html", "both"):
        os.makedirs(html_dir, exist_ok=True)
        html_content = build_html(
            subject      = subject,
            from_addr    = from_addr,
            date_raw     = date_raw,
            to_addr      = to_addr,
            cc_addr      = cc_addr,
            bcc_addr     = bcc_addr,
            mid          = mid,
            body_type    = result.body_type,
            body_content = body_final,
            attachments  = all_files,
            att_rel_dir  = att_rel_dir,
            mime_count   = result.mime_count,
            mime_text    = result.mime_text,
        )
        html_path = os.path.join(html_dir, f"{safe_name}_{ts_str}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[HTML] 已保存: {html_path}", file=sys.stderr)

    # ── 生成 Markdown ──
    if fmt in ("markdown", "both"):
        os.makedirs(md_dir, exist_ok=True)
        if result.body_type == "text/html":
            md_body = html_to_markdown(body_html_with_paths)
        else:
            # 纯文本邮件，直接作为 Markdown 引用块
            md_body = result.body_html

        md_content = build_md(
            subject      = subject,
            from_addr    = from_addr,
            date_raw     = date_raw,
            to_addr      = to_addr,
            cc_addr      = cc_addr,
            bcc_addr     = bcc_addr,
            mid          = mid,
            md_body      = md_body,
            attachments  = all_files,
            att_rel_dir  = att_rel_dir,
            mime_count   = result.mime_count,
            mime_text    = result.mime_text,
        )
        md_path = os.path.join(md_dir, f"{safe_name}_{ts_str}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[MD]  已保存: {md_path}", file=sys.stderr)

    # ── 统计输出 ──
    inline_count = sum(1 for a in all_files if a.get("disposition") == "inline")
    att_count    = sum(1 for a in all_files if a.get("disposition") == "attachment")
    saved_att    = [a for a in result.attachments
                    if a.disposition == "attachment" and a.saved_path]

    print(f"  {inline_count} 个内嵌资源, {att_count} 个附件, "
          f"{len(result.cid_map)} 个 CID 已落盘", file=sys.stderr)
    if saved_att:
        print(f"  附件已保存到: {att_save_dir}  ({len(saved_att)} 个文件)", file=sys.stderr)
    print(file=sys.stderr)

    return date_dir


def _progress_bar(current: int, total: int, width: int = 30) -> str:
    """生成进度条字符串。

    Parameters
    ----------
    current : int
        当前进度（1-based）。
    total : int
        总数。
    width : int
        进度条宽度（字符数）。

    Returns
    -------
    str
        如 ``"[████████████░░░░░░░░░░░░░░] 12/50 (24.0%)"``
    """
    pct = current / total
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {current}/{total} ({pct * 100:.1f}%)"


def main(n=None, fmt: str = "both", since: str = None, before: str = None, on_count=None) -> None:
    """主流程：获取邮件 → 逐封归档（边下载边处理）。

    Parameters
    ----------
    n : int or None
        最多获取 n 封最新的。``None`` 不限制。
    fmt : str
        输出格式 — ``"html"`` / ``"markdown"`` / ``"both"``。
    since : str or None
        起始日期（含），``"YYYY-MM-DD"`` 格式。
    before : str or None
        截止日期（不含），``"YYYY-MM-DD"`` 格式。
    on_count : callable or None
        透传给 ``fetch_emails`` 的确认回调。
    """
    try:
        emails_gen = fetch_emails(n=n, since=since, before=before, on_count=on_count)
    except IMAPError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return

    output_dir = _get_output_dir()
    os.makedirs(output_dir, exist_ok=True)

    print(f"输出格式: {fmt}", file=sys.stderr)
    print(file=sys.stderr)

    idx = 0
    total = 0
    fetched_dates: set[str] = set()
    try:
        for mid, msg, current, total in emails_gen:
            idx = current
            if total > 1:
                print(f"\r{_progress_bar(current, total)}\n", end="", file=sys.stderr, flush=True)
            date_dir = _process_email(mid, msg, output_dir, fmt=fmt)
            if date_dir:
                fetched_dates.add(date_dir)
        if total > 1:
            print("全部完成!", file=sys.stderr)
    except KeyboardInterrupt:
        print(f"\n\n[中断] 用户取消操作，已处理 {idx}/{total} 封邮件。", file=sys.stderr)
        return

    # ── 全量拉取（n is None）完成后标记对应日期为完整归档 ──
    if n is None and fetched_dates:
        for d in fetched_dates:
            mark_fetch_complete(d)
        print(f"✅ 已标记 {len(fetched_dates)} 个日期为完整归档。", file=sys.stderr)



