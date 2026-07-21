"""
MIME 解析模块。
一次遍历完成正文提取、附件/内嵌资源收集、CID→base64 映射构建。
"""
import base64
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from email_agent.utils import decode_part, decode_attachment_filename


# ── 类型定义 ────────────────────────────────────────────────

@dataclass
class AttachmentInfo:
    """单个附件/内嵌资源的描述信息。"""
    filename:    str
    mime_type:   str
    size:        int
    disposition: str          # "inline" / "attachment" / "other" / None
    content_id:  Optional[str]
    data:        Optional[bytes]
    saved_path:  Optional[str] = None   # 下载到本地后的路径


@dataclass
class ParseResult:
    """一次 MIME 解析的完整结果。"""
    body_type:   Optional[str]         # "text/html" | "text/plain" | None
    body_html:   str                   # 正文内容（HTML 或纯文本）
    attachments: list = field(default_factory=list)   # list[AttachmentInfo]
    mime_count:  int = 0
    mime_text:   str = ""              # 人类可读的 MIME 结构摘要
    cid_map:     dict = field(default_factory=dict)    # {cid: (mime_type, base64_data)}


# ── 内部辅助 ────────────────────────────────────────────────

def _get_disposition(part):
    """判断 MIME part 的 disposition：inline / attachment / other / None。"""
    cd = part.get("Content-Disposition", "")
    if cd:
        cd_lower = cd.lower()
        if cd_lower.startswith("inline"):
            return "inline"
        if cd_lower.startswith("attachment"):
            return "attachment"
        return "other"
    if part.get("Content-ID"):
        return "inline"
    return None


_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"})


def _guess_image_ct(ct: str, filename: str) -> bool:
    """当 MIME 类型不是 image/* 时，通过文件名后缀判断是否实际为图片。"""
    if not filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _IMAGE_EXTENSIONS


# ── 核心解析 ────────────────────────────────────────────────

def parse_email(msg) -> ParseResult:
    """一次遍历 MIME 树，返回结构化的 ParseResult。

    CID 优化：每个 part 只解析一次 CID 和 payload，避免重复计算。
    """
    plain = html = None
    attachments = []
    cid_map = {}
    mime_lines = []

    for idx, part in enumerate(msg.walk()):
        ct = part.get_content_type()
        cd = _get_disposition(part)
        filename = decode_attachment_filename(part)

        # ── 一次性获取 CID 和 payload（避免后续重复调用） ──
        cid_header = part.get("Content-ID", "") or ""
        cid_raw = cid_header.strip(" <>") or None
        payload = part.get_payload(decode=True)

        # ── MIME 摘要行 ──
        tag = {"attachment": "[附件]", "inline": "[内嵌]"}.get(cd, "")
        line = f"  [{idx}] {tag} {ct}"
        if filename:
            line += f"  ({filename})"
        elif cid_raw:
            line += f"  (cid:{cid_raw})"
        mime_lines.append(line)

        # ── 正文（跳过附件和内嵌资源）──
        if cd not in ("attachment", "inline"):
            if ct == "text/html" and html is None:
                html = decode_part(part)
            elif ct == "text/plain" and plain is None:
                plain = decode_part(part)

        # ── 附件 & 内嵌资源 ──
        if cd is not None:
            attachments.append(AttachmentInfo(
                filename    = filename or f"unnamed_{len(attachments)}",
                mime_type   = ct,
                size        = len(payload) if payload else 0,
                disposition = cd,
                content_id  = cid_raw,
                data        = payload,
            ))

        # ── CID → base64 映射 ──
        if cid_raw and payload:
            if ct.startswith("image/"):
                cid_map[cid_raw] = (ct, base64.b64encode(payload).decode("ascii"))
            elif _guess_image_ct(ct, filename):
                # 部分邮件客户端将图片错误标记为 application/octet-stream。
                # 通过文件名后缀回退检测，修正 data URI 中的 MIME 类型。
                ext = filename.rsplit(".", 1)[-1].lower()
                guessed_ct = f"image/{ext}"
                cid_map[cid_raw] = (guessed_ct, base64.b64encode(payload).decode("ascii"))

    return ParseResult(
        body_type   = "text/html" if html else "text/plain" if plain else None,
        body_html   = html or plain or "(无法提取邮件正文)",
        attachments = attachments,
        mime_count  = len(mime_lines),
        mime_text   = "\n".join(mime_lines),
        cid_map     = cid_map,
    )


def embed_cid_images(html_content: str, cid_map: dict) -> str:
    """将 HTML 中的 cid: 图片引用替换为 data: URI（base64 内嵌）。"""
    if not cid_map:
        return html_content

    def _replace(match):
        quote = match.group(1)
        cid = match.group(2)
        if cid in cid_map:
            mime_type, b64 = cid_map[cid]
            return f'src={quote}data:{mime_type};base64,{b64}{quote}'
        return match.group(0)

    return re.sub(
        r'src=(["\'])cid:([^"\'#?\s]+)\1',
        _replace,
        html_content,
    )


def embed_cid_images_as_files(html_content: str, cid_map: dict,
                              save_dir: str, url_prefix: str = "") -> Tuple[str, List[dict]]:
    """将 HTML 中的 cid: 图片保存为磁盘文件，替换引用为文件名（相对路径）。

    与 ``embed_cid_images`` 不同，本函数不将图片 base64 内嵌，而是把图片
    写入 *save_dir* 目录，并在 HTML 中仅保留文件名引用。调用方通过相对路径
    拼接即可让 HTML / Markdown 正确加载图片，大幅减小输出体积。

    Parameters
    ----------
    html_content : str
        原始 HTML 正文（可能包含 ``cid:xxx`` 引用）。
    cid_map : dict
        由 ``parse_email()`` 返回的 ``ParseResult.cid_map``。
    save_dir : str
        图片保存目标目录。

    Returns
    -------
    (modified_html, inline_files) : tuple[str, list[dict]]
        - *modified_html*: cid: 已替换为文件名的 HTML。
        - *inline_files*: 已落盘的文件信息列表，每项含 ``filename``、
          ``mime_type``、``size``、``saved_path``、``disposition``。
    """
    if not cid_map:
        return html_content, []

    os.makedirs(save_dir, exist_ok=True)

    cid_to_fname: dict = {}
    saved_files: list = []

    for idx, (cid, (mime_type, b64_data)) in enumerate(cid_map.items(), 1):
        ext = mime_type.split("/")[-1] if "/" in mime_type else "png"
        if ext == "jpeg":
            ext = "jpg"
        fname = f"inline_{idx:04d}.{ext}"
        fpath = os.path.join(save_dir, fname)

        raw_bytes = base64.b64decode(b64_data)
        with open(fpath, "wb") as f:
            f.write(raw_bytes)

        cid_to_fname[cid] = fname
        saved_files.append({
            "filename":    fname,
            "mime_type":   mime_type,
            "size":        len(raw_bytes),
            "disposition": "inline",
            "saved_path":  fpath,
        })

    def _replace(match):
        quote = match.group(1)
        cid = match.group(2)
        if cid in cid_to_fname:
            return f'src={quote}{url_prefix}{cid_to_fname[cid]}{quote}'
        return match.group(0)

    modified = re.sub(
        r'src=(["\'])cid:([^"\'#?\s]+)\1',
        _replace,
        html_content,
    )

    return modified, saved_files
