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

from email_agent.ai.cli_client import check_available, CLINotFoundError
from email_agent.ai.date_parser import expand_dates
from email_agent.cli import main as fetch_emails_main
from email_agent.digest.coordinator import run as run_digest
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
        d = date_spec["single"]
        return output_dir / d / f"{d}-summary.md"
    r = date_spec["range"]
    return output_dir / f"{r['start']}_{r['end']}-summary.md"


def _get_since_before(date_spec: dict) -> tuple[str, str]:
    """从 date_spec 提取 IMAP 查询所需的 since/before 日期。

    Returns
    -------
    (since, before) : tuple[str, str]
        since 包含当天，before 为 end+1 天（IMAP 搜索不含 before）。
    """
    if "single" in date_spec:
        d = datetime.strptime(date_spec["single"], "%Y-%m-%d")
        return date_spec["single"], (d + timedelta(days=1)).strftime("%Y-%m-%d")
    r = date_spec["range"]
    end_dt = datetime.strptime(r["end"], "%Y-%m-%d")
    return r["start"], (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")


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
        md_dir = output_dir / d / "markdown"
        if md_dir.exists():
            md_files = list(md_dir.glob("*.md"))
            if md_files:
                cache_items.append((f"邮件归档 ({len(md_files)} 封)", str(md_dir)))

    # 单日日报
    for d in date_list:
        sp = output_dir / d / f"{d}-summary.md"
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


def _clear_caches(date_spec: dict, output_dir: Path) -> None:
    """清除指定 date_spec 范围内的所有本地缓存。"""
    date_list = expand_dates(date_spec)

    for d in date_list:
        # 删除单日日报
        sp = output_dir / d / f"{d}-summary.md"
        if sp.exists():
            sp.unlink()
            print(f"  🗑 已删除日报: {sp}")

        # 删除邮件归档目录
        md_dir = output_dir / d / "markdown"
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
#  入口
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
    group.add_argument(
        "--today", action="store_true",
        help="今天的邮件日报"
    )
    group.add_argument(
        "--yesterday", action="store_true",
        help="昨天的邮件日报"
    )
    group.add_argument(
        "--date", type=_validate_date, metavar="YYYY-MM-DD",
        help="指定日期的邮件日报"
    )
    group.add_argument(
        "--this-week", action="store_true",
        help="本周一到今天的邮件汇总"
    )
    group.add_argument(
        "--last-week", action="store_true",
        help="上周一到上周日的邮件汇总"
    )
    group.add_argument(
        "--this-month", action="store_true",
        help="本月1日到今天的邮件汇总"
    )
    group.add_argument(
        "--last", type=_validate_positive_int, metavar="N",
        help="最近 N 天的邮件汇总（N 天前到今天）"
    )
    group.add_argument(
        "--range", nargs=2, type=_validate_date,
        metavar=("START", "END"),
        help="指定日期范围的邮件汇总"
    )

    parser.add_argument(
        "--send", action="store_true",
        help="生成日报后通过 SMTP 发送到指定邮箱（已有报告则直接发送跳过 AI）"
    )
    parser.add_argument(
        "--resend", action="store_true",
        help="直接发送已保存的报告文件（不重新生成，文件必须已存在）"
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="强制重新拉取邮件并完全重新生成（清除本地缓存，需用户确认）"
    )
    parser.add_argument(
        "--send-to", type=str, default="", metavar="EMAIL",
        help="日报接收邮箱（不指定则使用 config.txt 中的 send_to 或发给自己）"
    )

    args = parser.parse_args()

    # ── 前置检查 CLI ──
    try:
        if not check_available():
            raise CLINotFoundError()
    except CLINotFoundError:
        print("❌ 未检测到 CodeBuddy CLI。")
        print("   请先安装: https://www.codebuddy.cn/docs/cli/overview")
        print("   安装后确保 codebuddy 命令在 PATH 中可用。")
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
        print(
            f"📧 {date_spec['range']['start']} ~ "
            f"{date_spec['range']['end']} 邮件汇总"
        )

    # ── 重发模式：直接发送已有报告 ──
    if args.resend:
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
        return

    # ── 全新模式：清除缓存 → 重新拉取 → 重新生成 ──
    if args.fresh:
        if not _show_cache_and_confirm(date_spec, OUTPUT_DIR):
            return

        _clear_caches(date_spec, OUTPUT_DIR)

        # 重新拉取邮件
        since, before = _get_since_before(date_spec)
        print(f"📥 正在重新拉取邮件 ({since} ~ {before})...\n")
        fetch_emails_main(n=None, fmt="markdown", since=since, before=before)

        # 重新生成日报
        summary, path = run_digest(date_spec, OUTPUT_DIR)

        if summary and path:
            print("\n" + "=" * 60)
            print(summary)
            print("=" * 60)
            print(f"\n✨ 日报已保存到: {path}")
            print()

            if args.send:
                subject = _make_subject(date_spec)
                recipient = args.send_to or None
                send_markdown_mail(summary, subject, recipient)
        else:
            print("\n⚠️ 日报生成未完成，请检查上述错误信息。")
        return

    # ── 执行：检查本地归档 → 生成日报 → 保存 ──
    summary, path = run_digest(date_spec, OUTPUT_DIR)

    if summary and path:
        print("\n" + "=" * 60)
        print(summary)
        print("=" * 60)
        print(f"\n✨ 日报已保存到: {path}")
        print("   用 Typora / VS Code / 浏览器打开即可阅读。")
        print()

        # ── 邮件发送 ──
        if args.send:
            subject = _make_subject(date_spec)
            recipient = args.send_to or None  # None → 使用 config 默认值
            send_markdown_mail(summary, subject, recipient)

    elif not summary:
        print("\n⚠️ 日报生成未完成，请检查上述错误信息。")


if __name__ == "__main__":
    main()
