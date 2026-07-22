"""轻量级 AI 客户端 — 基于 OpenAI 兼容 API。

设计原则：纯文本进/文本出，不感知文件系统。
文件读取是调用方的职责。

支持所有 OpenAI 兼容服务：
- DeepSeek (api.deepseek.com)
- OpenAI 官方 (api.openai.com)
- Groq (api.groq.com)
- Ollama 本地 (localhost:11434)
- 任意兼容代理/网关
"""

import os
from typing import Literal, Optional

from openai import OpenAI

from email_agent import config


class AIError(Exception):
    """AI 调用异常。"""
    pass


def _build_client() -> OpenAI:
    """根据配置构建 OpenAI 兼容客户端。"""
    api_key = config.AI_API_KEY or os.environ.get("AI_API_KEY")
    return OpenAI(
        base_url=config.AI_BASE_URL,
        api_key=api_key,
    )


def query(
    *,
    system_prompt: Optional[str] = None,
    user_prompt: str,
    temperature: float = None,  # type: ignore[assignment]  # 默认值从 config 读取
    top_p: Optional[float] = None,
    max_tokens: int = None,  # type: ignore[assignment]  # 默认值从 config 读取
    stop: Optional[list[str]] = None,
    timeout: int = 120,
    response_format: Literal["text", "json"] = "text",
    thinking: bool = None,  # type: ignore[assignment]  # 默认值从 config 读取
    reasoning_effort: Optional[Literal["high", "max"]] = None,
    user_id: Optional[str] = None,
    extra_body: Optional[dict] = None,
) -> str:
    """调用 AI 生成文本（纯文本进/文本出，不感知文件系统）。

    Args:
        system_prompt: 系统提示词（可选）
        user_prompt: 用户提示词（邮件内容已由调用方内联）
        temperature: 采样温度 (0.0~2.0)，日报推荐 0.3。
            ⚠️ DeepSeek 思考模式下此参数无效。
        top_p: 核采样 (0.0~1.0)，None 不传使用 API 默认值 1.0。
            ⚠️ DeepSeek 思考模式下此参数无效。
        max_tokens: 输出最大 token 数，默认 8192
        stop: 停止词列表（最多 16 个），遇到即停止生成
        timeout: 请求超时（秒），默认 120
        response_format: 输出格式，"text" 或 "json"
        thinking: 是否启用 DeepSeek 思考模式（默认关闭）。
            日报场景无需深度推理，关闭可避免额外思考 token 费用。
        reasoning_effort: 推理强度，"high" 或 "max"。仅 thinking=True 时生效。
        user_id: 自定义用户标识（最大 512 字符），用于 KVCache 缓存隔离与调度隔离
        extra_body: 透传到请求体的额外字段（用于 API 特有参数的 escape hatch）

    Returns:
        AI 生成的文本

    Raises:
        AIError: API 调用失败
    """
    # ── 参数默认值从配置文件读取 ──
    if thinking is None:
        thinking = config.AI_THINKING
    if temperature is None:
        temperature = config.AI_TEMPERATURE
    if max_tokens is None:
        max_tokens = config.AI_MAX_TOKENS

    client = _build_client()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    # ── 构建 API 调用参数 ──
    api_params: dict = {
        "model": config.AI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }

    if top_p is not None:
        api_params["top_p"] = top_p

    if stop is not None:
        api_params["stop"] = stop

    if response_format == "json":
        api_params["response_format"] = {"type": "json_object"}

    if thinking and reasoning_effort is not None:
        api_params["reasoning_effort"] = reasoning_effort

    if user_id is not None:
        api_params["user_id"] = user_id

    # 思考模式控制（DeepSeek V4 默认开启，日报场景关掉）
    body = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    if extra_body:
        body.update(extra_body)
    api_params["extra_body"] = body

    try:
        response = client.chat.completions.create(**api_params)
        return response.choices[0].message.content or ""
    except Exception as e:
        raise AIError(f"AI API 调用失败: {e}")
