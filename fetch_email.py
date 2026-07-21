"""拉取 IMAP 收件箱邮件并生成 HTML/Markdown 归档。

用法:
    python fetch_email.py                                           # 默认：今天最新 5 封，both 格式
    python fetch_email.py --count 10 --format html --on 2026-07-15  # 指定某一天
    python fetch_email.py --on 2026-07-01 2026-07-18                # 指定日期范围
    python fetch_email.py --on 2026-07-01 ..                        # 7月1日之后（不含结束日期）
    python fetch_email.py --on .. 2026-07-18                        # 7月18日之前（不含起始日期）
    python fetch_email.py --on 2026-07-01 2026-07-18 --all          # 日期范围内全部邮件

    默认值: --count 5  --format both  --on now
"""
import argparse
import sys
from datetime import datetime, timedelta
from email_agent.cli import main
from email_agent.imap_client import count_matching_emails, IMAPError

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="从 IMAP 收件箱拉取邮件并生成 HTML/Markdown 归档"
    )
    parser.add_argument(
        "--count", "-n", type=int, default=5,
        help="最多拉取 N 封最新邮件，默认 5（与 --all 互斥，--all 优先）",
    )
    parser.add_argument(
        "--all", "-a", action="store_true",
        help="获取日期范围内全部邮件，等同于不限制数量",
    )
    parser.add_argument(
        "--format", "-f", type=str, default="both",
        choices=["html", "markdown", "both"],
        help="输出格式: html | markdown | both，默认 both",
    )
    parser.add_argument(
        "--on", type=str, nargs="+", default=["now"],
        help="日期过滤: YYYY-MM-DD | now | YYYY-MM-DD YYYY-MM-DD（since before），"
             "用 .. 作为无边界占位，如 '2026-07-01 ..'（之后）或 '.. 2026-07-18'（之前），默认 now",
    )
    args = parser.parse_args()

    # ── 处理 --on 参数 ──
    n_args = len(args.on)
    if n_args == 1:
        if args.on[0].lower() == "now":
            target_date = datetime.now()
        else:
            target_date = datetime.strptime(args.on[0], "%Y-%m-%d")
        since = target_date.strftime("%Y-%m-%d")
        before = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    elif n_args == 2:
        since = args.on[0] if args.on[0] != ".." else None
        before = args.on[1] if args.on[1] != ".." else None
    else:
        parser.error("--on 最多接受 2 个参数: YYYY-MM-DD [YYYY-MM-DD]")

    # ── --all 时二次确认 ──
    if args.all:
        try:
            count = count_matching_emails(since=since, before=before)
        except IMAPError as e:
            print(f"[错误] {e}")
            sys.exit(1)
        if count == 0:
            print("日期范围内没有匹配的邮件，退出。")
            sys.exit(0)
        print(f"日期范围内共有 {count} 封邮件，确认拉取全部？(y/n): ", end="", flush=True)
        try:
            user_input = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            sys.exit(0)
        if user_input not in ("y", "yes"):
            print("已取消。")
            sys.exit(0)
        print()

    main(n=None if args.all else args.count, fmt=args.format, since=since, before=before)
