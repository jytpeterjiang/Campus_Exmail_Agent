"""邮件发送模块 — 将 Markdown 日报转换为 HTML 邮件并通过 SMTP 发送。"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid


def send_markdown_mail(
    markdown_body: str,
    subject: str,
    recipient: str | None = None,
) -> bool:
    """将 Markdown 内容作为邮件发送（plain text + HTML 双版本）。

    Args:
        markdown_body: 日报的 Markdown 文本
        subject: 邮件主题
        recipient: 收件人地址；为 None 时使用 SEND_TO 或 EMAIL（发给自己）

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
    msg.attach(MIMEText(markdown_body, "plain", "utf-8"))

    # HTML 版本（主流邮件客户端优先展示此版本）
    try:
        import markdown2
    except ImportError:
        print("⚠️ 未安装 markdown2，仅发送纯文本版本")
        print("   安装: pip install markdown2")
    else:
        html_body = _md_to_html(markdown_body)
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


def _md_to_html(md_text: str) -> str:
    """将 Markdown 转换为适合邮件展示的内联 HTML。"""
    import markdown2

    html_content = markdown2.markdown(
        md_text,
        extras=[
            "tables",
            "fenced-code-blocks",
            "header-ids",
            "strike",
            "task_list",
        ],
    )

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, \
sans-serif; max-width: 720px; margin: 0 auto; padding: 20px; line-height: 1.6; \
color: #333; background: #fff;">
{html_content}
</body>
</html>"""
