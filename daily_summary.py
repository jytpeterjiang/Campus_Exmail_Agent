#!/usr/bin/env python
"""AI 邮件日报助手 — 参数化日期输入，基于本地邮件归档生成 AI 日报。

请先用 fetch_email.py 拉取邮件到本地，再运行本脚本生成日报:
    python fetch_email.py --on 2026-07-18 --all --format markdown  # 拉取邮件
    python daily_summary.py --date 2026-07-18                      # 生成日报

用法:
    python daily_summary.py --today              # 今天
    python daily_summary.py --yesterday          # 昨天
    python daily_summary.py --date 2026-07-15    # 指定日期
    python daily_summary.py --this-week          # 本周一到今天
    python daily_summary.py --last-week          # 上周一到上周日
    python daily_summary.py --this-month         # 本月1日到今天
    python daily_summary.py --last 7             # 最近7天
    python daily_summary.py --range 2026-07-01 2026-07-18  # 指定范围
"""

import argparse
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from email_agent.ai.cli_client import check_available
from email_agent.ai.date_parser import expand_dates, date_to_since_before
from email_agent.cli import main as fetch_emails_main
from email_agent.digest.coordinator import run as run_digest
from email_agent.local_data import (
    get_mail_dir,
    get_summary_path,
    get_aggregate_path,
    mail_count,
    is_fetch_complete,
    mark_fetch_complete,
)
from email_agent.mail_sender import send_markdown_mail

PROJECT_ROOT = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_ROOT / "output"


# ═══════════════════════════════════════════════════════
#  参数校验
# ═══════════════════════════════════════════════════════

def _validate_date(date_str: str) -> str:
    """校验并标准化日期格式为 YYYY-MM-DD。"""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", date_str)
    if not m:
        raise argparse.ArgumentTypeError(
            f"日期格式无效: {date_str}，应为 YYYY-MM-DD"
        )
    try:
        datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise argparse.ArgumentTypeError(f"日期不存在: {date_str}")
    return date_str


def _validate_positive_int(value: str) -> int:
    """校验正整数参数。"""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"无效数字: {value}")
    if n < 1:
        raise argparse.ArgumentTypeError(f"必须为正整数，得到: {n}")
    return n


# ═══════════════════════════════════════════════════════
#  date_spec 构建
# ═══════════════════════════════════════════════════════

def _build_single(date_str: str) -> dict:
    return {"single": date_str}


def _build_range(start: str, end: str) -> dict:
    return {"range": {"start": start, "end": end}}


def _make_subject(date_spec: dict) -> str:
    """根据 date_spec 生成邮件主题。"""
    if "single" in date_spec:
        return f"📋 邮件日报 - {date_spec['single']}"
    r = date_spec["range"]
    return f"📋 邮件汇总 {r['start']} ~ {r['end']}"


def _resolve_path(date_spec: dict, output_dir: Path) -> Path:
    """根据 date_spec 推断已保存的报告文件路径。"""
    if "single" in date_spec:
        return get_summary_path(date_spec["single"])
    return get_aggregate_path(date_spec["range"]["start"], date_spec["range"]["end"])


def _get_since_before(date_spec: dict) -> tuple[str, str]:
    """从 date_spec 提取 IMAP 查询所需的 since/before 日期。

    Returns
    -------
    (since, before) : tuple[str, str]
        since 包含当天，before 为 end+1 天（IMAP 搜索不含 before）。
    """
    if "single" in date_spec:
        return date_to_since_before(date_spec["single"])
    r = date_spec["range"]
    _, before = date_to_since_before(r["end"])
    return r["start"], before



def _show_cache_and_confirm(date_spec: dict, output_dir: Path) -> bool:
    """展示本地缓存并请求用户确认清除。

    Returns
    -------
    bool
        True 表示用户确认继续。
    """
    date_list = expand_dates(date_spec)
    cache_items: list[tuple[str, str]] = []  # (描述, 路径)

    # 邮件归档
    for d in date_list:
        md_dir = get_mail_dir(d)
        count = mail_count(d)
        if count > 0:
            cache_items.append((f"邮件归档 ({count} 封)", str(md_dir)))

    # 单日日报
    for d in date_list:
        sp = get_summary_path(d)
        if sp.exists():
            cache_items.append(("单日日报", str(sp)))

    # 汇总报告（仅范围模式）
    if "range" in date_spec:
        ap = _resolve_path(date_spec, output_dir)
        if ap.exists():
            cache_items.append(("汇总报告", str(ap)))

    if not cache_items:
        print("📭 本地无现有缓存，将直接重新获取。")
        return True

    print("\n📦 本地缓存检查:\n")
    for desc, path in cache_items:
        print(f"  ✅ {desc}: {path}")

    print(f"\n⚠️ 以上 {len(cache_items)} 个缓存将被清除并重新获取。")
    try:
        answer = input("确认继续? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return False

    if answer not in ("y", "yes"):
        print("已取消。")
        return False
    return True


def _clear_caches(date_spec: dict, output_dir: Path, *, skip_mail_dates: set[str] | None = None) -> None:
    """清除指定 date_spec 范围内的本地缓存。

    Parameters
    ----------
    skip_mail_dates : set[str] or None
        跳过邮件归档清除的日期（如已有完整归档的历史日期）。
    """
    skip_mail = skip_mail_dates or set()
    date_list = expand_dates(date_spec)

    for d in date_list:
        # 删除单日日报
        sp = get_summary_path(d)
        if sp.exists():
            sp.unlink()
            print(f"  🗑 已删除日报: {sp}")

        # 删除邮件归档目录（跳过已标记为完整的日期）
        if d not in skip_mail:
            md_dir = get_mail_dir(d)
            if md_dir.exists():
                shutil.rmtree(md_dir)
                print(f"  🗑 已删除邮件归档: {md_dir}")

    # 删除汇总报告（仅范围模式）
    if "range" in date_spec:
        ap = _resolve_path(date_spec, output_dir)
        if ap.exists():
            ap.unlink()
            print(f"  🗑 已删除汇总报告: {ap}")

    print()


# ═══════════════════════════════════════════════════════
#  输出 & 发送（fresh 和 normal 共享，解决 S2 重复）
# ═══════════════════════════════════════════════════════

def _present_and_send(summary: str, path: Path, date_spec: dict,
                      do_send: bool, recipient: str | None) -> None:
    """打印日报内容、文件路径，并根据 do_send 决定是否发送邮件。"""
    print("\n" + "=" * 60)
    print(summary)
    print("=" * 60)
    print(f"\n✨ 日报已保存到: {path}")

    if do_send:
        subject = _make_subject(date_spec)
        send_markdown_mail(summary, subject, recipient)


# ═══════════════════════════════════════════════════════
#  模式 handlers（解决 F1 main() 过长）
# ═══════════════════════════════════════════════════════

def _handle_resend(date_spec: dict, args) -> None:
    """重发模式：直接发送已有报告文件（不重新生成）。"""
    path = _resolve_path(date_spec, OUTPUT_DIR)
    if not path.exists():
        print(f"❌ 报告文件不存在: {path}")
        print("   请先使用 --send 生成并发送报告，或直接运行生成命令。")
        sys.exit(1)
    summary_content = path.read_text(encoding="utf-8")
    print(f"📄 已找到报告: {path}")
    subject = _make_subject(date_spec)
    recipient = args.send_to or None
    send_markdown_mail(summary_content, subject, recipient)


def _handle_fresh(date_spec: dict, args) -> None:
    """全新模式：清除缓存 → 智能重拉 → 重新生成 → 展示/发送。

    智能跳过：历史日期若已有 .fetch_complete 标记则不再重拉邮件。
    """
    date_list = expand_dates(date_spec)

    # 区分需要重拉的和已有完整归档的
    need_refetch = [d for d in date_list if not is_fetch_complete(d)]
    complete_dates = set(d for d in date_list if is_fetch_complete(d))

    if complete_dates:
        print(f"📦 以下日期已有完整归档，将仅重新生成日报（不重拉邮件）: {', '.join(sorted(complete_dates))}")

    if not need_refetch:
        # 全部完整：只清日报缓存，不动邮件归档
        print("✅ 所有日期归档完整，仅清除日报缓存并重新生成。\n")
        _clear_caches(date_spec, OUTPUT_DIR, skip_mail_dates=complete_dates)
    else:
        if not _show_cache_and_confirm(date_spec, OUTPUT_DIR):
            return
        _clear_caches(date_spec, OUTPUT_DIR, skip_mail_dates=complete_dates)

        since, before = _get_since_before(date_spec)
        print(f"📥 正在重新拉取邮件 ({since} ~ {before})...\n")
        fetch_emails_main(n=None, fmt="markdown", since=since, before=before)

        # 为拉取完成的日期写入标记
        for d in need_refetch:
            mark_fetch_complete(d)
        print(f"✅ 已标记 {len(need_refetch)} 个日期为完整归档。\n")

    summary, path = run_digest(date_spec, OUTPUT_DIR)

    if summary and path:
        _present_and_send(summary, path, date_spec, args.send, args.send_to or None)
        print()
    else:
        print("\n⚠️ 日报生成未完成，请检查上述错误信息。")


def _handle_normal(date_spec: dict, args) -> None:
    """普通模式：检查本地归档 → 生成日报 → 展示/发送。"""
    summary, path = run_digest(date_spec, OUTPUT_DIR)

    if summary and path:
        _present_and_send(summary, path, date_spec, args.send, args.send_to or None)
        print(f"   用 Typora / VS Code / 浏览器打开即可阅读。")
        print()
    elif not summary:
        print("\n⚠️ 日报生成未完成，请检查上述错误信息。")


# ═══════════════════════════════════════════════════════
#  入口（瘦身后约 50 行，仅负责解析 + 分发）
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AI 邮件日报助手 — 基于本地邮件归档生成 AI 日报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python daily_summary.py --today
  python daily_summary.py --yesterday
  python daily_summary.py --date 2026-07-15
  python daily_summary.py --this-week
  python daily_summary.py --last-week
  python daily_summary.py --this-month
  python daily_summary.py --last 7
  python daily_summary.py --range 2026-07-01 2026-07-18

发送模式:
  python daily_summary.py --last-week --send           # 生成 + 发送（已有文件自动跳过 AI）
  python daily_summary.py --last-week --resend         # 仅发送已有文件（不生成）
  python daily_summary.py --last-week --resend --send-to user@example.com
  python daily_summary.py --last-week --fresh           # 清除缓存后重新拉取 + 生成
  python daily_summary.py --last-week --fresh --send    # 强制全新拉取 + 生成 + 发送
  python daily_summary.py --date 2026-07-18 --fresh --send  # 单日也支持
""",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--today", action="store_true", help="今天的邮件日报")
    group.add_argument("--yesterday", action="store_true", help="昨天的邮件日报")
    group.add_argument("-d", "--date", type=_validate_date, metavar="YYYY-MM-DD", help="指定日期的邮件日报")
    group.add_argument("--this-week", action="store_true", help="本周一到今天的邮件汇总")
    group.add_argument("--last-week", action="store_true", help="上周一到上周日的邮件汇总")
    group.add_argument("--this-month", action="store_true", help="本月1日到今天的邮件汇总")
    group.add_argument("--last", type=_validate_positive_int, metavar="N", help="最近 N 天的邮件汇总")
    group.add_argument("--range", nargs=2, type=_validate_date, metavar=("START", "END"), help="指定日期范围的邮件汇总")

    parser.add_argument("-s", "--send", action="store_true", help="生成日报后通过 SMTP 发送")
    parser.add_argument("-r", "--resend", action="store_true", help="直接发送已保存的报告文件（不重新生成）")
    parser.add_argument("--fresh", action="store_true", help="强制重新拉取邮件并完全重新生成（清除缓存）")
    parser.add_argument("--send-to", type=str, default="", metavar="EMAIL", help="日报接收邮箱")

    args = parser.parse_args()

    # ── 参数互斥检查 ──
    if args.resend and args.fresh:
        parser.error("--resend 与 --fresh 互斥：--resend 仅发送已有文件，无需清除缓存重新生成。")

    if args.send_to and not (args.send or args.resend):
        parser.error("--send-to 需要配合 --send 或 --resend 使用。")

    # ── 前置检查 CLI（check_available() 失败时已打印诊断信息）──
    if not check_available():
        sys.exit(1)

    # ── 构建 date_spec ──
    today = datetime.now().date()

    if args.today:
        date_spec = _build_single(today.isoformat())
    elif args.yesterday:
        date_spec = _build_single((today - timedelta(days=1)).isoformat())
    elif args.date:
        date_spec = _build_single(args.date)
    elif args.this_week:
        monday = today - timedelta(days=today.weekday())
        date_spec = _build_range(monday.isoformat(), today.isoformat())
    elif args.last_week:
        monday = today - timedelta(days=today.weekday())
        last_monday = monday - timedelta(days=7)
        last_sunday = monday - timedelta(days=1)
        date_spec = _build_range(last_monday.isoformat(), last_sunday.isoformat())
    elif args.this_month:
        first = today.replace(day=1)
        date_spec = _build_range(first.isoformat(), today.isoformat())
    elif args.last:
        start = today - timedelta(days=args.last - 1)
        date_spec = _build_range(start.isoformat(), today.isoformat())
    elif args.range:
        start, end = args.range
        if end < start:
            start, end = end, start
        date_spec = _build_range(start, end)
    else:
        parser.print_help()
        sys.exit(1)

    # ── 反馈解析结果 ──
    if "single" in date_spec:
        print(f"📧 {date_spec['single']} 邮件日报")
    else:
        print(f"📧 {date_spec['range']['start']} ~ {date_spec['range']['end']} 邮件汇总")

    # ── 分发到对应 handler ──
    if args.resend:
        _handle_resend(date_spec, args)
    elif args.fresh:
        _handle_fresh(date_spec, args)
    else:
        _handle_normal(date_spec, args)


if __name__ == "__main__":
    main()
