"""日期展开工具：将 date_spec 展开为具体日期列表。"""

from datetime import datetime, timedelta


def date_to_since_before(date_str: str) -> tuple[str, str]:
    """单日期字符串 -> IMAP 查询所需的 (since, before)。

    before = date + 1 天，因为 IMAP SEARCH BEFORE 不含当天。
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return date_str, (d + timedelta(days=1)).strftime("%Y-%m-%d")


def expand_dates(date_spec: dict) -> list[str]:
    """将日期规格展开为具体日期列表。

    Parameters
    ----------
    date_spec : dict
        {"single": "2026-07-17"} 或 {"range": {"start":"...","end":"..."}}

    Returns
    -------
    list[str]
        日期字符串列表，如 ["2026-07-17"] 或 ["2026-07-13", ..., "2026-07-18"]
    """
    if "single" in date_spec:
        return [date_spec["single"]]

    start = datetime.strptime(date_spec["range"]["start"], "%Y-%m-%d")
    end = datetime.strptime(date_spec["range"]["end"], "%Y-%m-%d")

    if end < start:
        start, end = end, start

    return [
        (start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((end - start).days + 1)
    ]
