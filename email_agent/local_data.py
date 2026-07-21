"""本地邮件归档与日报文件的统一路径和数据查询模块。

职责：
- 所有 output/ 目录下的路径公式集中定义（single source of truth）
- 提供归档存在性、完整性、数量的统一查询接口
- 管理 .fetch_complete 标记文件（sentinel 模式）

原则：
- 今天始终视为"未完成"（邮件持续到达），历史日期以标记文件为准
- 无数据库依赖，纯文件系统契约
"""

from datetime import datetime
from pathlib import Path

# ── 项目根目录 ──
_PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "output"


# ═══════════════════════════════════════════════════════
#  路径公式（所有路径拼装的唯一出处）
# ═══════════════════════════════════════════════════════

def get_mail_dir(date_str: str) -> Path:
    """邮件归档目录：output/<date>/markdown/"""
    return OUTPUT_DIR / date_str / "markdown"


def get_summary_path(date_str: str) -> Path:
    """单日日报路径：output/<date>/<date>-summary.md"""
    return OUTPUT_DIR / date_str / f"{date_str}-summary.md"


def get_aggregate_path(start: str, end: str) -> Path:
    """聚合汇总路径：output/<start>_<end>-summary.md"""
    return OUTPUT_DIR / f"{start}_{end}-summary.md"


def _get_fetch_complete_marker(date_str: str) -> Path:
    """.fetch_complete 标记文件路径。"""
    return OUTPUT_DIR / date_str / ".fetch_complete"


# ═══════════════════════════════════════════════════════
#  状态查询
# ═══════════════════════════════════════════════════════

def has_mail_archive(date_str: str) -> bool:
    """该日期是否有本地邮件归档（至少一封 .md 文件）。"""
    md_dir = get_mail_dir(date_str)
    return md_dir.exists() and bool(list(md_dir.glob("*.md")))


def mail_count(date_str: str) -> int:
    """该日期本地归档的邮件数量。"""
    md_dir = get_mail_dir(date_str)
    if not md_dir.exists():
        return 0
    return len(list(md_dir.glob("*.md")))


def has_summary(date_str: str) -> bool:
    """该日期是否已有单日日报。"""
    return get_summary_path(date_str).exists()


def is_fetch_complete(date_str: str) -> bool:
    """该日期是否已全量拉取完成。

    规则：今天始终视为"未完成"（邮件持续到达），
    历史日期以 .fetch_complete 标记文件为准。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if date_str >= today:
        return False
    return _get_fetch_complete_marker(date_str).exists()


# ═══════════════════════════════════════════════════════
#  写入
# ═══════════════════════════════════════════════════════

def mark_fetch_complete(date_str: str) -> None:
    """标记该日期邮件已全量拉取完成（创建 .fetch_complete 文件）。"""
    marker = _get_fetch_complete_marker(date_str)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


# ═══════════════════════════════════════════════════════
#  便利函数
# ═══════════════════════════════════════════════════════

def classify_dates(date_list: list[str]) -> tuple[list[str], list[str], list[str]]:
    """将日期列表分为三类：(完整, 不完整, 缺失)。

    - 完整：历史日期 + 有 .fetch_complete 标记
    - 不完整：有邮件文件但没有 .fetch_complete（如用 -n 5 部分拉取）
    - 缺失：没有任何邮件文件
    """
    complete: list[str] = []
    partial: list[str] = []
    missing: list[str] = []

    for d in date_list:
        if has_mail_archive(d):
            if is_fetch_complete(d):
                complete.append(d)
            else:
                partial.append(d)
        else:
            missing.append(d)

    return complete, partial, missing


def list_available_dates() -> list[str]:
    """列出所有有邮件归档的日期（按日期排序）。"""
    if not OUTPUT_DIR.exists():
        return []
    return sorted([
        d.name for d in OUTPUT_DIR.iterdir()
        if d.is_dir() and has_mail_archive(d.name)
    ])
