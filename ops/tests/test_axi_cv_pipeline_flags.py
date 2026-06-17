"""Политика анонимизации OCR для CV vs прочих документов."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

from axi_cv_pipeline_flags import (  # noqa: E402
    ocr_anonymize_globally_enabled,
    should_run_ocr_anonymize_step,
)


class TestAxiCvPipelineFlags(unittest.TestCase):
    def tearDown(self) -> None:
        for k in (
            "AXI_OCR_ANONYMIZE_ENABLED",
            "AXI_OCR_SKIP_ANONYMIZE_FOR_CV",
        ):
            os.environ.pop(k, None)

    def test_cv_shokk_skips_anon_when_cv_rule_on(self):
        os.environ["AXI_OCR_ANONYMIZE_ENABLED"] = "1"
        os.environ["AXI_OCR_SKIP_ANONYMIZE_FOR_CV"] = "1"
        self.assertFalse(
            should_run_ocr_anonymize_step("Evgeny_Shokk_QMS_AIMS_SME_Expert.docx")
        )

    def test_iso_like_still_anonymizes_when_cv_skip_on(self):
        os.environ["AXI_OCR_ANONYMIZE_ENABLED"] = "1"
        os.environ["AXI_OCR_SKIP_ANONYMIZE_FOR_CV"] = "1"
        self.assertTrue(
            should_run_ocr_anonymize_step("ISO_13705_Fired_heaters.docx")
        )

    def test_global_off_skips_all(self):
        os.environ["AXI_OCR_ANONYMIZE_ENABLED"] = "0"
        os.environ["AXI_OCR_SKIP_ANONYMIZE_FOR_CV"] = "0"
        self.assertFalse(ocr_anonymize_globally_enabled())
        self.assertFalse(should_run_ocr_anonymize_step("ISO_13705_Fired_heaters.docx"))


if __name__ == "__main__":
    unittest.main()
