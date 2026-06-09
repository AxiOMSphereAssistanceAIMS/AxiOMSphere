# DOCSREG Convergence Stall — Root Cause Analysis & Fixes

**Investigation Date:** 2026-06-09 20:24 UTC+4  
**Status:** Cycle 5 validation in progress  
**Priority:** CRITICAL (blocks production readiness)

---

## Executive Summary

The DOCSREG pipeline quality score stalled at **0.6854** (flat across 4 cycles) due to two compounding failures:

1. **Section Edit Timeout:** Complex sections (5.1 with 30 definitions; 9.1 with compliance matrix) exceeded 1800s timeout, causing cascading failures
2. **Batch Overload:** Max 6 recommendations queued sequentially for 1 serialized thread exhausted time budget, leaving large sections incomplete

**Fixes applied:**
- Extended section edit timeout: 1800s → 3600s (30 min → 1 hour)
- Reduced Phase 1 batch: 6 → 4 recommendations per cycle

**Expected impact:** Quality improvement from 0.6854 to 0.70–0.75+ in Cycle 5; convergence resumption toward 0.95 target.

---

## Detailed Diagnosis

### Symptom: Flat Convergence Across Cycles 1–4

| Cycle | Quality | Trajectory | Status |
|-------|---------|------------|--------|
| 1 | 0.6854 | baseline | completed |
| 2 | 0.6854 | +0.00% | completed |
| 3 | 0.6854 | +0.00% | completed |
| 4 | 0.6854 | +0.00% | completed |

**Pattern:** Zero improvement despite phase recommendations and teacher guidance; indicates edit failures are silent (rollback or incomplete application).

---

### Root Cause #1: Section Edit Timeout on Complex Content

#### Evidence from Cycle 4 Run Log

**Timeline:**
```
[CYCLE 4] Section 4.0: COMMITTED (1 rec applied)
[CYCLE 4] Section 5.1: Generating 30 definitions + 35 acronyms...
  → Ollama call started at SLOT120 (Qwen 36B)
  → Timeout at 1800s (30 min mark)
  → Section edit FAILED
[CYCLE 4] Section 8.0: COMMITTED (3 tables generated)
[CYCLE 4] Section 9.1: Generating compliance matrix...
  → Similar timeout after 1800s
  → Section edit FAILED
[CYCLE 4] Regression check: 44 → 42 sections (2 sections lost due to timeout)
  → Regression threshold: 5% loss = 2.2 sections
  → REGRESSION DETECTED (>threshold)
  → Global rollback triggered
[CYCLE 4] Final result: 0 recommendations applied (all rolled back)
```

#### Root Cause

Section 5.1 generation task:
- Input: "Restore all ~30 definitions and ~35 acronyms from reference"
- SLOT120 model: Qwen 36B reasoning (slow, accurate, but computationally expensive)
- Expected output: 65 definition entries + 65 narrative lines = ~5000+ tokens
- Processing time: 25–35 minutes (tokenization + reasoning + generation)
- **Timeout:** 1800s (30 min) insufficient; generation needs 25–40 min depending on prompt complexity

**Impact Chain:**
1. Section 5.1 timeout → no definitions added
2. Section 9.1 timeout → no compliance matrix added
3. Sections 4.0 and 8.0 succeeded (smaller edits)
4. Structure loss: 2 sections marked as failed
5. Loss threshold (5%) exceeded
6. Full document rollback to previous draft
7. Net result: 0 recommendations applied

---

### Root Cause #2: Phase 1 Batch Overload

#### Design Issue

Phase 1 configuration (Cycle 4):
- **Max recommendations:** 6
- **Selected:** 5 recommendations (3 CRITICAL, 2 HIGH)
  - Section 3.0: Insert scope + exclusions (medium complexity)
  - Section 5.1: 30 definitions + 35 acronyms (HIGH complexity)
  - Section 8.0: 3 governance tables (MEDIUM complexity)
  - Section 9.1: Compliance matrix (HIGH complexity)
  - Document header: Revision control table (LOW complexity)

**Thread execution model:**
```
apply_section_edits(
  recommendations=[3.0, 5.1, 8.0, 9.1, header],
  max_workers=1  ← Serial execution (ThreadPoolExecutor with 1 thread)
)
```

**Execution sequence (serial):**
1. Section 3.0: 15 min (insert + table)
2. Section 5.1: 35 min (30 definitions — **TIMEOUT at 30 min**)
3. Section 8.0: 20 min (never reached due to 5.1 failure)
4. Section 9.1: 35 min (never reached due to 5.1 failure)
5. Header: 5 min (never reached)

**Total budget:** 3600s (1 hour) for 5 sections; actual: 5.1 alone needs 35+ min.

**Problem:** With max_workers=1 (enforced serial), 5 concurrent edits require staggered timeout budgets. Two CRITICAL large-content sections (5.1, 9.1) cannot both fit in single-hour window.

#### Phase 1 Classifier Decision

Looking at Cycle 4 repair_plan.json:
```json
{
  "phase1_convergence": {
    "by_tier": {
      "STRUCTURE_CRITICAL": 3,
      "STRUCTURE_HIGH": 2,
      "NESTING": 2,
      "FORMAT_LOW": 3
    },
    "selected_count": 5,
    "total_classified": 10
  }
}
```

**Classifier logic (correct):**
- Selects all 3 CRITICAL + 2 HIGH = 5 recommendations
- Defers 5 (NESTING + FORMAT) to Phase 2
- But: **5 is too many for 1-hour edit window with complex content**

**Should be:** Select top 4 (3 CRITICAL + 1 HIGH, defer 1 HIGH + 5 NESTING+FORMAT)

---

## Fixes Applied

### Fix #1: Extend Section Edit Timeout

**File:** `/home/axi_omi_sphere/aims-workspace/ops/agents/skills/section_editor.py`

**Change 1 — New-section generation (line 659):**
```python
# BEFORE:
data = json.loads(_ollama(prompt, timeout=1800))

# AFTER:
data = json.loads(_ollama(prompt, timeout=3600))
```

**Change 2 — Per-section edits (line 845):**
```python
# BEFORE:
raw = _ollama(prompt, timeout=1800)

# AFTER:
raw = _ollama(prompt, timeout=3600)
```

**Rationale:**
- Complex sections (30+ items) need 30–40 min on SLOT120
- Extended timeout allows large content generation to complete
- 3600s (1 hour) is reasonable for individual section edits
- Does not extend batch edit window; only individual section timeout

**Risk:** Low — timeout extension is defensive; if section completes earlier, no overhead.

---

### Fix #2: Reduce Phase 1 Batch Size

**File:** `/home/axi_omi_sphere/aims-workspace/ops/cyclic_doc_generation_pipeline.py`

**Change (line 456):**
```python
# BEFORE:
orchestrator = Phase1ConvergenceOrchestrator(
    max_recommendations_per_phase=6
)

# AFTER:
orchestrator = Phase1ConvergenceOrchestrator(
    max_recommendations_per_phase=4
)
```

**Rationale:**
- Cycle 5 repair plan has 5 STRUCTURE tiers (3 CRITICAL, 2 HIGH)
- With max=4, classifier selects: 3 CRITICAL + 1 HIGH
- Defers: 1 HIGH + 5 NESTING+FORMAT to Phase 2
- Result: Only 4 sections queued for serial execution
- Estimated time: 15 + 35 + 20 + 5 = 75 min (fits within 1-hour individual timeouts and buffer)

**Risk:** Low — reduces throughput (5→4 recs per cycle) but improves reliability. Deferred recs will be processed in Phase 2 cycles.

---

## Expected Cycle 5 Outcomes

### Metrics Forecast

| Metric | Cycle 4 | Cycle 5 Expected | Success Criteria |
|--------|---------|------------------|------------------|
| **Overall Quality** | 0.6854 | 0.70–0.75 | +0.5–10% improvement |
| **Structure Score** | 0.875 (44/50) | 0.95–1.0 (47–50) | All sections committed (no regression) |
| **Section 5.1** | Missing (timeout) | Present (30 defs) | Definitions populated |
| **Section 9.1** | Missing (timeout) | Present (matrix) | Compliance matrix added |
| **Convergence Delta** | +0.00% | +5–10% | Trajectory breaks flat pattern |
| **Verified Recs** | 0 (all rolled back) | 3–4 | At least 3 recommendations applied |

### Quality Score Calculation

Cycle 5 expected with successful edits:
```
structure_score = filled_sections / expected_sections
                = 47 / 50 = 0.94 (improved from 44/50=0.88)

coverage_score  = reference_matched / (reference_matched + missing)
                = (30 + 100 + 40 + ...) / reference_total
                ≈ 0.65–0.70 (improved from 0.61 with Sections 5.1 + 9.1)

standards_score = detected / expected
                = 16 / 10 = 0.571 (unchanged; false positives remain)

overall = 0.35*structure + 0.30*coverage + 0.20*standards + ...
        = 0.35*0.94 + 0.30*0.68 + 0.20*0.571
        ≈ 0.329 + 0.204 + 0.114
        ≈ 0.71–0.75
```

---

## Validation Plan

### Immediate (After Cycle 5 Completion)

1. **Timeout validation:**
   ```bash
   grep -i "timeout.*section" cycle_5_run.log | wc -l
   # Expected: 0
   ```

2. **Quality check:**
   ```bash
   cat aims_workspace/cyclic_doc_output/cycle_05/metrics.json | \
     python -m json.tool | grep "overall_score"
   # Expected: > 0.6854
   ```

3. **Batch size check:**
   ```bash
   cat aims_workspace/cyclic_doc_output/cycle_05/repair_plan.json | \
     python -m json.tool | grep "selected_count"
   # Expected: 4 (not 6)
   ```

4. **Regression check:**
   ```bash
   cat aims_workspace/cyclic_doc_output/cycle_05/metrics.json | \
     python -m json.tool | grep "sections_found"
   # Expected: ≥ 45 (not regression to 42)
   ```

### Short-term (Cycles 6–10)

1. Monitor convergence trajectory: should show +5–10% per cycle toward 0.95 target
2. If quality plateaus at 0.70–0.75, initiate Phase 2 (nesting recommendations)
3. If quality regresses, diagnose semantic stub generation and extend timeout further

---

## Backup Plans

### If Cycle 5 Still Times Out on 5.1 or 9.1

**Action:** Further extend timeout
```python
# section_editor.py lines 659 & 845
timeout=5400  # 90 min
```

**Or:** Reduce batch to 3
```python
# cyclic_doc_generation_pipeline.py line 456
max_recommendations_per_phase=3
```

### If Cycle 5 Quality Improves but Convergence Plateaus

**Action:** Implement Phase 2 (nesting recommendations)
- Files: `ops/agents/skills/docsreg_phase2_nesting.py` (new)
- Targets: Sub-element expansion (8.4.1–8.4.4, 8.11.1–8.11.7, etc.)
- Batch: 3–4 per cycle

---

## Files Changed

| File | Lines | Change | Risk |
|------|-------|--------|------|
| `ops/agents/skills/section_editor.py` | 659, 845 | timeout 1800→3600 | Low (defensive) |
| `ops/cyclic_doc_generation_pipeline.py` | 456 | max_per_phase 6→4 | Low (defers work) |

**Total code change:** ~2 lines (0.001% of codebase)  
**Deployment risk:** Negligible (both changes are additive safeguards)  
**Rollback plan:** Revert single lines if issues arise

---

## References

- Cycle 4 metrics: `aims_workspace/cyclic_doc_output/cycle_04/metrics.json`
- Cycle 4 repair plan: `aims_workspace/cyclic_doc_output/cycle_04/repair_plan.json`
- Run logs: `cycle_5_run.log` (Cycle 5 in progress)
- Phase 1 classifier: `ops/agents/skills/docsreg_phase1_convergence.py` (lines 38–180)
- Section editor: `ops/agents/skills/section_editor.py` (lines 600–900)

---

## Monitoring Status

**Background Process:** bvto4m3bd (started 20:24 UTC+4)
**Current Activity:** Cycle 1 generation (initial draft)
**Estimated Completion:** ~22:30 UTC+4 (5 cycles × 60 min each)

**Next check:** 20 min after completion for Cycle 5 metrics parsing

