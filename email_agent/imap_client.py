"""IMAP 客户端：连接、认证、获取邮件（支持日期范围过滤）。"""
import imaplib
import email

from email_agent.config import IMAP_SERVER, IMAP_PORT, EMAIL, PASSWORD


class IMAPError(Exception):
    """IMAP 操作异常。"""
    pass


def _check(resp, msg):
    if resp != "OK":
        raise IMAPError(f"{msg}: {resp}")


# IMAP 协议要求的月份英文缩写（与 locale 无关）
_MONTH_ABBRS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _to_imap_date(iso_date: str) -> str:
    """将 ISO 格式日期转换为 IMAP 要求的 DD-Mon-YYYY。

    Parameters
    ----------
    iso_date : str
        ``"YYYY-MM-DD"`` 格式，如 ``"2026-07-18"``。

    Returns
    -------
    str
        ``"DD-Mon-YYYY"`` 格式，如 ``"18-Jul-2026"``。
    """
    y, m, d = iso_date.split("-")
    return f"{d}-{_MONTH_ABBRS[int(m)]}-{y}"


def fetch_emails(n=None, since=None, before=None, on_count=None):
    """生成器：连接 IMAP 服务器，逐封 yield 邮件（支持数量限制与日期范围过滤）。

    日期过滤在 IMAP 服务器端完成，仅返回匹配的邮件 ID。
    每下载一封立即 yield，实现"边下载边处理"的流式管道。

    Parameters
    ----------
    n : int or None
        最多返回 n 封（最新的）。``None`` 表示不限制数量。
    since : str or None
        起始日期（含），``"YYYY-MM-DD"`` 格式。如 ``"2026-07-01"``。
    before : str or None
        截止日期（不含），``"YYYY-MM-DD"`` 格式。如 ``"2026-07-18"``。
    on_count : callable or None
        可选回调，在 search 完成后、fetch 正文前调用。
        签名为 ``on_count(total: int) -> bool``，返回 ``True`` 继续、``False`` 取消。
        回调执行时 IMAP 连接仍处于打开状态，用于复用连接的二次确认。

    Yields
    ------
    tuple[str, email.message.Message, int, int]
        (邮件序号 ID, 邮件消息对象, 当前索引, 总数)
    """
    # ── 构建 IMAP 搜索条件 ──
    criteria = []
    if since is not None:
        criteria.append(f'SINCE "{_to_imap_date(since)}"')
    if before is not None:
        criteria.append(f'BEFORE "{_to_imap_date(before)}"')

    if not criteria:
        criteria.append("ALL")

    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    try:
        conn.login(EMAIL, PASSWORD)

        resp, data = conn.select("INBOX")
        _check(resp, "选择邮箱失败")

        total = int(data[0])
        if total == 0:
            raise IMAPError("收件箱为空")

        resp, msg_ids = conn.search(None, *criteria)
        _check(resp, "搜索邮件失败")

        all_ids = msg_ids[0].split()
        if not all_ids:
            raise IMAPError("未找到匹配的邮件")

        # 如果指定了数量，取最后 n 条（最新）
        if n is not None and n < len(all_ids):
            target_ids = all_ids[-n:]
        else:
            target_ids = all_ids

        total_count = len(target_ids)

        # ── 确认回调（复用当前 IMAP 连接，避免二次登录）──
        if on_count is not None:
            if not on_count(total_count):
                return

        for i, mid in enumerate(target_ids, start=1):
            resp, msg_data = conn.fetch(mid, "(RFC822)")
            _check(resp, f"获取邮件 {mid} 失败")
            raw_bytes = msg_data[0][1]
            msg = email.message_from_bytes(raw_bytes)
            yield (mid.decode(), msg, i, total_count)
    finally:
        try:
            conn.logout()
        except Exception:
            pass



