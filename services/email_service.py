from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl

from services.config import config


class EmailDeliveryError(RuntimeError):
    """Raised when an SMTP server rejects or fails a message."""


def _clean(value: object) -> str:
    return str(value or "").strip()


def _message(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str = "",
) -> EmailMessage:
    from_email = config.smtp_from_email
    if not config.smtp_host or not from_email:
        raise ValueError("smtp is not configured")
    message = EmailMessage()
    sender_name = config.site_title or "Image Studio"
    message["From"] = formataddr((sender_name, from_email))
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def send_email(*, to_email: str, subject: str, text: str, html: str = "") -> None:
    recipient = _clean(to_email).lower()
    if "@" not in recipient:
        raise ValueError("recipient email is invalid")

    message = _message(to_email=recipient, subject=subject, text=text, html=html)
    context = ssl.create_default_context()
    host = config.smtp_host
    port = config.smtp_port
    username = config.smtp_username
    password = config.smtp_password

    try:
        if config.smtp_use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                _login_if_needed(server, username, password)
                server.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if config.smtp_use_starttls:
                server.starttls(context=context)
                server.ehlo()
            _login_if_needed(server, username, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(str(exc)) from exc


def _login_if_needed(server: smtplib.SMTP, username: str, password: str) -> None:
    if not (config.smtp_force_auth_login or username or password):
        return
    if not username or not password:
        raise ValueError("smtp username and password are required")
    server.login(username, password)


def send_verification_email(*, to_email: str, code: str) -> None:
    site_title = config.site_title or "Image Studio"
    subject = f"{site_title} 邮箱验证码"
    text = (
        f"你的 {site_title} 注册验证码是：{code}\n\n"
        "验证码 10 分钟内有效。如果不是你本人操作，请忽略这封邮件。"
    )
    html = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f7f7f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1c1917;">
    <div style="max-width:480px;margin:0 auto;background:#fff;border:1px solid #f4e7e7;border-radius:12px;padding:24px;">
      <h1 style="margin:0 0 12px;font-size:20px;line-height:28px;">{site_title} 邮箱验证</h1>
      <p style="margin:0 0 16px;color:#57534e;font-size:14px;line-height:22px;">请输入下面的验证码完成注册，验证码 10 分钟内有效。</p>
      <div style="letter-spacing:8px;font-size:30px;font-weight:700;color:#e11d48;background:#fff1f2;border-radius:10px;padding:14px 18px;text-align:center;">{code}</div>
      <p style="margin:18px 0 0;color:#78716c;font-size:12px;line-height:20px;">如果不是你本人操作，请忽略这封邮件。</p>
    </div>
  </body>
</html>
"""
    send_email(to_email=to_email, subject=subject, text=text, html=html)


def send_password_reset_email(*, to_email: str, code: str) -> None:
    site_title = config.site_title or "Image Studio"
    subject = f"{site_title} 找回密码验证码"
    text = (
        f"你的 {site_title} 找回密码验证码是：{code}\n\n"
        "验证码 10 分钟内有效。如果不是你本人操作，请忽略这封邮件。"
    )
    html = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f7f7f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1c1917;">
    <div style="max-width:480px;margin:0 auto;background:#fff;border:1px solid #f4e7e7;border-radius:12px;padding:24px;">
      <h1 style="margin:0 0 12px;font-size:20px;line-height:28px;">{site_title} 找回密码</h1>
      <p style="margin:0 0 16px;color:#57534e;font-size:14px;line-height:22px;">请输入下面的验证码重置密码，验证码 10 分钟内有效。</p>
      <div style="letter-spacing:8px;font-size:30px;font-weight:700;color:#0f766e;background:#ecfdf5;border-radius:10px;padding:14px 18px;text-align:center;">{code}</div>
      <p style="margin:18px 0 0;color:#78716c;font-size:12px;line-height:20px;">如果不是你本人操作，请忽略这封邮件。</p>
    </div>
  </body>
</html>
"""
    send_email(to_email=to_email, subject=subject, text=text, html=html)
