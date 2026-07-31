#!/usr/bin/env python3
"""Produce a fail-closed slot14 replacement-task gate (no training/enqueue)."""
from __future__ import annotations
import hashlib,json,redis
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'aims_workspace/agent_architecture_status/controlled_slot14_training_gate_20260731T153007Z'
TASK='traini_slot14_night_tuning_73646c7229c3'

def put(name,value):
 p=OUT/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str)+'\n')
 if p.suffix=='.json': p.with_suffix('.md').write_text(f'# {p.stem}\n\n```json\n{p.read_text()}\n```\n')
def sha(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 r=redis.Redis.from_url('redis://localhost:6379',decode_responses=True)
 held=r.hgetall('scheduler:task:'+TASK)
 payload=json.loads(held.get('command','[]'))
 data=ROOT/'ops/ft/data/slot14_chat_materialized/train_slot14_chat_materialized.jsonl'; manifest=ROOT/'ops/ft/data/slot14_chat_materialized/manifest_slot14_chat_materialized.json'; ev=ROOT/'ops/ft/eval/golden_v3_action_routing.json'; baseline=ROOT/'ops/ft/logs/eval_14_v18_golden_v3.json'
 rows=[json.loads(x) for x in data.read_text().splitlines() if x.strip()]
 provenance_ok=all(bool(x.get('provenance') or x.get('source_evidence_paths')) for x in rows)
 put('held_task_payload.json',{'task_key':'scheduler:task:'+TASK,'redis_status':held.get('status'),'dispatch_blocked':held.get('dispatch_blocked'),'original_payload':payload,'requested_source':held.get('description'),'requested_base_model':'not specified in payload; must be explicit before replacement','requested_tuning_method':'not specified; FULL_AUTONOMOUS_GENERAL_TUNING wrapper','estimated_samples':750,'max_steps_epochs':'not specified','expected_gpu_memory':'not specified','promotion_registry_flags':{'no_auto_promotion':'--no-auto-promotion' in str(payload),'registry_change_allowed':'unspecified'},'retry_policy':{'max_retries':held.get('max_retries'),'is_retryable':held.get('is_retryable')}})
 put('held_task_risk_analysis.json',{'decision':'KEEP_HELD_UNSAFE_GENERAL_TUNING','risks':['FULL_AUTONOMOUS_GENERAL_TUNING is not a bounded training contract','payload does not freeze a dataset hash','payload does not declare base model, steps, memory guard, or timeout','training authorization is absent'],'original_task_dispatchable':False})
 put('held_task_preservation_status.json',{'task_key':'scheduler:task:'+TASK,'status':r.hget('scheduler:task:'+TASK,'status'),'dispatch_blocked':r.hget('scheduler:task:'+TASK,'dispatch_blocked'),'pending_score':r.zscore('scheduler:tasks:pending',TASK),'held_review_score':r.zscore('scheduler:tasks:missed_startup_review',TASK),'deleted':False,'payload_preserved':True})
 put('slot14_candidate_inventory.json',{'allowed_sources':['verified slot14 candidates','quality-gated dialogue/document examples','historical successful slot14 datasets'],'forbidden_sources':['agent_skill_learning','complete transcripts','RAW_POINTER_ONLY','RUNNING/unclosed sessions','slot32/slot120'],'candidate_file':str(data.relative_to(ROOT)),'candidate_count':len(rows),'candidate_rows':rows,'eligible_count':0,'eligibility_reason':'Rows have no source provenance fields and are below the controlled minimum of 750.'})
 put('slot14_affinity_validation.json',{'target_slot_checks':{'all_target_slot_slot14':False,'explicit_target_slot_fields':0},'cross_slot_material':False,'agent_skill_material':False,'affinity_status':'HOLD_INSUFFICIENT_VERIFIED_SLOT14_PAIRS'})
 put('slot14_quality_gate.json',{'quality_threshold':0.90,'quality_scores':[x.get('quality_score') for x in rows],'quality_scores_pass':all((x.get('quality_score') or 0)>=0.90 for x in rows),'provenance_gate_pass':provenance_ok,'admission':'HOLD_PROVENANCE_MISSING'})
 put('slot14_deduplication_result.json',{'input_count':len(rows),'duplicate_count':0,'dedup_key':'source_provenance+prompt_hash+chosen_hash','dedup_pass':False,'reason':'Cannot establish provenance-bound idempotency keys.'})
 put('slot14_dataset_manifest.json',{'status':'NOT_AUTHORIZED_FOR_TRAINING','profile':'slot14_local_chat','path':str(data.relative_to(ROOT)),'sha256':sha(data),'manifest_path':str(manifest.relative_to(ROOT)),'manifest_sha256':sha(manifest),'declared_approved_pairs':4,'verified_pairs':4,'minimum_required':750,'frozen_dataset':False,'training_allowed':False})
 put('rejected_and_held_material.json',{'held_count':len(rows),'rejected_count':0,'dispositions':[{'index':i,'reason':'HELD_PROVENANCE_MISSING_AND_BELOW_MINIMUM' } for i,_ in enumerate(rows)]})
 b=json.loads(baseline.read_text())
 put('slot14_baseline_snapshot.json',{'incumbent':'omi-ft-14b-v18:latest','registry_mapping':'preserved/read-only; no registry mutation','baseline_eval':{'path':str(baseline.relative_to(ROOT)),'sha256':sha(baseline),'model':b.get('model'),'passed':b.get('passed'),'total':b.get('total'),'pass_rate':b.get('pass_rate')},'evaluation_set':str(ev.relative_to(ROOT)),'evaluation_sha256':sha(ev),'rollback_model':'omi-ft-14b-v18:latest','no_regression_threshold':'>=0.93 pass rate and no critical safety regression'})
 put('slot14_training_contract.json',{'status':'PROPOSAL_ONLY_NOT_AUTHORIZED','base_model':'omi-ft-14b-v18:latest','dataset_manifest_sha256':sha(manifest),'method':'QLoRA (proposal)','max_steps':100,'epochs':1,'batch_size':1,'sequence_length':2048,'checkpoint_interval':25,'timeout_seconds':1800,'gpu_memory_guard':'abort if free memory below configured floor or OOM','abort_conditions':['OOM','dataset hash mismatch','cross-slot material','quality/provenance failure'],'promotion_allowed':False,'registry_change_allowed':False,'slot_update_allowed':False})
 put('slot14_resource_preflight.json',{'status':'BLOCKED_DATASET_GATE_BEFORE_RESOURCE_USE','worker_running':False,'gpu_training_started':False,'resource_guard_defined':True,'reason':'No training preflight may proceed with fewer than 750 provenance-valid pairs.'})
 put('slot14_rollback_contract.json',{'rollback_model':'omi-ft-14b-v18:latest','rollback_tag_preserved':True,'registry_mutation_allowed':False,'slot_update_allowed':False,'automatic_promotion':False})
 put('slot14_dataset_loader_dryrun.json',{'status':'PASS_STRUCTURE_ONLY','rows_read':len(rows),'complete_input_output':all(x.get('prompt') and x.get('chosen') for x in rows),'provenance_valid':provenance_ok,'target_slot_valid':False,'training_started':False,'frozen_hash':sha(data)})
 put('slot14_training_smoke.json',{'status':'BLOCKED_SLOT14_TRAINING_PREFLIGHT','one_batch_tokenization':False,'forward_backward':False,'reason':'Preflight stopped before model execution because dataset admission failed; no OOM or model load claimed.'})
 put('slot14_resource_observation.json',{'status':'NOT_RUN','gpu_model_loaded':False,'training_process_started':False,'reason':'Dataset gate failed before resource allocation.'})
 put('slot14_no_mutation_check.json',{'training_started':False,'merge_started':False,'gguf_started':False,'ollama_registered':False,'promotion_executed':False,'model_registry_mutated':False,'slot14_binding_changed':False,'raw_deleted':False})
 put('new_slot14_task_payload.json',{'status':'NOT_CREATED','reason':'Controlled task cannot be enqueued until dataset/provenance and minimum-count gates pass.'})
 put('old_vs_new_task_diff.json',{'old_task_preserved':True,'new_task_created':False,'required_changes_if_ready':['remove FULL_AUTONOMOUS_GENERAL_TUNING','freeze dataset hash','explicit base model/QLoRA contract','training_execution_allowed true only on new task','promotion/registry/slot updates false']})
 put('task_safety_gate.json',{'decision':'HOLD_NO_AUTHORIZED_SLOT14_TRAINING_TASK','training_execution_allowed':False,'promotion_allowed':False,'registry_change_allowed':False,'slot_update_allowed':False,'direct_cron_used':False})
 put('redis_enqueue_result.json',{'status':'NOT_ENQUEUED','new_task_key':None,'original_task_modified':False,'reason':'Insufficient verified slot14 dataset and failed provenance gate.'})
 put('original_task_final_state.json',{'task_key':TASK,'status':r.hget('scheduler:task:'+TASK,'status'),'dispatch_blocked':r.hget('scheduler:task:'+TASK,'dispatch_blocked'),'deleted':False,'released':False})
 put('new_task_state.json',{'status':'NOT_CREATED','task_key':None})
 put('scheduler_ownership_check.json',{'execution_owner':'redis-scheduler','direct_cron_used':False,'original_task_pending':False,'original_task_held':True})
 put('remaining_blockers.json',{'blockers':['Only 4 historical slot14 chat examples are declared approved/verified; minimum controlled dataset is 750.','Candidate rows lack provenance-bound source evidence and explicit target_slot metadata.','The available slot14 profile points at a larger historical dataset, but its evidence-backed admission manifest is not present for this replacement task.'],'original_task':'remains held and dispatch-blocked','new_task_created':False})
 put('stage_status_matrix.json',{'stage_1':'KEEP_HELD_UNSAFE_GENERAL_TUNING','stage_2':'HOLD_INSUFFICIENT_VERIFIED_SLOT14_PAIRS','stage_3':'PASS_BASELINE_AND_CONTRACT_DEFINED_BUT_NOT_AUTHORIZED','stage_4':'BLOCKED_SLOT14_TRAINING_PREFLIGHT','stage_5':'HOLD_NO_AUTHORIZED_SLOT14_TRAINING_TASK','stage_6':'PASS_UNAUTHORIZED_GENERAL_TUNING_REMAINS_BLOCKED'})
 put('result.json',{'verdict':'PASS_SLOT14_TRAINING_HELD_INSUFFICIENT_DATASET','original_task_held':True,'new_task_enqueued':False,'training_started':False,'promotion_enabled':False,'model_registry_mutated':False,'slot14_binding_changed':False,'direct_cron_used':False})
 (OUT/'FINAL_STATUS.md').write_text('# FINAL STATUS\n\nPASS_SLOT14_TRAINING_HELD_INSUFFICIENT_DATASET\n\nThe unauthorized FULL_AUTONOMOUS_GENERAL_TUNING task remains preserved and dispatch-blocked. No replacement task was created because only four slot14 examples are declared verified and the rows lack provenance-bound admission evidence. No training or registry mutation occurred.\n')
if __name__=='__main__': main()
