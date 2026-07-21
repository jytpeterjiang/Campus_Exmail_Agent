"""日期展开工具：将 date_spec 展开为具体日期列表。"""

from datetime import datetime, timedelta


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
