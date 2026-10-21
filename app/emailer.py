import smtplib
from email.message import EmailMessage
from typing import Any


def send_password_reset_email(
    config: dict[str, Any], recipient: str, reset_url: str
) -> None:
    host = config.get("SMTP_HOST")
    sender = config.get("SMTP_FROM")
    if not isinstance(host, str) or not host or not isinstance(sender, str) or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM must be configured")

    message = EmailMessage()
    message["Subject"] = "Đặt lại mật khẩu MiniLMS"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Hãy sử dụng liên kết sau để đặt lại mật khẩu MiniLMS. "
        "Liên kết hết hạn sau 30 phút và chỉ dùng được một lần:\n\n"
        f"{reset_url}\n"
    )

    port = int(config.get("SMTP_PORT", 587))
    username = config.get("SMTP_USERNAME")
    password = config.get("SMTP_PASSWORD")
    use_ssl = bool(config.get("SMTP_USE_SSL", False))
    client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with client_class(host, port, timeout=15) as client:
        if not use_ssl and config.get("SMTP_USE_TLS", True):
            client.starttls()
        if username:
            client.login(username, password or "")
        client.send_message(message)
