"""邮件发送模块 — 纯 SMTP 传输，不处理内容渲染。

内容渲染由 mail_renderer 模块负责。
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from typing import Optional

from email_agent.mail_renderer import render_email_html


def send_markdown_mail(
    markdown_body: str,
    subject: str,
    recipient: Optional[str] = None,
) -> bool:
    """将 Markdown 日报渲染为美观的 HTML 邮件并发送。

    内部委托给 send_html_mail()：
    1. mail_renderer.render_email_html() 负责 Markdown → HTML 渲染
    2. send_html_mail() 负责 MIME 构建 + SMTP 传输

    Args:
        markdown_body: 日报的 Markdown 文本
        subject: 邮件主题
        recipient: 收件人地址；为 None 时使用 SEND_TO 或 EMAIL（发给自己）

    Returns:
        是否发送成功
    """
    html_body = render_email_html(markdown_body)
    return send_html_mail(html_body, markdown_body, subject, recipient)


def send_html_mail(
    html_body: str,
    plain_body: str = "",
    subject: str = "",
    recipient: Optional[str] = None,
) -> bool:
    """发送 HTML 邮件（同时附带纯文本版本作为兜底）。

    这是底层发送 API，不处理任何内容转换。
    如需从 Markdown 发送，请使用 send_markdown_mail()。

    Args:
        html_body: HTML 格式的邮件正文
        plain_body: 纯文本版本（邮件客户端不支持 HTML 时的兜底展示）
        subject: 邮件主题
        recipient: 收件人地址；为 None 时使用 SEND_TO 或 EMAIL

    Returns:
        是否发送成功
    """
    from email_agent.config import (
        SMTP_SERVER, SMTP_PORT, EMAIL, PASSWORD, SEND_TO,
    )

    if not EMAIL or not PASSWORD:
        print("❌ 邮件发送失败: config.txt 中缺少 email 或 password")
        return False

    destination = recipient or SEND_TO or EMAIL

    # ── 构建 MIME multipart ──
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = destination
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=EMAIL.split("@")[-1])

    # 纯文本版本（邮件客户端不支持 HTML 时的兜底）
    if plain_body:
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))

    # HTML 版本（主流邮件客户端优先展示此版本）
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # ── SMTP SSL 发送 ──
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL, PASSWORD)
            server.send_message(msg)
        print(f"📨 日报已发送至: {destination}")
        return True
    except smtplib.SMTPException as e:
        print(f"❌ SMTP 发送失败: {e}")
        return False
