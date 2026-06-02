"""Logi Conversational Orchestrator — CEO/strategy planning interface.

This is a minimal implementation to support skill-wiring verification.
Full orchestrator implementation will be in Phase 5.
"""
from __future__ import annotations


class LogiAgent:
    """Logi agent — CEO/strategy planning orchestrator.
    
    Minimal implementation for Phase 4 skill wiring verification.
    """
    
    def __init__(self):
        """Initialize Logi agent."""
        self.user_history = {}
    
    def run(self, user_id: int, text: str, notify_callback=None, skill_context: str = "") -> str:
        """Execute Logi orchestration with skill context.

        Args:
            user_id: Telegram user ID
            text: User input text
            notify_callback: Optional callback for status updates
            skill_context: Strategy skill pack context (injected from LOGI_SKILL_CONTEXT)

        Returns:
            Response text
        """
        # Minimal implementation: echo + placeholder
        if not text:
            return "(empty request)"

        # Store in history
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        self.user_history[user_id].append(text)

        # Placeholder response with skill context acknowledgment
        ctx_indicator = " [with strategy context]" if skill_context else " [no context]"
        return f"Logi acknowledged: {text[:100]}{ctx_indicator}"
    
    def clear_history(self, user_id: int) -> None:
        """Clear conversation history for user."""
        if user_id in self.user_history:
            del self.user_history[user_id]
