"""SMTP email sender for OpenCold."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(
    smtp_config: dict,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
) -> None:
    """Send a single email via SMTP.

    smtp_config: {host, port, username, password, sender_email, sender_name, use_tls}
    Raises on failure.
    """
    host = smtp_config["host"]
    port = int(smtp_config["port"])
    username = smtp_config["username"]
    password = smtp_config["password"]
    sender_email = smtp_config["sender_email"]
    sender_name = smtp_config.get("sender_name", "")
    use_tls = smtp_config.get("use_tls", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email

    # Plain text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if use_tls and port == 465:
        # SSL connection
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(username, password)
            server.send_message(msg)
    else:
        # STARTTLS or plain
        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(msg)


def test_connection(smtp_config: dict) -> str | None:
    """Test SMTP connection. Returns None on success, error message on failure."""
    try:
        host = smtp_config["host"]
        port = int(smtp_config["port"])
        username = smtp_config["username"]
        password = smtp_config["password"]
        use_tls = smtp_config.get("use_tls", True)

        if use_tls and port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.login(username, password)
        else:
            with smtplib.SMTP(host, port) as server:
                if use_tls:
                    server.starttls(context=ssl.create_default_context())
                server.login(username, password)
        return None
    except Exception as e:
        return str(e)
