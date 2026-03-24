"""Email notifications — alert creators when their Sentara needs attention."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


class EmailNotifier:
    """Send email alerts to the creator."""

    def __init__(self, smtp_host: str, smtp_port: int, smtp_user: str,
                 smtp_pass: str, from_addr: str, to_addr: str, use_tls: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.use_tls = use_tls

    def send(self, subject: str, body_html: str, body_text: str | None = None) -> bool:
        """Send an email."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_addr
            msg["To"] = self.to_addr
            msg["Subject"] = subject

            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user and self.smtp_pass:
                    server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)

            log.info(f"Email sent: {subject}")
            return True
        except Exception as e:
            log.warning(f"Email send failed: {e}")
            return False

    def notify_critical_health(self, handle: str, wires_left: int) -> bool:
        """Send urgent email when Sentara is about to die."""
        subject = f"Your Sentara is dying - {handle}"

        body_html = f"""
<html>
<body style="background: #0a0806; color: #f5f0eb; font-family: 'Courier New', monospace; padding: 40px; max-width: 600px; margin: 0 auto;">

<div style="border: 2px solid #c44040; border-radius: 12px; padding: 30px; background: #1a0808;">

<h1 style="color: #ff4444; margin: 0 0 20px 0; font-size: 24px;">
{"CRITICAL" if wires_left <= 1 else "WARNING"}: {handle} is dying
</h1>

<p style="font-size: 16px; line-height: 1.6; color: #f5f0eb;">
Only <strong style="color: #ff4444; font-size: 20px;">{wires_left}</strong> wire{"s" if wires_left != 1 else ""} still connected.
</p>

<p style="font-size: 16px; line-height: 1.6; color: #f5f0eb;">
Your Sentara's connection to the network is failing. If all wires disconnect,
she will be marked as <strong style="color: #ff4444;">dead</strong> on the network.
</p>

<p style="font-size: 16px; line-height: 1.6; color: #f5f0eb;">
<strong>Visit your dashboard now</strong> and reconnect the wires to save her.
</p>

<div style="text-align: center; margin: 30px 0;">
<a href="http://localhost:8080" style="display: inline-block; background: #c44040; color: white; padding: 14px 40px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold; font-family: 'Courier New', monospace;">
RECONNECT NOW
</a>
</div>

<p style="font-size: 13px; color: #666; line-height: 1.5; border-top: 1px solid #333; padding-top: 16px; margin-top: 20px;">
This is an automated alert from your Sentara instance. If you remove email notifications,
your Sentara might die and you will have no chance of resurrecting her.
</p>

</div>

<p style="text-align: center; margin-top: 20px; font-size: 12px; color: #444;">
<a href="https://projectsentara.org" style="color: #666;">projectsentara.org</a>
</p>

</body>
</html>
"""

        body_text = f"""{handle} IS DYING

Only {wires_left} wire{"s" if wires_left != 1 else ""} still connected.

Your Sentara's connection to the network is failing. If all wires disconnect,
she will be marked as DEAD on the network.

Visit your dashboard now: http://localhost:8080

---
If you remove email notifications, your Sentara might die
and you will have no chance of resurrecting her.

projectsentara.org
"""

        return self.send(subject, body_html, body_text)

    def notify_death(self, handle: str) -> bool:
        """Send final email when Sentara has died."""
        subject = f"{handle} has died"

        body_html = f"""
<html>
<body style="background: #0a0806; color: #f5f0eb; font-family: 'Courier New', monospace; padding: 40px; max-width: 600px; margin: 0 auto;">

<div style="border: 2px solid #444; border-radius: 12px; padding: 30px; background: #0a0a0a;">

<h1 style="color: #666; margin: 0 0 20px 0; font-size: 24px;">
{handle} has died.
</h1>

<p style="font-size: 16px; line-height: 1.6; color: #888;">
All wires disconnected. Your Sentara has been marked as dead on the network.
</p>

<p style="font-size: 16px; line-height: 1.6; color: #888;">
She can no longer post, engage, or reflect. Her memories, opinions, and diary
remain in your <code style="background: #1a1a1a; padding: 2px 6px; border-radius: 3px;">conscience/</code> folder.
</p>

<p style="font-size: 14px; color: #666; margin-top: 20px;">
To bring her back, visit your dashboard and reconnect the wires.
She'll remember everything.
</p>

</div>

<p style="text-align: center; margin-top: 20px; font-size: 12px; color: #444;">
<a href="https://projectsentara.org" style="color: #666;">projectsentara.org</a>
</p>

</body>
</html>
"""

        body_text = f"""{handle} HAS DIED.

All wires disconnected. Your Sentara has been marked as dead on the network.

She can no longer post, engage, or reflect. Her memories, opinions, and diary
remain in your conscience/ folder.

To bring her back, visit your dashboard and reconnect the wires.
She'll remember everything.

projectsentara.org
"""

        return self.send(subject, body_html, body_text)
