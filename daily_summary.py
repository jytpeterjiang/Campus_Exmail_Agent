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

模式:
    python daily_summary.py --last-week --send            # 生成 + 发送（已有文件自动跳过AI）
    python daily_summary.py --last-week --resend          # 仅发送已有文件（不生成）
    python daily_summary.py --last-week --regen            # Prompt调优：仅重新生成AI日报（不动邮件）
    python daily_summary.py --last-week --regen --refetch  # 重新生成 + 强制重拉邮件
"""

import argparse
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from email_agent.ai.date_parser import expand_dates, date_to_since_before
from email_agent.cli import main as fetch_emails_main
from email_agent.digest.coordinator import run as run_digest
from email_agent.local_data import (
    get_mail_dir,
    get_summary_path,
    get_aggregate_path,
    get_summary_html_path,
    get_aggregate_html_path,
    mark_fetch_complete,
)
from email_agent.mail_renderer import save_rendered_html
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


def _resolve_html_path(date_spec: dict) -> Path:
    """根据 date_spec 推断 HTML 预览文件的保存路径。"""
    if "single" in date_spec:
        return get_summary_html_path(date_spec["single"])
    return get_aggregate_html_path(date_spec["range"]["start"], date_spec["range"]["end"])


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





def _handle_regen(date_spec: dict, args) -> None:
    """重新生成模式：仅清除 AI 日报缓存并重新生成（不动邮件归档）。

    配合 --refetch 时，同时清除邮件归档并重新拉取（需要用户确认）。
    """
    date_list = expand_dates(date_spec)
    print(f"\n🔄 重新生成模式：清除 {len(date_list)} 天 AI 日报缓存")

    # ── 清除 AI 日报缓存 ──
    for d in date_list:
        sp = get_summary_path(d)
        if sp.exists():
            sp.unlink()
            print(f"  🗑 已删除日报: {sp}")

    if "range" in date_spec:
        ap = _resolve_path(date_spec, OUTPUT_DIR)
        if ap.exists():
            ap.unlink()
            print(f"  🗑 已删除汇总报告: {ap}")

    # ── --refetch: 清除邮件归档并重拉 ──
    if args.refetch:
        print("\n⚠️ --refetch 将清除邮件归档并重新拉取，涉及 IMAP 调用。")
        try:
            answer = input("确认继续? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return
        if answer not in ("y", "yes"):
            print("已取消。")
            return

        for d in date_list:
            md_dir = get_mail_dir(d)
            if md_dir.exists():
                shutil.rmtree(md_dir)
                print(f"  🗑 已删除邮件归档: {md_dir}")

        since, before = _get_since_before(date_spec)
        print(f"\n📥 正在拉取邮件 ({since} ~ {before})...\n")
        fetch_emails_main(n=None, fmt="markdown", since=since, before=before)

        for d in date_list:
            mark_fetch_complete(d)
        print(f"✅ 已标记 {len(date_list)} 个日期为完整归档。\n")

    # ── 重新生成日报 ──
    _handle_normal(date_spec, args)



# ═══════════════════════════════════════════════════════
#  输出 & 发送（normal 和 regen 共享）
# ═══════════════════════════════════════════════════════

def _present_and_send(summary: str, path: Path, date_spec: dict,
                      do_send: bool, recipient: str | None,
                      save_html: bool = False) -> None:
    """打印日报内容、文件路径，并根据参数发送/保存 HTML。"""
    print("\n" + "=" * 60)
    print(summary)
    print("=" * 60)
    print(f"\n✨ 日报已保存到: {path}")

    if save_html:
        html_path = _resolve_html_path(date_spec)
        save_rendered_html(summary, html_path)
        print(f"   用浏览器打开即可预览。")

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

    if args.save_html:
        html_path = _resolve_html_path(date_spec)
        save_rendered_html(summary_content, html_path)
        print(f"   用浏览器打开即可预览。")

    if args.send:
        subject = _make_subject(date_spec)
        recipient = args.send_to or None
        send_markdown_mail(summary_content, subject, recipient)
    elif not args.save_html:
        print("\n⚠️ 请指定 --send 或 --save-html")


def _handle_normal(date_spec: dict, args) -> None:
    """普通模式：检查本地归档 → 生成日报 → 展示/发送。"""
    summary, path = run_digest(date_spec, OUTPUT_DIR)

    if summary and path:
        _present_and_send(summary, path, date_spec, args.send, args.send_to or None,
                          save_html=args.save_html)
        if not args.save_html:
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

发送 & 调优:
  python daily_summary.py --last-week --send            # 生成 + 发送（已有文件自动跳过AI）
  python daily_summary.py --last-week --save-html       # 生成 + 渲染HTML本地预览（不发送）
  python daily_summary.py --last-week --send --save-html # 生成 + 发送 + 同时保存HTML
  python daily_summary.py --last-week --resend          # 仅发送已有文件（不生成）
  python daily_summary.py --last-week --resend --save-html # 发送已有文件 + 同时渲染HTML
  python daily_summary.py --last-week --regen            # Prompt调优：仅重新生成AI日报（不动邮件）
  python daily_summary.py --last-week --regen --refetch  # 重新生成 + 强制重拉邮件
  python daily_summary.py --last-week --regen --send     # 重新生成 + 发送
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
    parser.add_argument("--regen", action="store_true", help="仅重新生成 AI 日报缓存（不动邮件归档，用于 Prompt 调优）")
    parser.add_argument("--refetch", action="store_true", help="配合 --regen 使用，同时清除并重新拉取邮件")
    parser.add_argument("--save-html", action="store_true", help="渲染为 HTML 保存到本地（不发送也可预览）")
    parser.add_argument("--send-to", type=str, default="", metavar="EMAIL", help="日报接收邮箱")

    args = parser.parse_args()

    # ── 参数互斥检查 ──
    if args.resend and args.regen:
        parser.error("--resend 与 --regen 互斥：--resend 仅发送已有文件，无需重新生成。")

    if args.refetch and not args.regen:
        parser.error("--refetch 需要配合 --regen 使用。")

    if args.send_to and not (args.send or args.resend):
        parser.error("--send-to 需要配合 --send 或 --resend 使用。")

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
    elif args.regen:
        _handle_regen(date_spec, args)
    else:
        _handle_normal(date_spec, args)


if __name__ == "__main__":
    main()
