import os
import uuid


class TelegramAdapter:
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.auto_approve = os.getenv("MVP_AUTO_APPROVE", "false").lower() == "true"
        self._utils = None
        if not dry_run:
            import utils_system as utils

            self._utils = utils

    def request_approval(self, draft_id: str, contact_name: str, kanal: str, text: str) -> dict[str, str]:
        approval_id = f"appr_{uuid.uuid4().hex[:8]}"
        message = (
            f"<b>Freigabe benötigt</b>\n"
            f"Draft: <code>{draft_id}</code>\n"
            f"Approval-ID: <code>{approval_id}</code>\n"
            f"Kontakt: {contact_name} ({kanal})\n\n"
            f"{text[:700]}\n\n"
            f"Antwort mit /approve {approval_id} oder /reject {approval_id}"
        )
        if not self.dry_run and self._utils:
            self._utils.send_telegram(message)
        return {
            "approval_id": approval_id,
            "status": "approved" if self.auto_approve else "pending",
        }

    def fetch_approval_updates(self) -> dict[str, str]:
        """Returns map approval_id -> approved|rejected based on Telegram commands."""
        if self.dry_run or not self._utils:
            return {}
        result: dict[str, str] = {}
        for update in self._utils.check_telegram_updates():
            text = update.get("message", {}).get("text", "").strip()
            if text.startswith("/approve "):
                result[text.split(" ", 1)[1].strip()] = "approved"
            elif text.startswith("/reject "):
                result[text.split(" ", 1)[1].strip()] = "rejected"
        return result

    def send_message(self, kanal: str, text: str) -> bool:
        if self.dry_run:
            return True
        if kanal == "telegram" and self._utils:
            self._utils.send_telegram(text)
            return True
        return False
