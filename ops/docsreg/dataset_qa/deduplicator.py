"""PHASE 9 Deduplicator — removes exact, normalized, and near-duplicate examples."""
import hashlib
import re
import unicodedata
from typing import Dict, List, Set, Tuple

from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    DeduplicationResult,
)


# Near-duplicate threshold (Jaccard similarity)
NEAR_DUPLICATE_THRESHOLD = 0.95


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip whitespace, normalize unicode."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two texts using word-level shingles."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class Deduplicator:
    """Removes duplicate training examples using multiple strategies.

    Deduplication levels:
    1. Exact SHA-256 match on output_sha256
    2. Normalized text hash (lowercased, whitespace-collapsed)
    3. Near-duplicate similarity (Jaccard >= 0.95)
    4. Same document_id + same failure_class + same output hash
    """

    def __init__(self, threshold: float = NEAR_DUPLICATE_THRESHOLD):
        self.threshold = threshold

    def deduplicate(self, examples: List[TrainingExample]) -> Tuple[List[TrainingExample], DeduplicationResult]:
        """Remove duplicates, keeping the best variant.

        Returns:
            Tuple of (deduplicated examples, deduplication report)
        """
        if not examples:
            return [], DeduplicationResult(
                total_before=0, total_after=0, duplicates_removed=0,
                exact_duplicates=0, normalized_duplicates=0,
                near_duplicates=0, same_doc_class_output=0,
            )

        total_before = len(examples)
        removed_ids: Set[str] = set()

        # Phase 1: Exact SHA-256 duplicates
        exact_removed = self._remove_exact_duplicates(examples, removed_ids)

        # Phase 2: Normalized text duplicates
        normalized_removed = self._remove_normalized_duplicates(examples, removed_ids)

        # Phase 3: Same document_id + failure_class + output hash
        doc_class_removed = self._remove_doc_class_output_duplicates(examples, removed_ids)

        # Phase 4: Near-duplicates (most expensive, run last)
        near_removed = self._remove_near_duplicates(examples, removed_ids)

        kept = [ex for ex in examples if ex.example_id not in removed_ids]
        kept_ids = [ex.example_id for ex in kept]
        removed_id_list = list(removed_ids)

        return kept, DeduplicationResult(
            total_before=total_before,
            total_after=len(kept),
            duplicates_removed=len(removed_ids),
            exact_duplicates=exact_removed,
            normalized_duplicates=normalized_removed,
            near_duplicates=near_removed,
            same_doc_class_output=doc_class_removed,
            kept_example_ids=kept_ids,
            removed_example_ids=removed_id_list,
        )

    def _remove_exact_duplicates(
        self, examples: List[TrainingExample], removed: Set[str]
    ) -> int:
        """Remove examples with identical output_sha256."""
        count = 0
        seen: Dict[str, TrainingExample] = {}
        for ex in examples:
            if ex.example_id in removed:
                continue
            key = ex.output_sha256
            if key in seen:
                loser = self._pick_loser(seen[key], ex)
                removed.add(loser.example_id)
                if loser.example_id == seen[key].example_id:
                    seen[key] = ex
                count += 1
            else:
                seen[key] = ex
        return count

    def _remove_normalized_duplicates(
        self, examples: List[TrainingExample], removed: Set[str]
    ) -> int:
        """Remove examples with identical normalized repaired_text."""
        count = 0
        seen: Dict[str, TrainingExample] = {}
        for ex in examples:
            if ex.example_id in removed:
                continue
            norm = _normalize_text(ex.repaired_text)
            key = _sha256(norm)
            if key in seen:
                loser = self._pick_loser(seen[key], ex)
                removed.add(loser.example_id)
                if loser.example_id == seen[key].example_id:
                    seen[key] = ex
                count += 1
            else:
                seen[key] = ex
        return count

    def _remove_doc_class_output_duplicates(
        self, examples: List[TrainingExample], removed: Set[str]
    ) -> int:
        """Remove examples with same document_id + failure_class + output hash."""
        count = 0
        seen: Dict[str, TrainingExample] = {}
        for ex in examples:
            if ex.example_id in removed:
                continue
            key = f"{ex.document_id}|{ex.failure_class}|{ex.output_sha256}"
            if key in seen:
                loser = self._pick_loser(seen[key], ex)
                removed.add(loser.example_id)
                if loser.example_id == seen[key].example_id:
                    seen[key] = ex
                count += 1
            else:
                seen[key] = ex
        return count

    def _remove_near_duplicates(
        self, examples: List[TrainingExample], removed: Set[str]
    ) -> int:
        """Remove near-duplicate examples (Jaccard similarity >= threshold)."""
        count = 0
        active = [ex for ex in examples if ex.example_id not in removed]

        # O(n^2) but dataset is small
        for i in range(len(active)):
            if active[i].example_id in removed:
                continue
            for j in range(i + 1, len(active)):
                if active[j].example_id in removed:
                    continue
                sim = _jaccard_similarity(
                    active[i].repaired_text, active[j].repaired_text
                )
                if sim >= self.threshold:
                    loser = self._pick_loser(active[i], active[j])
                    removed.add(loser.example_id)
                    count += 1

        return count

    def _pick_loser(self, a: TrainingExample, b: TrainingExample) -> TrainingExample:
        """Pick the example to remove. Keep the one with better metrics.

        Priority: higher quality_delta > higher data_retention_rate >
        lower data_loss_percentage > newer skill_version.
        """
        if a.quality_delta != b.quality_delta:
            return b if a.quality_delta > b.quality_delta else a
        if a.data_retention_rate != b.data_retention_rate:
            return b if a.data_retention_rate > b.data_retention_rate else a
        if a.data_loss_percentage != b.data_loss_percentage:
            return b if a.data_loss_percentage < b.data_loss_percentage else a
        if a.skill_version != b.skill_version:
            return b if a.skill_version > b.skill_version else a
        # Tie: remove the second one
        return b
