"""CodeBuddy CLI 统一通信层。

封装所有 subprocess 调用，对外暴露简洁的同步接口。
调用方不需要知道 CLI 参数细节，只需传业务参数。
"""

import json
import locale
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class CLIClientError(Exception):
    """CLI 调用异常。"""
    pass


class CLINotFoundError(CLIClientError):
    """CLI 未安装。"""
    pass


# ═══════════════════════════════════════════════════════
#  CodeBuddy 可执行文件路径缓存
# ═══════════════════════════════════════════════════════

_codebuddy_path: Optional[str] = None


def _resolve_codebuddy_path() -> Optional[str]:
    """查找 codebuddy 可执行文件路径。缓存结果以避免重复查找。"""
    global _codebuddy_path
    if _codebuddy_path is not None:
        return _codebuddy_path

    # 优先使用 shutil.which（正确处理 Windows PATHEXT）
    exe_path = shutil.which("codebuddy")
    if exe_path is not None:
        _codebuddy_path = exe_path
        return _codebuddy_path

    # shutil.which 没找到，用 shell=True 让系统 shell 解析
    try:
        subprocess.run(
            "codebuddy --version",
            capture_output=True, timeout=5,
            shell=True,
        )
        # shell=True 能跑通，后续调用也走 shell=True
        _codebuddy_path = "codebuddy"  # 标记为仅 shell 模式
        return _codebuddy_path
    except Exception:
        pass

    return None


# ═══════════════════════════════════════════════════════
#  可用性检查
# ═══════════════════════════════════════════════════════

def check_available() -> bool:
    """验证 codebuddy CLI 是否可用。"""
    path = _resolve_codebuddy_path()
    if path is None:
        # 打印诊断信息
        print("[诊断] codebuddy 未能在以下 PATH 中找到:")
        for p in os.environ.get("PATH", "").split(os.pathsep):
            print(f"  - {p}")
        return False

    try:
        subprocess.run(
            [path, "--version"] if path != "codebuddy" else "codebuddy --version",
            capture_output=True, timeout=5,
            shell=(path == "codebuddy"),
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
#  核心查询接口
# ═══════════════════════════════════════════════════════

def query(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    add_dirs: Optional[list[Path]] = None,
    max_turns: int = 10,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> str:
    """调用 CodeBuddy CLI 执行一次性查询，返回 stdout 文本。

    Parameters
    ----------
    prompt : str
        用户提示词，作为 -p 参数传入。
    system_prompt : str or None
        系统提示词，通过 --append-system-prompt 注入。
    add_dirs : list[Path] or None
        需要 CLI 访问的目录列表，转为 --add-dir 参数。
    max_turns : int
        最大对话轮数，默认 10。
    timeout : int
        超时秒数，默认 60。

    Returns
    -------
    str
        CLI 的 stdout 输出（去除首尾空白）。

    Raises
    ------
    CLINotFoundError
        CLI 未安装。
    CLIClientError
        调用失败、返回非零或超时。
    """
    codebuddy_path = _resolve_codebuddy_path()
    if codebuddy_path is None:
        raise CLINotFoundError(
            "CodeBuddy CLI 未安装。请访问 https://www.codebuddy.cn/docs/cli/overview"
        )
    use_shell = (codebuddy_path == "codebuddy")

    if use_shell:
        # shell=True 模式，拼接完整命令字符串
        parts = [
            "codebuddy",
            "-p", f'"{prompt}"',
            "--model", "deepseek-v4-flash",
            "--max-turns", str(max_turns),
            "--permission-mode", "auto",
            "-y",
        ]
        if system_prompt:
            parts.extend(["--append-system-prompt", f'"{system_prompt}"'])
        if add_dirs:
            for d in add_dirs:
                parts.extend(["--add-dir", str(d.resolve())])
        cmd = " ".join(parts)
    else:
        cmd = [
            codebuddy_path,
            "-p", prompt,
            "--model", "deepseek-v4-flash",
            "--max-turns", str(max_turns),
            "--permission-mode", "auto",
            "-y",
        ]
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
        if add_dirs:
            for d in add_dirs:
                cmd.extend(["--add-dir", str(d.resolve())])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            shell=use_shell,
        )
    except subprocess.TimeoutExpired:
        raise CLIClientError(f"CLI 调用超时（>{timeout}s）")
    except FileNotFoundError:
        raise CLINotFoundError("CodeBuddy CLI 未安装")

    stdout = _decode_output(result.stdout)
    stderr = _decode_output(result.stderr)

    if result.returncode != 0:
        raise CLIClientError(
            f"CLI 返回非零退出码 {result.returncode}: {stderr.strip()}"
        )

    return stdout.strip()


def query_json(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    max_turns: int = 5,
    timeout: int = 30,
    cwd: Optional[Path] = None,
) -> Optional[dict]:
    """调用 CLI 并尝试从 stdout 提取 JSON。

    比 query() 多一层 JSON 解析兜底：
    先用 json.loads 尝试完整解析，失败后用正则提取 {...}。
    """
    raw = query(
        prompt=prompt,
        system_prompt=system_prompt,
        max_turns=max_turns,
        timeout=timeout,
        cwd=cwd,
    )
    return _extract_json(raw)


# ═══════════════════════════════════════════════════════
#  内部工具
# ═══════════════════════════════════════════════════════

def _decode_output(data: bytes) -> str:
    """解码 subprocess 输出字节，优先 UTF-8，失败回退系统编码。"""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), errors="replace")


def _extract_json(text: str) -> Optional[dict]:
    """从文本中提取 JSON 对象。"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 正则兜底：匹配第一个 {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
