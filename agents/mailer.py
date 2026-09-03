"""Send emails via Gmail SMTP with optional PDF attachment."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from .config import get_gmail_user, get_gmail_app_password


def send_email(to: str, subject: str, body: str,
               pdf_path: str = "", sender_name: str = "The Team",
               attachment_path: str = "") -> dict:
    """Send an email via Gmail SMTP. Returns success status.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.
        pdf_path: Optional PDF to attach (auto-generated proposal).
        sender_name: Name in the From field.
        attachment_path: Optional user-specified file to attach.
    """
    gmail_user = get_gmail_user()
    gmail_pass = get_gmail_app_password()

    if not gmail_user or not gmail_pass:
        return {"success": False, "error": "Gmail not configured. Run setup first."}

    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{gmail_user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Attach PDF if provided
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="pdf")
            filename = Path(pdf_path).name
            attach.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(attach)

    # Attach user-specified file if provided
    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, "rb") as f:
            attach = MIMEApplication(f.read())
            filename = Path(attachment_path).name
            attach.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(attach)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
        return {"success": True, "to": to, "subject": subject}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "Gmail authentication failed. Check your app password."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_batch(emails: list[dict], sender_name: str = "The Team") -> list[dict]:
    """Send multiple emails. Each dict has: to, subject, body, pdf_path, attachment_path."""
    results = []
    for email_data in emails:
        result = send_email(
            to=email_data["to"],
            subject=email_data["subject"],
            body=email_data["body"],
            pdf_path=email_data.get("pdf_path", ""),
            sender_name=sender_name,
            attachment_path=email_data.get("attachment_path", ""),
        )
        results.append(result)
    return results
