#!/usr/bin/env python3
"""Fail-closed validation of physical training data against its manifest."""
import argparse, hashlib, json
from pathlib import Path

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def validate(dataset: Path, manifest: dict) -> dict:
    errors=[]; rows=[]
    if not dataset.exists(): errors.append('physical_file_missing')
    else:
        try: rows=[json.loads(x) for x in dataset.read_text().splitlines() if x.strip()]
        except Exception as e: errors.append(f'jsonl_invalid:{e}')
    actual_hash=digest(dataset) if dataset.exists() else None
    if manifest.get('row_count') != len(rows): errors.append('physical_row_count_manifest_mismatch')
    if manifest.get('dataset_sha256') != actual_hash: errors.append('physical_sha256_manifest_mismatch')
    if manifest.get('admitted_pair_count') != len(rows): errors.append('admitted_pair_count_mismatch')
    ids=[]
    for i,row in enumerate(rows):
        m=row.get('metadata',row)
        if not m.get('pair_id'): errors.append(f'row_{i}_missing_pair_id')
        ids.append(m.get('pair_id'))
        if m.get('approved_for_training') is not True: errors.append(f'row_{i}_not_approved_for_training')
        if not m.get('source_id') and not m.get('source_dataset'): errors.append(f'row_{i}_missing_source_identity')
        if not m.get('source_hash'): errors.append(f'row_{i}_missing_source_hash')
        if not m.get('transformation_method') and not m.get('transformation_version'): errors.append(f'row_{i}_missing_transformation_evidence')
        if not m.get('quality_result') and not m.get('codex_cli_audit'): errors.append(f'row_{i}_missing_quality_evidence')
    if len(ids)!=len(set(ids)): errors.append('duplicate_pair_ids')
    return {'status':'PASS' if not errors else 'FAIL_DATASET_SUMMARY_PHYSICAL_MISMATCH_ALLOWED','valid':not errors,'errors':errors,'row_count':len(rows),'actual_sha256':actual_hash}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('dataset',type=Path); ap.add_argument('manifest',type=Path); args=ap.parse_args()
    print(json.dumps(validate(args.dataset,json.loads(args.manifest.read_text())),indent=2))
    return 0 if validate(args.dataset,json.loads(args.manifest.read_text()))['valid'] else 1
if __name__=='__main__': raise SystemExit(main())
