from __future__ import annotations

from ops.pipelines.ai_label_removal.detector import (
    is_ai_related,
    is_ai_related_key,
    is_ai_related_value,
)
from ops.pipelines.ai_label_removal.telegram_handler import (
    detect_ai_label_removal_intent,
)


class TestDetector:
    def test_ai_tool_values_flagged(self):
        for v in ["ChatGPT", "OpenAI GPT-4", "Anthropic Claude", "Midjourney", "Stable Diffusion"]:
            assert is_ai_related_value(v), v

    def test_ai_keys_flagged(self):
        for k in ["AIGenerated", "ai_generation_id", "GeneratedByAI", "provenance", "C2PA", "GrammarlyDocumentId"]:
            assert is_ai_related_key(k), k

    def test_normal_metadata_not_flagged(self):
        for v in ["Jane Engineer", "Finance Department", "EMEA", "Acme Corp", "domain expert"]:
            assert not is_ai_related_value(v), v
        for k in ["Author", "Company", "Department", "Region", "Manager"]:
            assert not is_ai_related_key(k), k

    def test_is_ai_related_combines_name_and_value(self):
        assert is_ai_related("GenerationTool", "Claude")
        assert is_ai_related("AIGenerated", "true")
        assert not is_ai_related("Department", "Finance")


class TestIntent:
    def test_russian_request(self):
        assert detect_ai_label_removal_intent("удали метки ИИ")
        assert detect_ai_label_removal_intent("очисти AI metadata из документа")
        assert detect_ai_label_removal_intent("убери метки ии пожалуйста")

    def test_english_request(self):
        assert detect_ai_label_removal_intent("remove AI labels")
        assert detect_ai_label_removal_intent("please clean AI metadata")
        assert detect_ai_label_removal_intent("AI labels cleanup")

    def test_irrelevant_messages_ignored(self):
        for msg in [
            "сделай отчёт в word",
            "what is the weather today",
            "please summarize this document",
            "remove the second paragraph",
            "",
            None,
        ]:
            assert not detect_ai_label_removal_intent(msg), msg
