"""日报构建器：组装参数，调用 AI，返回 Markdown 内容。

两个核心函数：
- generate_single_day()：读原始 .md 邮件 → 生成单日日报
- aggregate_summaries()：读已有日报 → 聚合为周报/月报

设计原则：Python 负责读文件，AI 只负责理解 + 生成。
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from email_agent.ai import query, AIError
from email_agent.ai import (
    SYSTEM_PROMPT,
    AGGREGATE_SYSTEM_PROMPT,
    build_single_day_prompt,
    build_aggregate_prompt,
)


# ═══════════════════════════════════════════════════════
#  输出清理
# ═══════════════════════════════════════════════════════

def _clean_output(text: str, footer: str) -> Optional[str]:
    """轻量清理 AI 输出。

    切换 API 后不再有 agent 噪音，只需：
    1. 校验以 # 开头（有效日报/汇总）
    2. 补全 footer（如果 AI 未生成）
    """
    text = text.strip()
    if not text.startswith("#"):
        return None
    # 补全 footer（如果 AI 未生成）
    if "*本日报由 " not in text and "*本报告由 " not in text:
        text = text.rstrip() + "\n\n---\n" + footer
    return text


# ═══════════════════════════════════════════════════════
#  文件读取辅助
# ═══════════════════════════════════════════════════════

def _read_emails(md_dir: Path) -> str:
    """读取目录下所有 .md 邮件文件，拼接为单个字符串。"""
    return "\n\n---\n\n".join(
        fp.read_text(encoding="utf-8")
        for fp in sorted(md_dir.glob("*.md"))
    )


def _read_summaries(date_list: list[str], output_dir: Path) -> str:
    """读取多日的 -summary.md 日报文件，拼接为单个字符串。"""
    parts = []
    for d in sorted(date_list):
        sp = output_dir / d / f"{d}-summary.md"
        if sp.exists():
            parts.append(sp.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


# ═══════════════════════════════════════════════════════
#  单日日报生成
# ═══════════════════════════════════════════════════════

def generate_single_day(date_str: str, output_dir: Path) -> Optional[str]:
    """生成单日日报（读原始 .md 邮件文件）。

    Python 负责读文件并内联到 prompt，AI 只负责理解内容。

    Parameters
    ----------
    date_str : str
        日期字符串 "YYYY-MM-DD"。
    output_dir : Path
        项目 output 根目录。

    Returns
    -------
    str or None
        Markdown 日报内容，失败返回 None。
    """
    md_dir = output_dir / date_str / "markdown"
    if not md_dir.exists():
        print(f"  ⚠️ {date_str} 的 markdown 目录不存在")
        return None

    # Python 负责读文件
    emails = _read_emails(md_dir)
    if not emails.strip():
        return "当日无邮件"

    # 邮件内容直接传入 prompt
    prompt = build_single_day_prompt(date_str, emails)

    try:
        raw = query(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            timeout=120,
        )
        footer = f"*本日报由 Email Agent 基于本地归档生成 · 数据来源：`output/{date_str}/`*"
        return _clean_output(raw, footer)
    except AIError as e:
        print(f"  ❌ {date_str} 日报生成失败: {e}")
        return None


# ═══════════════════════════════════════════════════════
#  多日汇总
# ═══════════════════════════════════════════════════════

def aggregate_summaries(
    start: str, end: str, date_list: list[str], output_dir: Path
) -> Optional[str]:
    """聚合多日日报为一个综合汇总报告。

    Python 读取所有单日日报并内联到 prompt，AI 只负责汇总。

    Parameters
    ----------
    start : str
        起始日期 "YYYY-MM-DD"。
    end : str
        结束日期 "YYYY-MM-DD"。
    date_list : list[str]
        需要汇总的日期列表。
    output_dir : Path
        项目 output 根目录。

    Returns
    -------
    str or None
        汇总报告 Markdown 内容。
    """
    if not date_list:
        return None

    # Python 负责读取所有日报文件
    daily_summaries = _read_summaries(date_list, output_dir)
    prompt = build_aggregate_prompt(start, end, date_list, daily_summaries)

    try:
        raw = query(
            system_prompt=AGGREGATE_SYSTEM_PROMPT,
            user_prompt=prompt,
            timeout=120,
        )
        footer = f"*本报告由 Email Agent 基于每日日报汇总生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        return _clean_output(raw, footer)
    except AIError as e:
        print(f"❌ 汇总生成失败: {e}")
        return None
