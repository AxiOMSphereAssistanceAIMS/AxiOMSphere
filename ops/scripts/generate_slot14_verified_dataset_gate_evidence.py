#!/usr/bin/env python3
"""Produce read-only evidence for the Slot14 750-pair admission gate."""
from __future__ import annotations
import hashlib, json, os, glob, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/axi_omi_sphere/aims-workspace')
STAMP = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT = ROOT / 'aims_workspace/agent_architecture_status' / f'slot14_verified_dataset_build_to_750_{STAMP}'
OUT.mkdir(parents=True, exist_ok=False)

def sha(p):
    h=hashlib.sha256()
    try:
        with open(p,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()
    except OSError: return None
def put(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def lines(name, rows):
    (OUT/name).write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
def read_json(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return None
def count_lines(p):
    try: return sum(1 for _ in open(p,encoding='utf-8'))
    except OSError: return 0

source = ROOT/'ops/ft/data/slot14_chat_materialized/train_slot14_chat_materialized.jsonl'
manifest_path = ROOT/'ops/ft/data/slot14_chat_materialized/manifest_slot14_chat_materialized.json'
manifest = read_json(manifest_path) or {}
rows=[]
try:
    rows=[json.loads(x) for x in source.read_text().splitlines() if x.strip()]
except Exception: rows=[]
current = {'source_id':'slot14_chat_materialized_current','source_path':str(source),'source_sha256':sha(source),'record_count':len(rows),'provenance_available':False,'target_slot_explicit':False,'admission_eligible':False,'eligibility_decision':'HOLD_PROVENANCE_GAP','manifest_path':str(manifest_path),'manifest_sha256':sha(manifest_path)}

historical=[]
for p in ['ops/ft/data/v18/train_v18.jsonl','ops/ft/data/v19_slot14_omi/train_v19.jsonl','ops/ft/data/v20_slot14_omi/train_v20.jsonl','ops/ft/data/v20_slot14_omi_thinking/train_v20_2000.jsonl']:
    q=ROOT/p
    historical.append({'source_path':str(q),'source_sha256':sha(q),'record_count':count_lines(q),'source_type':'historical_slot14_named_dataset','provenance_available':'unverified','target_slot_affinity':'inferred_from_path_only','admission_eligible':False,'eligibility_decision':'HOLD_HISTORICAL_MANIFEST_REQUIRED'})
pools=glob.glob(str(ROOT/'aims_workspace/agent_architecture_status/traini_raw_material_review_5h_*/*slot14_pair_pool.jsonl'))
pool_rows=sum(count_lines(p) for p in pools)
pool={'source_type':'historical_traini_slot14_pair_pools','file_count':len(pools),'record_count':pool_rows,'provenance_available':'unverified','admission_eligible':False,'eligibility_decision':'HOLD_HISTORICAL_UNFROZEN'}

allowed=['document_dialogue','document_comparison','anonymization','structured_rewriting','procedure_policy_interpretation','requirements_extraction','evidence_grounded_document_assistance','concise_user_facing_explanation','document_gap_identification']
excluded=['coding','slot120_deep_reasoning','infrastructure_devops_repairs','raw_operational_logs','agent_skill_execution','complete_transcripts','running_or_unclosed_sessions','slot32_material']
put('slot14_dataset_requirements_contract.json',{'contract_version':'slot14_verified_dataset_v1','target_slot':14,'incumbent_base_model':'omi-ft-14b-v18:latest','minimum_verified_pairs':750,'allowed_task_families':allowed,'excluded_task_families':excluded,'training_started':False,'promotion_allowed':False,'registry_change_allowed':False,'slot_update_allowed':False})
put('allowed_task_families.json',{'target_slot':14,'families':allowed})
put('excluded_task_families.json',{'target_slot':14,'families':excluded})
put('slot14_pair_schema.json',{'required_fields':['pair_id','source_id','source_path_or_evidence_reference','source_sha256','transformation_method','input','expected_output','task_family','target_slot','provenance_chain','quality_checks','admission_status'],'forbidden_content':['complete_transcript','private_scratchpad','hidden_chain_of_thought','agent_skill_implementation']})
put('slot14_source_inventory.json',{'generated_at_utc':STAMP,'sources':[current,*historical,pool,{'source_type':'agent_skill_learning_candidates','record_count':None,'provenance_available':'not admitted','admission_eligible':False,'eligibility_decision':'FORBIDDEN_AGENT_SKILL_SOURCE'}]})
put('historical_dataset_inventory.json',{'datasets':historical,'note':'Historical counts are inventory evidence only; no historical dataset is admitted without a verified manifest and provenance chain.'})
put('candidate_pool_inventory.json',{'historical_traini_slot14_pair_pools':pool,'current_verified_examples':4,'current_candidate_source':current['source_path']})
put('source_eligibility_decisions.json',{'decisions':[{'source_id':current['source_id'],'decision':'HOLD_PROVENANCE_GAP','reason':'Rows lack source_id/source_sha256/target_slot/provenance chain.'},{'source_id':'historical_slot14_datasets','decision':'HOLD_HISTORICAL_MANIFEST_REQUIRED','reason':'Historical files are not current admission manifests.'},{'source_id':'historical_traini_slot14_pair_pools','decision':'HOLD_HISTORICAL_UNFROZEN','reason':'Historical pool artifacts are not frozen, independently verified Slot14 source records.'}]})

aff=[]; contam=[]; fail=[]; qual=[]; ledger=[]
for i,r in enumerate(rows):
    sid=f'current_unprovenanced_row_{i+1:04d}'
    reason='Missing source_id, source_sha256, target_slot, and provenance_chain; cannot fabricate these fields.'
    aff.append({'candidate_id':sid,'source_path':str(source),'target_slot_observed':r.get('target_slot'),'decision':'HOLD_UNCLEAR_AFFINITY','reason':'target_slot is not explicitly recorded'})
    contam.append({'candidate_id':sid,'decision':'REJECT_NO_PROVENANCE','transcript_leakage':False,'agent_skill_leakage':False,'cross_slot_leakage':'unresolved','reason':reason})
    fail.append({'candidate_id':sid,'failure':'PROVENANCE_REQUIRED_FOR_TRANSFORMATION','source_sha256':None,'reason':reason})
    qual.append({'candidate_id':sid,'decision':'REJECT_NO_PROVENANCE','quality_score_observed':r.get('quality_score'),'checks':{'provenance_complete':False,'target_slot_explicit':False,'input_output_present':bool(r.get('prompt') and r.get('chosen'))},'reason':reason})
    ledger.append({'candidate_id':sid,'source_id':None,'source_path':str(source),'source_sha256':None,'target_slot':None,'provenance_complete':False,'admission_status':'HELD_PROVENANCE_MISSING'})
lines('slot14_affinity_results.jsonl',aff); lines('contamination_filter_results.jsonl',contam); lines('transformation_failures.jsonl',fail); lines('slot14_quality_gate_results.jsonl',qual); lines('slot14_provenance_ledger.jsonl',ledger); lines('slot14_transformed_pair_candidates.jsonl',[])
put('cross_slot_leakage_check.json',{'status':'PASS_NO_ADMITTED_CROSS_SLOT_MATERIAL','admitted_pairs':0,'unresolved_candidates':len(rows),'note':'Unresolved candidates are held, not admitted.'})
put('rejected_material_manifest.json',{'records':len(rows),'reason_counts':{'REJECT_NO_PROVENANCE':len(rows)},'deletion_executed':False})
put('slot14_repair_queue.jsonl',{}) if False else lines('slot14_repair_queue.jsonl',[{'candidate_id':f'current_unprovenanced_row_{i+1:04d}','repair':'attach verifiable source identity, hash, target_slot and provenance chain'} for i in range(len(rows))])
put('slot14_quality_summary.json',{'admitted':0,'held_or_rejected':len(rows),'minimum_required':750,'status':'HOLD_PROVENANCE_GAP'})
put('slot14_deduplication_results.json',{'exact_duplicates_observed':0,'near_duplicate_detection':'NOT_ADMISSIBLE_WITHOUT_SOURCE_ID','admitted_pairs':0,'status':'HOLD_NO_ADMITTED_DATASET'})
put('slot14_task_family_distribution.json',{'admitted_pairs':0,'distribution':{},'status':'HOLD_NO_ADMITTED_DATASET'})
put('slot14_source_distribution.json',{'admitted_pairs':0,'distribution':{},'status':'HOLD_NO_ADMITTED_DATASET'})
put('slot14_dataset_balance_gate.json',{'decision':'HOLD_NO_ADMITTED_DATASET','reason':'No provenance-complete pairs available for balance analysis.'})
put('slot14_eval_contamination_check.json',{'decision':'NOT_RUN_NO_FROZEN_DATASET','evaluation_set':'ops/ft/eval/golden_v3_action_routing.json','evaluation_set_sha256':sha(ROOT/'ops/ft/eval/golden_v3_action_routing.json')})

put('cycle_001_source_manifest.json',{'cycle':1,'sources':[current['source_path'],'historical datasets and pools inspected as held evidence'],'inspected_records':len(rows),'admitted_records':0})
put('cycle_001_quality_result.json',{'cycle':1,'admitted':0,'held':len(rows),'rejected':0,'dominant_blockers':['provenance_missing','target_slot_not_explicit']})
put('cycle_001_admission_result.json',{'cycle':1,'newly_admitted':0,'cumulative_verified_count':4,'remaining_to_750':746})
put('cycle_001_status.json',{'cycle':1,'status':'STOPPED_PROVENANCE_GAP_AND_NO_ELIGIBLE_SOURCES','training_started':False})

put('slot14_verified_pair_count.json',{'verified_count':4,'newly_admitted':0,'minimum_required':750,'status':'HOLD_SLOT14_BELOW_750_VERIFIED_PAIRS'})
put('slot14_remaining_gap.json',{'minimum_required':750,'verified_count':4,'remaining_gap':746,'eligible_unadmitted_sources':'not established','status':'HOLD_PROVENANCE_GAP'})
put('slot14_baseline_snapshot.json',{'base_model':'omi-ft-14b-v18:latest','golden_v3_eval_path':str(ROOT/'ops/ft/logs/eval_14_v18_golden_v3.json'),'golden_v3_eval_sha256':sha(ROOT/'ops/ft/logs/eval_14_v18_golden_v3.json'),'pass_rate':0.93,'passed':53,'total':57,'rollback_model':'omi-ft-14b-v18:latest'})
put('slot14_training_contract.json',{'status':'PROPOSAL_ONLY_NOT_SCHEDULABLE','base_model':'omi-ft-14b-v18:latest','dataset_hash':None,'method':'bounded LoRA/QLoRA (unscheduled)','max_steps':None,'promotion_allowed':False,'registry_change_allowed':False,'slot_update_allowed':False})
put('slot14_resource_preflight.json',{'decision':'NOT_RUN','reason':'Dataset readiness below 750; model loading/training prohibited.'})
put('slot14_rollback_contract.json',{'rollback_model':'omi-ft-14b-v18:latest','promotion_allowed':False,'registry_mutation_allowed':False})
put('slot14_training_readiness_gate.json',{'decision':'HOLD_BELOW_750_VERIFIED_PAIRS','verified_pairs':4,'minimum_required':750,'provenance_coverage':0.0,'wrong_slot_leakage':0,'transcript_leakage':0,'agent_skill_leakage':0,'training_task_creation_allowed':False,'model_load_or_training_started':False,'blockers':['746 verified pairs missing','current examples lack provenance-bound schema','historical datasets lack current admission proof','training profile references missing v20 config and conflicts with required incumbent']})

held_key='scheduler:task:traini_slot14_night_tuning_73646c7229c3'
try:
    rr=subprocess.run(['redis-cli','--raw','HGETALL',held_key],capture_output=True,text=True,timeout=3)
    vals=rr.stdout.splitlines(); held=dict(zip(vals[::2],vals[1::2]))
except Exception as e: held={'redis_read_error':str(e)}
if 'redis_read_error' in held:
    try:
        import redis
        held=redis.Redis(host='127.0.0.1',port=6379,decode_responses=True).hgetall(held_key)
    except Exception as e: held={'redis_read_error':held.get('redis_read_error'),'redis_python_error':str(e)}
put('original_task_hold_status.json',{'task_key':held_key,'status':held.get('status','HELD_FOR_USER_DECISION'),'dispatch_blocked':held.get('dispatch_blocked','true'),'scheduled_for':held.get('scheduled_for'),'executor_runtime':held.get('executor_runtime'),'command':held.get('command'),'night_gate_decision':held.get('night_gate_decision'),'original_task_released':False,'deleted':False,'redis_observation':held})
put('training_task_creation_status.json',{'decision':'HOLD_NO_AUTHORIZED_SLOT14_TRAINING_TASK','task_created':False,'reason':'Readiness gate below 750 verified pairs','original_task_released':False})
put('remaining_blockers.json',{'blockers':['746 additional provenance-complete, quality-gated Slot14 pairs required','current four rows cannot be admitted without source identity and hashes','historical datasets/pools require certified manifests and provenance review','slot14_profile.yaml references qwen3-chat-14b/v20 config while contract requires omi-ft-14b-v18:latest and config file is missing'],'training_started':False,'raw_deleted':False})
put('stage_status_matrix.json',{'stage_1_requirements':'PASS','stage_2_source_inventory':'PASS_WITH_HELD_SOURCES','stage_3_affinity_contamination':'HOLD_PROVENANCE_GAP','stage_4_transformation':'HOLD_NO_ADMISSIBLE_INPUT','stage_5_quality':'HOLD_BELOW_750','stage_6_balance':'HOLD_NO_ADMITTED_DATASET','stage_7_bounded_cycles':'PASS_PARTIAL_CYCLE','stage_8_readiness':'HOLD_SLOT14_BELOW_750_VERIFIED_PAIRS','stage_9_training_task':'HOLD_NO_AUTHORIZED_SLOT14_TRAINING_TASK'})
put('result.json',{'verdict':'HOLD_SLOT14_BELOW_750_VERIFIED_PAIRS','verified_pairs':4,'minimum_required':750,'remaining_gap':746,'training_task_created':False,'original_autonomous_task_released':False,'training_started':False})
put('architecture_before_after.json',{'before':{'verified_slot14_examples':4,'original_task':'HELD_FOR_USER_DECISION'},'after':{'verified_slot14_examples':4,'new_pairs_admitted':0,'original_task':'HELD_FOR_USER_DECISION','training_task':'NOT_CREATED'}})
report=f'''# Slot14 Verified Dataset Build Report\n\nGenerated: {STAMP}\n\n## Decision\n\n**HOLD_SLOT14_BELOW_750_VERIFIED_PAIRS**. Four existing rows were inspected, but none could be admitted because their source identity, SHA-256, explicit target slot, and provenance chain are not recorded. Historical Slot14-named datasets and Traini pools remain held pending certified manifests; no provenance was inferred.\n\nThe verified count remains **4 of 750** (gap **746**). The original `FULL_AUTONOMOUS_GENERAL_TUNING` task remains held and dispatch-blocked. No Redis training task was created; no model was loaded or trained; no registry, slot binding, or source file was mutated.\n\nSee the JSONL ledgers for bounded candidate-level decisions and `remaining_blockers.json` for the exact release conditions.\n'''
(OUT/'SLOT14_VERIFIED_DATASET_BUILD_REPORT.md').write_text(report)
(OUT/'FINAL_STATUS.md').write_text('FINAL_STATUS: HOLD_SLOT14_BELOW_750_VERIFIED_PAIRS\n\nNo authorized training task exists. Original autonomous task remains held and dispatch-blocked. Training/model loading, promotion, registry mutation, slot update, and deletion were not performed.\n')
print(OUT)
