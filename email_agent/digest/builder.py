"""日报构建器：组装参数，调用 CLI，返回 Markdown 内容。

两个核心函数：
- generate_single_day()：读原始 .md 邮件 → 生成单日日报
- aggregate_summaries()：读已有日报 → 聚合为周报/月报
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from email_agent.ai.cli_client import query, CLIClientError
from email_agent.ai.prompts import build_single_day_prompt, build_aggregate_prompt, SINGLE_DAY_SYSTEM, AGGREGATE_SYSTEM


# ═══════════════════════════════════════════════════════
#  输出清理
# ═══════════════════════════════════════════════════════

def _clean_output(text: str) -> str:
    """清理 CLI 输出中的非内容噪音。

    模型在非交互模式下可能输出前缀噪音和尾部闲聊：
    - 前缀：权限提示、免责声明等
    - 尾部："请告诉我如何继续"、"是否需要写入" 等交互追问

    策略：
    1. 跳过非 Markdown 内容开头的前缀
    2. 找到 footer 标记行后截断尾部
    3. 兜底：反向扫描尾部闲聊行
    """
    lines = text.split("\n")

    # ── 第一步：前缀清理 ──
    # 如果行包含以下元描述关键词，判定为非内容噪音，不视为有效开头
    meta_kw = ["流程", "操作", "步骤", "授权", "方式", "运行", "脚本", "执行",
               "不需要", "建议", "注意", "提醒", "请提供"]
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(kw in stripped for kw in meta_kw):
            continue
        # 日报常见的有效开头：标题、引用、表格、加粗、列表、有序列表
        if (stripped.startswith("#") or stripped.startswith(">")
                or stripped.startswith("|") or stripped.startswith("*")
                or (stripped.startswith("- ") and not stripped.startswith("- 请"))):
            start = i
            break
    if start > 0:
        lines = lines[start:]

    # ── 第二步：尾部 footer 截断 ──
    footer_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("*本日报由 ") or stripped.startswith("*本报告由 Email Agent"):
            footer_idx = i
            break

    if footer_idx is not None:
        # footer 之后的内容全部丢弃
        lines = lines[:footer_idx + 1]

    # ── 第三步：兜底 - 反向扫描尾部闲聊行 ──
    # 去掉末尾纯分隔线
    while lines and lines[-1].strip() == "---":
        lines.pop()
    # 去掉末尾空白行
    while lines and not lines[-1].strip():
        lines.pop()

    chat_kw = ["写入", "落盘", "请告诉", "授权", "是否继续", "是否需要", "帮你", "让我",
               "请提供", "格式模板"]
    chat_trim = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if any(kw in stripped for kw in chat_kw):
            chat_trim = i
        else:
            break

    if chat_trim < len(lines):
        lines = lines[:chat_trim]
        while lines and not lines[-1].strip():
            lines.pop()

    cleaned = "\n".join(lines).strip()
    # 清洗后仍不以 Markdown 标题开头 → AI 没有生成有效日报（可能是问答/解释文本）
    if not cleaned or not cleaned.startswith("#"):
        return None
    return cleaned


def _ensure_footer(text: str, footer: str) -> str:
    """防御性补全：如果文本末尾没有预期的 footer 行，自动追加。

    解决 AI 可能因 token 截断或提前结束而遗漏 footer 的问题。
    """
    if not text:
        return text
    # 检查是否已包含 footer 关键字（避免重复追加）
    if "*本日报由 " in text or "*本报告由 Email Agent" in text:
        return text
    return text.rstrip() + "\n\n---\n" + footer


# ═══════════════════════════════════════════════════════
#  单日日报生成
# ═══════════════════════════════════════════════════════

def generate_single_day(date_str: str, output_dir: Path) -> Optional[str]:
    """生成单日日报（读原始 .md 邮件文件）。

    仅在目标日期尚无 -summary.md 时调用。
    AI 通过 --add-dir 自主读取邮件文件。

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

    prompt = build_single_day_prompt(date_str)

    try:
        raw = query(
            prompt=prompt,
            system_prompt=SINGLE_DAY_SYSTEM,
            add_dirs=[md_dir],
            max_turns=30,
            timeout=300,
        )
        result = _clean_output(raw)
        if result:
            footer = f"*本日报由 Email Agent 基于本地归档生成 · 数据来源：`output/{date_str}/`*"
            result = _ensure_footer(result, footer)
        return result
    except CLIClientError as e:
        print(f"  ❌ {date_str} 日报生成失败: {e}")
        return None


# ═══════════════════════════════════════════════════════
#  多日汇总
# ═══════════════════════════════════════════════════════

def aggregate_summaries(
    start: str, end: str, date_list: list[str], output_dir: Path
) -> Optional[str]:
    """聚合多日日报为一个综合汇总报告。

    AI 通过 --add-dir 自主读取 output 目录下各日期的 -summary.md 文件，
    避免将日报内容内联到命令行参数导致超长。

    Parameters
    ----------
    start : str
        起始日期 "YYYY-MM-DD"。
    end : str
        结束日期 "YYYY-MM-DD"。
    date_list : list[str]
        需要汇总的日期列表。
    output_dir : Path
        项目 output 根目录，通过 --add-dir 暴露给 AI。

    Returns
    -------
    str or None
        汇总报告 Markdown 内容。
    """
    if not date_list:
        return None

    prompt = build_aggregate_prompt(start, end, date_list)

    try:
        raw = query(
            prompt=prompt,
            system_prompt=AGGREGATE_SYSTEM,
            add_dirs=[output_dir],
            max_turns=20,
            timeout=300,
        )
        result = _clean_output(raw)
        if result:
            footer = f"*本报告由 Email Agent 基于每日日报汇总生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
            result = _ensure_footer(result, footer)
        return result
    except CLIClientError as e:
        print(f"❌ 汇总生成失败: {e}")
        return None
