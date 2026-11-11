"""Outbound mail for magic links. If SMTP_HOST is unset, magic links stay disabled.

Tests set KAIRO_MAIL_SINK to a file path. Messages are appended there and never sent.
"""
import os, smtplib
from email.message import EmailMessage

def configured():
    return bool(os.environ.get("SMTP_HOST") or os.environ.get("KAIRO_MAIL_SINK"))

def send(to, subject, body):
    sink = os.environ.get("KAIRO_MAIL_SINK")
    if sink:
        with open(sink, "a", encoding="utf-8") as f:
            f.write(f"TO:{to}\nSUBJECT:{subject}\n{body}\n---\n")
        return
    if not os.environ.get("SMTP_HOST"):
        raise RuntimeError("SMTP non configuré")
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "kairo@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as s:
        if os.environ.get("SMTP_TLS", "1") != "0":
            s.starttls()
        user = os.environ.get("SMTP_USER")
        if user:
            s.login(user, os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
