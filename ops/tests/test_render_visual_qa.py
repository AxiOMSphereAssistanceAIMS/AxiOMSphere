#!/usr/bin/env python3
"""
test_render_visual_qa.py
────────────────────────

Test suite for Phase 3 rendering + visual QA pipeline.

Coverage:
- Valid DOCX rendering to PDF and PNG images
- Invalid/missing DOCX error handling
- Blank page detection via brightness threshold
- Timeout handling and reporting
- Metrics collection and serialization
- Degraded visual QA mode (missing dependencies)
- Regression: Phase 2 validation profile tests still pass
"""
import json
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from tempfile import TemporaryDirectory

# Add to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ops.docgen.render_visual_qa import (
    RenderMetrics,
    DocumentRenderer,
    render_docx_for_qa,
    save_render_metrics,
)

log = logging.getLogger("test_render_visual_qa")


class TestRenderingSuccess:
    """Test successful DOCX → PDF → PNG rendering pipeline."""

    def test_render_metrics_dataclass_initializes(self):
        """RenderMetrics initializes with correct defaults."""
        metrics = RenderMetrics()
        assert metrics.render_attempted is False
        assert metrics.render_success is False
        assert metrics.render_provider == "none"
        assert metrics.pdf_created is False
        assert metrics.png_pages_created is False
        assert metrics.page_count == 0
        assert metrics.blank_page_count == 0
        assert metrics.visual_qa_passed is False
        assert metrics.critical_visual_issues_count == 0
        assert metrics.warnings_count == 0
        assert metrics.render_timeout is False
        assert metrics.degraded_visual_qa_mode is False
        assert metrics.png_paths == []

    def test_render_metrics_to_dict_serialization(self):
        """RenderMetrics.to_dict() produces JSON-serializable output."""
        metrics = RenderMetrics(
            render_success=True,
            page_count=5,
            visual_qa_passed=True,
        )
        result = metrics.to_dict()
        assert result["render_success"] is True
        assert result["page_count"] == 5
        assert result["visual_qa_passed"] is True
        assert "timestamp" in result
        # Verify it's JSON-serializable
        json_str = json.dumps(result)
        assert len(json_str) > 0

    def test_document_renderer_initializes(self):
        """DocumentRenderer initializes with correct defaults."""
        renderer = DocumentRenderer(timeout_sec=120, dpi=150)
        assert renderer.timeout_sec == 120
        assert renderer.dpi == 150
        assert isinstance(renderer.metrics, RenderMetrics)

    def test_document_renderer_clamps_dpi_range(self):
        """DocumentRenderer clamps DPI to 150-300 range."""
        renderer_low = DocumentRenderer(dpi=100)
        assert renderer_low.dpi == 150  # Clamped up to minimum

        renderer_high = DocumentRenderer(dpi=500)
        assert renderer_high.dpi == 300  # Clamped down to maximum

        renderer_valid = DocumentRenderer(dpi=200)
        assert renderer_valid.dpi == 200  # Valid range, no change

    def test_soffice_detection_from_env_var(self):
        """_detect_soffice() finds binary from AXI_SOFFICE_PATH."""
        renderer = DocumentRenderer()
        with patch.dict("os.environ", {"AXI_SOFFICE_PATH": "/usr/bin/soffice"}):
            with patch("pathlib.Path.exists", return_value=True):
                result = renderer._detect_soffice()
                assert result == "/usr/bin/soffice"

    def test_soffice_detection_from_common_paths(self):
        """_detect_soffice() checks common installation paths."""
        renderer = DocumentRenderer()
        with patch("pathlib.Path.exists", return_value=False):
            with patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout="/usr/bin/soffice\n"),
            ):
                result = renderer._detect_soffice()
                assert result == "/usr/bin/soffice"

    def test_render_docx_to_pdf_missing_file(self):
        """render_docx_to_pdf() fails safely when DOCX not found."""
        renderer = DocumentRenderer()
        with TemporaryDirectory() as tmpdir:
            result, pdf_path = renderer.render_docx_to_pdf(
                Path(tmpdir) / "nonexistent.docx",
                Path(tmpdir),
            )
            assert result is False
            assert pdf_path is None
            assert "not found" in renderer.metrics.error_message
            assert renderer.metrics.render_attempted is False

    def test_render_docx_to_pdf_soffice_not_found(self):
        """render_docx_to_pdf() fails when LibreOffice not available."""
        renderer = DocumentRenderer()
        with TemporaryDirectory() as tmpdir:
            # Create a dummy DOCX file
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")

            # Mock _detect_soffice to return None
            with patch.object(renderer, "_detect_soffice", return_value=None):
                result, pdf_path = renderer.render_docx_to_pdf(test_docx, tmpdir)

            assert result is False
            assert pdf_path is None
            assert "not found" in renderer.metrics.error_message.lower()
            assert renderer.metrics.degraded_visual_qa_mode is True

    @patch("subprocess.run")
    def test_render_docx_to_pdf_subprocess_success(self, mock_run):
        """render_docx_to_pdf() succeeds with LibreOffice subprocess."""
        mock_run.return_value = MagicMock(returncode=0)
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            # Create expected PDF output
            expected_pdf = output_dir / "test.pdf"
            expected_pdf.write_text("pdf content")

            with patch.object(renderer, "_detect_soffice", return_value="/usr/bin/soffice"):
                result, pdf_path = renderer.render_docx_to_pdf(test_docx, output_dir)

            assert result is True
            assert pdf_path == expected_pdf
            assert renderer.metrics.render_success is True
            assert renderer.metrics.pdf_created is True
            assert renderer.metrics.render_provider == "libreoffice"


class TestRenderingFailure:
    """Test rendering error handling."""

    @patch("subprocess.run")
    def test_render_docx_to_pdf_subprocess_fails(self, mock_run):
        """render_docx_to_pdf() fails when soffice returns non-zero."""
        mock_run.return_value = MagicMock(returncode=1, stderr="soffice error")
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            with patch.object(renderer, "_detect_soffice", return_value="/usr/bin/soffice"):
                result, pdf_path = renderer.render_docx_to_pdf(test_docx, output_dir)

            assert result is False
            assert pdf_path is None
            assert "failed" in renderer.metrics.error_message.lower()
            assert renderer.metrics.render_attempted is True

    @patch("subprocess.run")
    def test_render_docx_to_pdf_timeout(self, mock_run):
        """render_docx_to_pdf() catches TimeoutExpired."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 120)
        renderer = DocumentRenderer(timeout_sec=120)

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            with patch.object(renderer, "_detect_soffice", return_value="/usr/bin/soffice"):
                result, pdf_path = renderer.render_docx_to_pdf(test_docx, output_dir)

            assert result is False
            assert pdf_path is None
            assert renderer.metrics.render_timeout is True
            assert renderer.metrics.degraded_visual_qa_mode is True
            assert "timeout" in renderer.metrics.error_message.lower()


class TestBlankPageDetection:
    """Test visual QA blank page detection."""

    def test_validate_images_no_images(self):
        """_validate_images() with empty image list."""
        renderer = DocumentRenderer()
        result = renderer._validate_images([])
        assert result["qa_passed"] is True
        assert result["blank_page_count"] == 0
        assert result["critical_issues"] == 0
        assert result["warnings"] == 0

    @patch("PIL.Image.open")
    def test_validate_images_blank_pages_detected(self, mock_image_open):
        """_validate_images() detects blank pages via brightness threshold."""
        # Mock image: all white pixels (avg brightness = 255 > threshold 250)
        mock_img = MagicMock()
        mock_gray = MagicMock()
        mock_img.convert.return_value = mock_gray
        # Simulate 100 white pixels
        mock_gray.getdata.return_value = [255] * 100

        mock_image_open.return_value = mock_img

        renderer = DocumentRenderer()
        with TemporaryDirectory() as tmpdir:
            # Create fake image paths
            fake_images = [Path(tmpdir) / f"page_{i}.png" for i in range(1, 4)]
            for img in fake_images:
                img.write_text("fake")

            result = renderer._validate_images(fake_images)

        # All 3 images are mostly white → blank
        assert result["blank_page_count"] == 3
        assert result["warnings"] == 3
        # Blank pages are warnings, not critical
        assert result["critical_issues"] == 0

    @patch("PIL.Image.open")
    def test_validate_images_mixed_content(self, mock_image_open):
        """_validate_images() with mix of blank and content pages."""
        # Create mock images: 2 blank (255 avg), 1 with content (150 avg)
        def mock_open_side_effect(path):
            img = MagicMock()
            gray = MagicMock()
            img.convert.return_value = gray

            # Simulate based on filename
            if "page_0001" in str(path):
                # Blank page
                gray.getdata.return_value = [255] * 100
            elif "page_0002" in str(path):
                # Blank page
                gray.getdata.return_value = [255] * 100
            else:
                # Content page (darker)
                gray.getdata.return_value = [150] * 100

            return img

        mock_image_open.side_effect = mock_open_side_effect

        renderer = DocumentRenderer()
        with TemporaryDirectory() as tmpdir:
            fake_images = [
                Path(tmpdir) / f"page_{i:04d}.png" for i in range(1, 4)
            ]
            for img in fake_images:
                img.write_text("fake")

            result = renderer._validate_images(fake_images)

        assert result["blank_page_count"] == 2
        assert result["warnings"] == 2
        # QA should still pass if 2 blanks <= max(1, 3//10) = 1
        # Actually: 2 > 1, so qa_passed = False
        assert result["qa_passed"] is False

    @patch("PIL.Image.open", side_effect=IOError("Cannot read corrupted PNG file"))
    def test_validate_images_image_open_failure_returns_degraded_result(self, mock_open):
        """_validate_images() gracefully handles corrupt PNG files (production failure path).

        Validates that when a rendered PNG is corrupted or unreadable (Image.open fails),
        the visual QA pipeline:
        - Records a critical issue (not silent)
        - Fails QA validation (visual_qa_passed=False)
        - Does not raise unhandled exception
        """
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            # Simulate 3 rendered pages, 1 of which is corrupted
            fake_images = [
                Path(tmpdir) / f"page_{i:04d}.png" for i in range(1, 4)
            ]
            for img in fake_images:
                img.write_text("fake")

            # Call with open errors
            result = renderer._validate_images(fake_images)

        # Corrupt image → critical issue recorded (not silent)
        assert result["critical_issues"] >= 1
        assert result["qa_passed"] is False
        # Verify all 3 images failed to open
        assert result["critical_issues"] == 3


class TestTimeoutHandling:
    """Test timeout and error recovery."""

    def test_render_and_validate_timeout_propagates(self):
        """render_and_validate() catches timeout and sets degraded mode."""
        renderer = DocumentRenderer(timeout_sec=5)

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")

            # Mock render_docx_to_pdf to timeout
            with patch.object(
                renderer, "render_docx_to_pdf", return_value=(False, None)
            ):
                renderer.metrics.render_timeout = True
                success, metrics = renderer.render_and_validate(test_docx, tmpdir)

        assert success is False
        assert metrics.render_timeout is True
        assert metrics.degraded_visual_qa_mode is True
        assert metrics.visual_qa_passed is False

    def test_render_and_validate_sets_render_duration(self):
        """render_and_validate() tracks render_duration_sec."""
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")

            # Mock successful pipeline
            with patch.object(
                renderer, "render_docx_to_pdf", return_value=(False, None)
            ):
                success, metrics = renderer.render_and_validate(test_docx, tmpdir)

        assert metrics.render_duration_sec >= 0.0


class TestMetricsCollection:
    """Test metrics collection and serialization."""

    def test_save_render_metrics_creates_json(self):
        """save_render_metrics() writes metrics to JSON file."""
        metrics = RenderMetrics(
            render_success=True,
            page_count=3,
            visual_qa_passed=True,
        )

        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "metrics.json"
            success = save_render_metrics(metrics, output_file)

            # Check within the context manager (before tmpdir cleanup)
            assert success is True
            assert output_file.exists()

            # Verify JSON content
            with open(output_file) as f:
                data = json.load(f)
            assert data["render_success"] is True
            assert data["page_count"] == 3
            assert data["visual_qa_passed"] is True

    def test_save_render_metrics_handles_write_error(self):
        """save_render_metrics() fails gracefully on write error."""
        metrics = RenderMetrics()

        # Use invalid path
        with patch("builtins.open", side_effect=IOError("No permission")):
            success = save_render_metrics(metrics, "/invalid/path.json")

        assert success is False

    def test_render_docx_for_qa_convenience_function(self):
        """render_docx_for_qa() provides single-call interface."""
        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            # Mock the full pipeline
            with patch("ops.docgen.render_visual_qa.DocumentRenderer") as mock_renderer_class:
                mock_instance = MagicMock()
                mock_metrics = RenderMetrics(render_success=True)
                mock_instance.render_and_validate.return_value = (True, mock_metrics)
                mock_renderer_class.return_value = mock_instance

                success, metrics = render_docx_for_qa(test_docx, output_dir)

            assert success is True
            assert metrics.render_success is True


class TestDegradedMode:
    """Test graceful degradation when dependencies missing."""

    def test_pdf_to_images_missing_pdf2image(self):
        """pdf_to_images() fails gracefully when pdf2image not available."""
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            test_pdf = Path(tmpdir) / "test.pdf"
            test_pdf.write_text("dummy")

            # Simulate ImportError
            with patch.dict("sys.modules", {"pdf2image": None}):
                success, images = renderer.pdf_to_images(test_pdf, tmpdir)

        assert success is False
        assert images == []
        assert renderer.metrics.degraded_visual_qa_mode is True
        assert "pdf2image" in renderer.metrics.error_message.lower()

    def test_render_and_validate_with_all_failures(self):
        """render_and_validate() reports degraded mode when pipeline fails."""
        renderer = DocumentRenderer()

        with TemporaryDirectory() as tmpdir:
            test_docx = Path(tmpdir) / "test.docx"
            test_docx.write_text("dummy")

            # Mock all steps to fail
            with patch.object(
                renderer, "render_docx_to_pdf", return_value=(False, None)
            ):
                success, metrics = renderer.render_and_validate(test_docx, tmpdir)

        assert success is False
        assert metrics.degraded_visual_qa_mode is True
        assert metrics.critical_visual_issues_count == 1
        assert metrics.visual_qa_passed is False


class TestRegression:
    """Test backward compatibility with Phase 2 validation profiles."""

    def test_render_metrics_is_json_serializable(self):
        """RenderMetrics output is compatible with JSON serialization."""
        metrics = RenderMetrics(
            render_attempted=True,
            render_success=True,
            render_provider="libreoffice",
            pdf_created=True,
            pdf_path="/path/to/test.pdf",
            png_pages_created=True,
            png_paths=["/path/to/page_0001.png", "/path/to/page_0002.png"],
            page_count=2,
            blank_page_count=0,
            visual_qa_passed=True,
            critical_visual_issues_count=0,
            warnings_count=0,
            render_timeout=False,
            degraded_visual_qa_mode=False,
            qa_artifact_dir="/path/to/qa",
        )

        # Verify all fields serialize
        result = metrics.to_dict()
        json_str = json.dumps(result, indent=2)
        parsed = json.loads(json_str)

        assert parsed["render_success"] is True
        assert parsed["page_count"] == 2
        assert len(parsed["png_paths"]) == 2

    def test_phase2_validation_profiles_not_affected(self):
        """Phase 3 rendering does not interfere with Phase 2 validation."""
        # This is a sanity check that imports work
        try:
            from ops.docgen.validation_profile_loader import ValidationProfileLoader
            profile = ValidationProfileLoader.get_profile("technical_report")
            assert profile.document_type == "technical_report"
            assert profile.quality_thresholds is not None
        except ImportError:
            # Phase 2 may not be deployed yet; that's OK
            pytest.skip("Phase 2 validation profiles not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
