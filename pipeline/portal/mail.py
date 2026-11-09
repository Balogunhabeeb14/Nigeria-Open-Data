"""Encrypted transactional outbox, drained by the existing Prefect worker."""
import json
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import HTTPException
from pipeline.settings import settings
from pipeline.portal import store
from pipeline.portal.security import seal, unseal, vault


def configured():
    vault()
    if not settings.smtp_host:
        raise HTTPException(503, "Email delivery is not configured. Ask the operator to configure SMTP.")
    if not settings.smtp_starttls and settings.portal_cookie_secure:
        raise HTTPException(503, "Production email delivery requires TLS.")


def enqueue(conn, email, action, token):
    configured()
    link = f"{settings.frontend_url.rstrip('/')}/account#action={action}&token={token}"
    payload = json.dumps({"subject": f"Nigeria Open Data: {action}", "body": f"Complete your {action} request:\n\n{link}\n\nIgnore this email if you did not request it."})
    store.execute(conn, "INSERT INTO cdm.portal_mail_outbox(recipient,payload_ciphertext) VALUES (:email,:payload)", email=email, payload=seal(payload))


def send(email, payload):
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = payload["subject"]
    message.set_content(payload["body"])
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
        smtp.send_message(message)


def drain():
    if not settings.smtp_host:
        return 0
    sent = 0
    # Row locks prevent multiple dispatcher processes from sending concurrently.
    with store.engine().begin() as conn:
        rows = store.all_rows(conn, """SELECT * FROM cdm.portal_mail_outbox
            WHERE sent_at IS NULL AND attempts<8 AND next_attempt_at<=NOW()
            ORDER BY next_attempt_at LIMIT 10 FOR UPDATE SKIP LOCKED""")
        for row in rows:
            try:
                send(row["recipient"], json.loads(unseal(row["payload_ciphertext"])))
                store.execute(conn, "UPDATE cdm.portal_mail_outbox SET sent_at=NOW() WHERE id=:id", id=row["id"])
                sent += 1
            except Exception:
                # SMTP exceptions may contain authentication details; never log them.
                store.execute(conn, """UPDATE cdm.portal_mail_outbox SET attempts=attempts+1,
                    next_attempt_at=NOW()+INTERVAL '5 minutes' WHERE id=:id""", id=row["id"])
    return sent
