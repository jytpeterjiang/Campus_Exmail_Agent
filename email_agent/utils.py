"""无状态的工具函数：解码邮件头、解码 part、文件名提取、大小格式化。"""
from email.header import decode_header


def decode_header_value(header_value):
    """解码 RFC 2047 邮件头，返回纯文本字符串。"""
    if not header_value:
        return "(无)"
    parts = decode_header(header_value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def decode_part(part):
    """解码 MIME part 的 payload 为字符串。"""
    charset = part.get_content_charset() or "utf-8"
    payload = part.get_payload(decode=True)
    if payload is None:
        return "(空内容)"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def decode_attachment_filename(part):
    """从 MIME part 提取并解码附件文件名。"""
    raw = part.get_filename()
    if not raw:
        return None
    return decode_header_value(raw)


def format_size(size_bytes):
    """将字节数格式化为人类可读的大小字符串。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def sanitize_filename(raw_name, max_length=120):
    """移除文件名中的非法字符并截断到 max_length。"""
    import re
    safe = re.sub(r'[<>:"/\\|?*]', '', raw_name).strip()
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe if safe else "无主题"
