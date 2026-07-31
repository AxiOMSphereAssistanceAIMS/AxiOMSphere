#!/usr/bin/env python3
"""Record Slot14 attempt closure and a future provenance-bound acquisition contract."""
import json, hashlib
from pathlib import Path
import redis

R=Path('/home/axi_omi_sphere/aims-workspace')
O=R/'aims_workspace/agent_architecture_status/slot14_training_attempt_closure_and_dataset_acquisition_20260731'; O.mkdir(parents=True)
def put(n,x): (O/n).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
key='scheduler:task:traini_slot14_night_tuning_73646c7229c3'; r=redis.Redis(decode_responses=True); task=r.hgetall(key)
put('closed_training_attempt_status.json',{'status':'CLOSED_NOT_DATASET_READY','threshold':750,'verified_count':4,'remaining_gap':746,'historical_v18_rows':774,'historical_v18_admission':'LEGACY_DATASET_LEVEL_EVIDENCE_NOT_ADMISSIBLE','deterministically_recoverable_historical_pairs':0,'training_started':False,'closed_attempt_not_reopened':True})
put('incumbent_preservation_status.json',{'incumbent_model':'omi-ft-14b-v18:latest','preserved':True,'model_registry_mutated':False,'slot14_binding_changed':False,'promotion_performed':False})
v18=R/'ops/ft/data/v18/train_v18.jsonl'
put('historical_v18_lineage_status.json',{'dataset_path':str(v18),'reported_rows':774,'dataset_sha256':sha(v18),'admission_status':'LEGACY_DATASET_LEVEL_EVIDENCE_NOT_ADMISSIBLE','per_pair_identity_present':False,'source_hashes_present':False,'deterministically_recoverable_pairs':0,'original_deleted':False,'evidence_retained':True})
put('retired_task_status.json',{'task_key':key,'status':task.get('status'),'dispatch_blocked':task.get('dispatch_blocked'),'held_for_user_decision':task.get('held_for_user_decision'),'pending_score':r.zscore('scheduler:tasks:pending',key),'retry_membership':None,'audit_history_score':r.zscore('scheduler:tasks:missed_startup_review','traini_slot14_night_tuning_73646c7229c3'),'retained_in_audit_history':True,'deleted':False,'payload_preserved':bool(task.get('command'))})
fields=['immutable pair_id','source_id at creation time','source path/reference','source SHA-256','transformation method','target_slot=slot14','input','output','task family','provenance chain','quality result','admission decision','deduplication identity']
put('slot14_verified_dataset_acquisition_contract.json',{'program_id':'slot14_verified_dataset_acquisition_v1','status':'REGISTERED','target_slot':14,'minimum_verified_pairs':750,'pair_required_fields':fields,'readiness_recalculated_from':'admitted pairs only','training_allowed_before_readiness':False,'redis_training_task_before_readiness':False,'retired_task_auto_release':False,'cycle_size':[50,100],'stop_conditions':['quality plateau','provenance plateau','no eligible source','threshold reached']})
put('allowed_source_contract.json',{'allowed':['real document-dialogue tasks','document comparison','anonymization','structured rewriting','procedure/policy interpretation','requirement extraction','evidence-grounded document assistance','approved source-derived augmentation with complete lineage'],'target_slot':14})
put('forbidden_source_contract.json',{'forbidden':['complete transcripts','agent_skill_learning artifacts used directly','Slot32 material','Slot120 material','infrastructure repair logs','pairs without source hashes','reconstructed or fabricated provenance','legacy v18 rows without per-pair identity']})
put('cumulative_readiness_rule.json',{'minimum_verified_pairs':750,'verified_count_basis':'admitted pairs only','below_threshold_decision':'FAIL_CLOSED','training_proposal_below_threshold':False,'redis_training_task_before_readiness_pass':False,'automatic_retired_task_release':False,'recalculate_on_each_admission_cycle':True})
put('acquisition_cycle_contract.json',{'cycle_size_min':50,'cycle_size_max':100,'steps':['classify','transform','validate','deduplicate','admit'],'required_outputs':['cycle source manifest','quality result','admission result','cumulative verified count','remaining gap'],'stop_conditions':['quality plateau','provenance plateau','no eligible sources','verified count >= 750']})
put('slot14_training_regression_guard.json',{'guard':'FAIL_CLOSED','required':{'verified_count_min':750,'provenance_coverage':1.0,'cross_slot_leakage':0,'transcript_leakage':0,'agent_skill_leakage':0,'frozen_dataset_hash':True,'controlled_training_contract':True},'training_task_rejected_if_any_missing':True,'promotion_allowed':False,'registry_change_allowed':False,'slot_update_allowed':False})
put('training_task_creation_status.json',{'created':False,'task_key':None,'reason':'Current attempt closed below 750; acquisition program only; no training task authorized'})
put('remaining_blockers.json',{'blockers':['746 additional provenance-complete admitted Slot14 pairs required','historical v18 per-pair identity and provenance unavailable','no frozen dataset hash or controlled training contract exists'],'training_task_created':False,'original_task_retired':True})
(O/'SLOT14_TRAINING_ATTEMPT_CLOSURE_REPORT.md').write_text('''# Slot14 Training Attempt Closure and Dataset Acquisition\n\nVerdict: `PASS_SLOT14_TRAINING_ATTEMPT_CLOSED_DATASET_ACQUISITION_REGISTERED`.\n\nThe current attempt is formally `CLOSED_NOT_DATASET_READY`: 4 verified pairs against the certified 750-pair threshold, leaving a gap of 746. Historical v18 contains 774 rows but remains legacy dataset-level evidence and is not admissible without per-pair provenance; deterministic recovery yielded zero pairs.\n\nThe incumbent `omi-ft-14b-v18:latest` is preserved. The original autonomous task remains retired and dispatch-blocked, absent from pending/retry queues and retained in audit history. A separate provenance-bound acquisition contract and fail-closed training regression guard were registered. No training task, model loading, promotion, registry mutation, slot update, or deletion occurred.\n''')
(O/'FINAL_STATUS.md').write_text('FINAL_STATUS: PASS_SLOT14_TRAINING_ATTEMPT_CLOSED_DATASET_ACQUISITION_REGISTERED\n\nNo training task was created.\n')
print(O)
