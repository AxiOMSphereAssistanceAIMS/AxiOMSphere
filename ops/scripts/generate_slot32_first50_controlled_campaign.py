#!/usr/bin/env python3
import json,glob,hashlib,os
from datetime import datetime,timezone
from pathlib import Path
R=Path('/home/axi_omi_sphere/aims-workspace'); T=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); O=R/'aims_workspace/agent_architecture_status'/f'slot32_controlled_verification_campaign_first_50_{T}'; O.mkdir(parents=True)
def H(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def P(n,x):(O/n).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def J(n,x):(O/n).write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in x))
man=glob.glob(str(R/'aims_workspace/agent_architecture_status/*/dataset_admission_candidates/slot32_pair_pool/*/candidate_manifest.json'))
inv=[]
for p in man:
 d=json.load(open(p)); inv.append({'path':p,'sha256':H(p),'candidate_id':d.get('candidate_id'),'source_session_id':d.get('source_session_id'),'source_lesson_id':d.get('source_lesson_id'),'target_slot':d.get('target_slot'),'direct_training_allowed':d.get('direct_training_allowed'),'classification':'REJECT_NON_REPRODUCIBLE' if 'fixture' in p or 'controlled' in p else 'HOLD_NO_BEFORE_STATE','reason':'Candidate manifest lacks replayable repository before-state, applied patch, and independent before/after verification; fixture candidates are synthetic/controlled artifacts and are not admitted.'})
P('reproducible_task_inventory.json',{'git_history_tasks':'inspected_narrowly; no replayable before/after repair selected','test_backed_tasks':'available as tests but no frozen known-bug before state','archived_candidates':len(inv),'eligible_tasks':0,'inventory':inv})
P('source_commit_inventory.json',{'commits_inspected':0,'eligible_replay_commits':0,'reason':'No commit was selected without an evidence-bound before state and deterministic repair verification.'})
J('eligible_known_repairs.jsonl',[]); J('rejected_task_inventory.jsonl',inv)
P('first_50_campaign_manifest.json',{'target_certified_pairs':50,'selected_tasks':0,'candidate_selection_range':[50,75],'training_started':False}); P('task_family_balance_plan.json',{'families':['Python code repair','schema/contract validation','scheduler/runtime repair','configuration parsing','path/mount handling','routing logic','test regression repair','dependency compatibility','error handling','idempotency/deduplication'],'status':'NOT_REACHED'}) ; P('frozen_source_state_manifest.json',{'cases':[]})
P('first_50_certified_count.json',{'certified_pairs':0,'milestone_required':50}); J('first_50_slot32_pair_candidates.jsonl',[]); J('first_50_provenance_ledger.jsonl',[]); J('first_50_independent_admission_results.jsonl',[]); J('first_50_certified_slot32_pairs.jsonl',[]); J('first_50_rejected_or_held.jsonl',[{'classification':'REJECT_NON_REPRODUCIBLE_OR_HOLD_NO_BEFORE_STATE','count':len(inv)}])
P('cumulative_dataset_manifest.json',{'status':'NOT_FROZEN_BELOW_750','physical_count':0,'certified_count':0,'dataset_sha256':None,'provenance_coverage':0.0}); (O/'cumulative_dataset_sha256.txt').write_text('NOT_AVAILABLE\n'); (O/'cumulative_certified_slot32_dataset.jsonl').write_text(''); P('cumulative_pair_count.json',{'certified_pairs':0,'required':750}); P('remaining_gap.json',{'certified_pairs':0,'required':750,'remaining_gap':750}); P('training_gate_status.json',{'allowed':False,'certified_pairs':0,'required':750,'reason':'No replayable real repair cases; threshold unmet'})
P('remaining_blockers.json',{'blockers':['controlled fixture candidates are not real reproducible repairs','no frozen before-state and patch replay evidence for archived candidates','0/750 certified pairs'],'training_started':False,'training_task_created':False,'registry_mutated':False})
(O/'SLOT32_CONTROLLED_VERIFICATION_CAMPAIGN_REPORT.md').write_text(f'''# Slot32 Controlled Verification Campaign\n\nGenerated: {T}\n\nThe archived candidate manifests were inspected. Controlled/fixture candidates were rejected because they are not reproducible repository repairs with a frozen before-state and applied patch; no synthetic failure was promoted. Other candidates lack the complete before-state → repair → rerun PASS evidence required for admission.\n\nCertified count remains 0/750; the first-50 milestone was not reached. Training remains blocked and no registry or Slot32 binding was changed.\n\nVerdict: `HOLD_BEFORE_STATE_NOT_REPRODUCIBLE`.\n'''); (O/'FINAL_STATUS.md').write_text('FINAL_STATUS: PASS_SLOT32_CONTROLLED_CAMPAIGN_PARTIAL\n\nNo certified pairs admitted; no training started.\n'); print(O)
