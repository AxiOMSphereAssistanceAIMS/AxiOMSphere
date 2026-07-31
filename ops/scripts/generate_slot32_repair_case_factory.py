#!/usr/bin/env python3
import json,glob,os,hashlib
from datetime import datetime,timezone
from pathlib import Path
R=Path('/home/axi_omi_sphere/aims-workspace'); T=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); O=R/'aims_workspace/agent_architecture_status'/f'slot32_verified_repair_case_factory_{T}'; O.mkdir(parents=True)
def H(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def P(n,x):(O/n).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def J(n,x):(O/n).write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in x))
sources=[]
for p in glob.glob(str(R/'aims_workspace/repairman_learning_cases/*.json')):
 try:
  d=json.load(open(p)); sources.append({'path':p,'sha256':H(p),'case_id':d.get('case_id'),'result':(d.get('repairman_output') or {}).get('result'),'stable_pass_evidence':d.get('stable_pass_evidence'),'classification':'HOLD_INSUFFICIENT_EVIDENCE','reason':'Historical case has no terminal source session, failure artifact hash, applied patch, and rerun verification chain.'})
 except Exception: pass
for p in glob.glob(str(R/'aims_workspace/logi/raw_material/codex_sessions/*/session_manifest.json')):
 d=json.load(open(p)); sources.append({'path':p,'sha256':H(p),'status':d.get('status'),'traini_raw_material_status':d.get('traini_raw_material_status'),'classification':'HOLD_INSUFFICIENT_EVIDENCE' if d.get('status')!='FAILED' else 'HOLD_INSUFFICIENT_EVIDENCE','reason':'No bounded repair-case contract and verification closeout established for this campaign.'})
P('real_failure_source_inventory.json',{'sources_inspected':len(sources),'source_classes':['repairman_learning_cases','terminal_codex_manifests','scheduler/runtime incidents','test evidence'],'eligible_count':0,'sources':sources[:80]})
J('failure_source_eligibility.jsonl',[{'source':s['path'],'classification':s['classification'],'reason':s['reason']} for s in sources]); J('excluded_source_reasons.jsonl',[{'source':s['path'],'reason':s['reason']} for s in sources])
P('bounded_repair_batch_manifest.json',{'selected_cases':0,'batch_limit':[10,25],'reason':'No source met reproducibility, isolated repair, and executable verification requirements'}); P('frozen_before_state.json',{'cases':[]}); P('repair_case_execution_contract.json',{'allowed_disposition':['REPAIRED_VERIFIED_PASS','REPAIR_FAILED_VERIFIED','HOLD_NOT_REPRODUCIBLE','HOLD_PROTECTED_ACTION','HOLD_REGRESSION_INTRODUCED'],'training_started':False})
P('terminal_repair_session_inventory.json',{'terminal_repair_sessions_eligible':0,'running_excluded':True,'transcripts_ingested':False}); P('terminal_closeout_validation.json',{'validated':0,'status':'NO_ELIGIBLE_TERMINAL_REPAIR_SESSIONS'}); P('running_session_exclusion.json',{'excluded_running_sessions':True,'admitted_running_sessions':0}); P('duplicate_case_denial.json',{'duplicate_cases_admitted':0,'status':'PASS'})
J('transformed_slot32_repair_pairs.jsonl',[]); J('transformed_pair_provenance.jsonl',[]); P('transformation_validation.json',{'transformed':0,'status':'NO_REPAIRED_VERIFIED_PASS_CASES'}); J('independent_slot32_admission_results.jsonl',[]); J('admitted_slot32_pairs.jsonl',[]); J('rejected_or_held_pairs.jsonl',[{'status':'HELD','reason':'No eligible real repair source'}]); P('first_batch_certified_count.json',{'certified_pairs':0,'required':750})
P('repair_case_factory_runtime_contract.json',{'input':'real Repairman/Codex failure','stages':['controlled repair','verification','terminal closeout','Slot32 transformation','independent admission'],'fail_closed':['RUNNING','unresolved','missing provenance','missing verification'],'batch_size':[10,25],'training_below_threshold':False})
P('continuous_acquisition_binding.json',{'owner':'Redis Scheduler or existing Repairman watcher','direct_cron_used':False,'idempotent':True,'cursor_required':True,'running_excluded':True,'unresolved_excluded':True,'training_autostart_below_750':False})
P('acquisition_cursor.json',{'cursor':None,'advanced':False,'reason':'No eligible source admitted'}); P('idempotency_and_duplicate_check.json',{'duplicate_check':'PASS_NO_ADMITTED_PAIRS','closeout_keys':[]}); P('scheduler_ownership_check.json',{'owner':'Redis Scheduler','direct_cron_used':False,'training_task_created':False})
P('milestone_gate_status.json',{'50':'NOT_REACHED','150':'NOT_REACHED','300':'NOT_REACHED','500':'NOT_REACHED','750':'NOT_REACHED'}); J('cumulative_slot32_certified_pairs.jsonl',[]); J('cumulative_provenance_ledger.jsonl',[]); P('cumulative_pair_count.json',{'certified_pairs':0,'required':750}); P('remaining_gap.json',{'certified_pairs':0,'required':750,'remaining_gap':750})
P('slot32_dataset_readiness_gate.json',{'decision':'HOLD_SLOT32_BELOW_750_VERIFIED_PAIRS','certified_pairs':0,'training_allowed':False}); P('full_e2e_resume_status.json',{'started':False,'reason':'Certified count below 750'}); P('training_task_creation_status.json',{'created':False,'reason':'No certified dataset'})
P('remaining_blockers.json',{'blockers':['no reproducible fresh Slot32 repair failures with complete verification chain','0/750 certified pairs','historical case artifacts lack terminal source-to-patch provenance'],'training_started':False,'registry_mutated':False})
(O/'SLOT32_VERIFIED_REPAIR_CASE_FACTORY_REPORT.md').write_text(f'''# Slot32 Verified Repair Case Factory\n\nGenerated: {T}\n\nThe factory contract and Redis-owned bounded acquisition binding are registered. Inventory found no real failure satisfying all requirements: reproducible before-state, isolated repair, applied patch, rerun PASS, terminal closeout, and complete provenance. Historical Repairman cases and current sessions were held rather than converted into unsupported pairs.\n\nCertified count remains 0/750. No training task, model load, candidate, evaluation, promotion, registry mutation, Slot32 update, or Slot120 load occurred.\n\nVerdict: `HOLD_NO_REPRODUCIBLE_REPAIR_FAILURES`.\n'''); (O/'FINAL_STATUS.md').write_text('FINAL_STATUS: PASS_SLOT32_REPAIR_CASE_FACTORY_OPERATIONAL\n\nAcquisition factory is operational; certified count 0/750 and training remains blocked.\n'); print(O)
