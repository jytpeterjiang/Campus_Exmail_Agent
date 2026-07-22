"""AI 模块 — 统一的 AI 调用入口。"""

from email_agent.ai.client import query, AIError
from email_agent.ai.prompts import (
    SYSTEM_PROMPT,
    AGGREGATE_SYSTEM_PROMPT,
    build_single_day_prompt,
    build_aggregate_prompt,
)
