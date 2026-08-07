"""Development-friendly email backends."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


DEV_MAILBOX_CACHE_KEY = "hrms_dev_last_emails"


class DevMailboxEmailBackend(ConsoleEmailBackend):
    """
    Console backend that also:
    - writes messages under MEDIA_ROOT/dev_mailbox/
    - stores the latest message bodies in cache for the password-reset done page
    """

    def send_messages(self, email_messages):
        messages = list(email_messages or [])
        sent = super().send_messages(messages)

        mailbox_dir = Path(settings.MEDIA_ROOT) / "dev_mailbox"
        mailbox_dir.mkdir(parents=True, exist_ok=True)

        stored = []
        for index, message in enumerate(messages):
            body = message.body or ""
            subject = message.subject or "(no subject)"
            to = ", ".join(message.to or [])
            stored.append({"subject": subject, "to": to, "body": body})

            safe_to = re.sub(r"[^a-zA-Z0-9._-]+", "_", to or "unknown")[:60]
            path = mailbox_dir / f"email_{safe_to}_{index}.txt"
            path.write_text(
                f"To: {to}\nSubject: {subject}\n\n{body}\n",
                encoding="utf-8",
            )

        cache.set(DEV_MAILBOX_CACHE_KEY, stored, timeout=60 * 30)
        return sent


def get_dev_reset_link():
    """Extract the first http(s) reset link from the last outbound email (DEBUG helper)."""
    stored = cache.get(DEV_MAILBOX_CACHE_KEY) or []
    for item in stored:
        match = re.search(r"https?://\S+", item.get("body", ""))
        if match:
            return match.group(0).rstrip(".)>")
    return ""
