"""Telegram Alert Service — Real-time notifications for incident orchestration.

Sends alerts to ops team when:
- Critical incidents detected
- Repairs completed/failed
- Training jobs triggered
- Tasks blocked/escalated
"""
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any

import httpx


class TelegramAlertManager:
    """Send alerts to Telegram for operational visibility."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """Initialize Telegram bot.

        Args:
            bot_token: Telegram bot token (env: TELEGRAM_BOT_TOKEN)
            chat_id: Telegram chat ID (env: TELEGRAM_CHAT_ID)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.api_url = "https://api.telegram.org/bot"
        self.enabled = bool(self.bot_token and self.chat_id)

    async def send_status_update(
        self,
        title: str,
        total_tasks: int,
        runnable: int,
        blocked: int,
        success_rate: float,
    ) -> bool:
        """Send project status snapshot."""
        if not self.enabled:
            return False

        message = f"""
🔍 **Project Status Update**

{title}

📊 **Metrics**:
• Total tasks: {total_tasks}
• Runnable: {runnable}
• Blocked: {blocked}
• Success rate: {success_rate:.0f}%

Time: {datetime.utcnow().isoformat()}
"""
        return await self._send_message(message)

    async def send_incident_alert(
        self,
        incident_type: str,
        severity: str,
        service: str,
        error: str,
        incident_id: str,
    ) -> bool:
        """Send critical incident alert."""
        if not self.enabled:
            return False

        emoji = "🚨" if severity == "CRITICAL" else "⚠️"
        message = f"""
{emoji} **{severity} INCIDENT DETECTED**

**Type**: {incident_type}
**Service**: {service}
**Error**: {error}
**Incident ID**: {incident_id}

**Action**: Creating repair task...

Time: {datetime.utcnow().isoformat()}
"""
        return await self._send_message(message)

    async def send_repair_update(
        self,
        status: str,
        repair_id: str,
        fix: str,
        duration_seconds: Optional[int] = None,
    ) -> bool:
        """Send repair execution update."""
        if not self.enabled:
            return False

        emoji = "✅" if status == "succeeded" else "❌"
        duration_str = f"\n⏱️ **Duration**: {duration_seconds}s" if duration_seconds else ""

        message = f"""
{emoji} **REPAIR {status.upper()}**

**Repair ID**: {repair_id}
**Fix Applied**: {fix}{duration_str}

**Next Step**: Training loop triggered...

Time: {datetime.utcnow().isoformat()}
"""
        return await self._send_message(message)

    async def send_escalation_alert(
        self,
        task_id: str,
        task_type: str,
        priority: int,
        deadline_exceeded_seconds: int,
    ) -> bool:
        """Send escalation alert for overdue tasks."""
        if not self.enabled:
            return False

        message = f"""
🔴 **ESCALATION: TASK OVERDUE**

**Task ID**: {task_id}
**Type**: {task_type}
**Priority**: {priority}
**Overdue**: {deadline_exceeded_seconds}s

**Action Required**: Manual intervention may be needed.

Time: {datetime.utcnow().isoformat()}
"""
        return await self._send_message(message)

    async def send_training_triggered(
        self,
        repair_id: str,
        incident_type: str,
        learning_priority: int,
    ) -> bool:
        """Send notification when training is triggered."""
        if not self.enabled:
            return False

        message = f"""
🎓 **TRAINING TRIGGERED**

**Repair ID**: {repair_id}
**Incident Type**: {incident_type}
**Learning Priority**: {learning_priority}

**Process**: Learning loops analyzing pattern...

Time: {datetime.utcnow().isoformat()}
"""
        return await self._send_message(message)

    async def send_model_update(
        self,
        event_type: str,
        model_name: str,
        score: Optional[float] = None,
        verdict: Optional[str] = None,
    ) -> bool:
        """Send model training/evaluation update."""
        if not self.enabled:
            return False

        if event_type == "loop_started":
            message = f"""
🔬 **MODEL EVALUATION LOOP STARTED**

**Model**: {model_name}

**Process**: Baseline vs candidate comparison underway...

Time: {datetime.utcnow().isoformat()}
"""
        elif event_type == "loop_complete":
            emoji = "✅" if verdict == "ACCEPT" else "❌"
            message = f"""
{emoji} **MODEL EVALUATION COMPLETE**

**Model**: {model_name}
**Verdict**: {verdict}

**Action**: {verdict == "ACCEPT" and "Deploying improved model..." or "Reverting to baseline..."}

Time: {datetime.utcnow().isoformat()}
"""
        else:
            message = f"""
📊 **MODEL UPDATE**

**Model**: {model_name}
**Event**: {event_type}
**Score**: {score}

Time: {datetime.utcnow().isoformat()}
"""

        return await self._send_message(message)

    async def _send_message(self, text: str) -> bool:
        """Send message to Telegram."""
        if not self.enabled:
            return False

        try:
            url = f"{self.api_url}{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload)
                return response.status_code == 200
        except Exception:
            return False


# Global instance
_alert_manager: Optional[TelegramAlertManager] = None


async def get_alert_manager() -> TelegramAlertManager:
    """Get or create alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = TelegramAlertManager()
    return _alert_manager
