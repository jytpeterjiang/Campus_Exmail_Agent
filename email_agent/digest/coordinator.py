"""日报业务编排器：日期展开 → 检查本地邮件 → 生成日报 → 保存。

核心流程（两级生成）：
1. 逐日检查 output/<date>/markdown/ 是否存在邮件归档
2. 缺失时提示用户手动运行 fetch_email.py 拉取
3. 逐日检查 -summary.md → 缺失的先生成单日日报
4. 单日查询 → 直接返回已有/新生成的单日日报
5. 多日查询 → 基于单日日报聚合为汇总报告
"""

from pathlib import Path

from email_agent.ai.date_parser import expand_dates
from email_agent.digest.builder import generate_single_day, aggregate_summaries
from email_agent.local_data import (
    get_summary_path,
    get_aggregate_path,
    classify_dates,
)


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def run(date_spec: dict, output_dir: Path) -> tuple:
    """执行完整的日报生成流程。

    Parameters
    ----------
    date_spec : dict
        {"single": "..."} 或 {"range": {"start":"...","end":"..."}}
    output_dir : Path
        项目 output 根目录。

    Returns
    -------
    (summary_content, summary_path) : tuple[str|None, Path|None]
        前者为 Markdown 字符串（失败为 None），后者为保存路径。
    """
    # ① 展开日期列表
    date_list = expand_dates(date_spec)

    # ② 检查本地邮件归档，缺失时提示用户手动拉取
    available = _check_local_emails(date_list, output_dir)
    if not available:
        print("📭 所选日期范围内没有任何本地邮件归档。")
        print(f"   请先手动拉取: python fetch_email.py --on {' '.join(date_list)} --all --format markdown")
        return None, None

    if len(available) < len(date_list):
        skipped = [d for d in date_list if d not in available]
        print(f"⚠️ 以下日期缺失邮件归档，已跳过: {', '.join(skipped)}")

    print(f"📊 {'每天' if len(available) == 1 else f'{len(available)} 天'}的邮件已就绪。")

    # ③ 逐日确保单日日报存在（缺失才生成）
    daily_summaries = _ensure_daily_summaries(available, output_dir)

    if not daily_summaries:
        return None, None

    # ④ 分支处理
    is_single = "single" in date_spec

    if is_single:
        # 单日：直接返回那一天的日报
        d = available[0]
        content = daily_summaries[d]
        path = get_summary_path(d)
        return content, path
    else:
        # 多日：先检查聚合报告是否已存在
        path = get_aggregate_path(date_spec["range"]["start"], date_spec["range"]["end"])
        if path.exists():
            print(f"  ✅ 汇总报告已存在: {path}")
            return path.read_text(encoding="utf-8"), path

        # 多日：聚合已有单日日报（Python 读文件，AI 汇总）
        print(f"\n📋 正在聚合 {len(available)} 天的日报...")
        summary = aggregate_summaries(
            date_spec["range"]["start"],
            date_spec["range"]["end"],
            available,
            output_dir,
        )
        if not summary:
            return None, None

        _save_aggregate_summary(date_spec, summary, output_dir)
        return summary, path


# ═══════════════════════════════════════════════════════
#  步骤：检查本地邮件归档
# ═══════════════════════════════════════════════════════

def _check_local_emails(
    date_list: list[str], output_dir: Path
) -> list[str]:
    """检查本地邮件归档是否存在，缺失时提示用户手动拉取。

    委托 email_agent.local_data.classify_dates 进行三分法分类：
    - 完整：历史日期 + .fetch_complete 标记存在
    - 不完整：有邮件文件但无 .fetch_complete（如 -n 5 部分拉取）
    - 缺失：无任何邮件文件

    Returns
    -------
    list[str]
        已有 .md 邮件文件的日期列表（完整 + 不完整均可生成日报）。
    """
    complete, partial, missing = classify_dates(date_list)
    available = complete + partial

    if missing:
        print(f"\n⚠️ 以下日期缺少本地邮件归档: {', '.join(missing)}")
        print(f"   请先手动拉取: python fetch_email.py --on {' '.join(missing)} --all --format markdown")
        print()
    if partial:
        print(f"\n💡 以下日期归档不完整（可能为部分拉取）: {', '.join(partial)}")
        print(f"   建议全量拉取: python fetch_email.py --on {' '.join(partial)} --all --format markdown")
        print()

    return available


# ═══════════════════════════════════════════════════════
#  步骤：确保单日日报
# ═══════════════════════════════════════════════════════

def _ensure_daily_summaries(
    date_list: list[str], output_dir: Path
) -> dict[str, str]:
    """逐日检查并在缺失时生成单日日报。

    Returns
    -------
    dict[str, str]
        {日期: 日报 Markdown 内容}
    """
    daily_summaries: dict[str, str] = {}

    for d in date_list:
        summary_path = get_summary_path(d)

        if summary_path.exists():
            print(f"  ✅ {d} 已有日报，跳过")
            content = summary_path.read_text(encoding="utf-8")
            daily_summaries[d] = content
        else:
            print(f"  ⏳ {d} 日报缺失，正在生成...")
            content = generate_single_day(d, output_dir)
            if content:
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(content, encoding="utf-8")
                daily_summaries[d] = content
                print(f"  ✅ {d} 日报已保存")
            else:
                print(f"  ⚠️ {d} 日报生成失败，跳过")

    return daily_summaries

# ═══════════════════════════════════════════════════════
#  保存
# ═══════════════════════════════════════════════════════

def _save_aggregate_summary(
    date_spec: dict, content: str, output_dir: Path
) -> Path:
    """保存多日汇总报告。"""
    start = date_spec["range"]["start"]
    end = date_spec["range"]["end"]
    path = get_aggregate_path(start, end)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
