"""Correo del agente: SMTP para hablar, IMAP para escuchar.

smtplib/imaplib son bloqueantes, así que cada operación se despacha a un hilo.
"""

import asyncio
import email
import imaplib
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr


@dataclass
class Attachment:
    filename: str
    content: bytes


@dataclass
class Message:
    uid: str
    sender: str
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)
    from_name: str = ""
    # (nombre, correo) de To + Cc de la cabecera. OJO: en un correo reenviado los
    # destinatarios ORIGINALES no están aquí sino dentro del cuerpo citado.
    recipients: list[tuple[str, str]] = field(default_factory=list)
    message_id: str = ""


class EmailClient:
    def __init__(
        self,
        address: str,
        password: str,
        imap_host: str = "imap.gmail.com",
        imap_port: int = 993,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.address = address
        self._password = password
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    # ── Hablar ───────────────────────────────────────────────────────────

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = f"U2NyaWJl <{self.address}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.address, self._password)
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)

    # ── Escuchar ─────────────────────────────────────────────────────────

    def _fetch_sync(self, label: str, unread_only: bool) -> list[Message]:
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        try:
            conn.login(self.address, self._password)
            # Gmail expone las etiquetas como carpetas IMAP.
            status, _ = conn.select(f'"{label}"' if label else "INBOX")
            if status != "OK":
                return []

            criterion = "UNSEEN" if unread_only else "ALL"
            status, data = conn.search(None, criterion)
            if status != "OK" or not data[0]:
                return []

            messages: list[Message] = []
            for uid in data[0].split():
                status, raw = conn.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                messages.append(self._parse(uid.decode(), raw[0][1]))
            return messages
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def _parse(uid: str, raw: bytes) -> Message:
        msg = email.message_from_bytes(raw)
        from_name, sender = parseaddr(msg.get("From", ""))
        subject = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
        recipients = getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))
        message_id = (msg.get("Message-ID", "") or "").strip()

        body = ""
        attachments: list[Attachment] = []

        for part in msg.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if part.get_content_type() == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload and not body:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif "attachment" in disposition:
                filename = part.get_filename()
                payload = part.get_payload(decode=True)
                if filename and payload:
                    attachments.append(Attachment(filename=filename, content=payload))

        return Message(uid=uid, sender=sender, subject=subject, body=body,
                       attachments=attachments, from_name=from_name,
                       recipients=recipients, message_id=message_id)

    async def fetch(self, label: str = "", unread_only: bool = True) -> list[Message]:
        return await asyncio.to_thread(self._fetch_sync, label, unread_only)

    def _mark_seen_sync(self, uid: str) -> None:
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        try:
            conn.login(self.address, self._password)
            conn.select("INBOX")
            conn.store(uid, "+FLAGS", "\\Seen")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    async def mark_seen(self, uid: str) -> None:
        await asyncio.to_thread(self._mark_seen_sync, uid)
