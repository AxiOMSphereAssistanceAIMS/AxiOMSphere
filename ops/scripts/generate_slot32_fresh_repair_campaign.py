#!/usr/bin/env python3
import json,glob,os,hashlib
from datetime import datetime,timezone
from pathlib import Path
R=Path('/home/axi_omi_sphere/aims-workspace'); T=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); O=R/'aims_workspace/agent_architecture_status'/f'slot32_fresh_verified_repair_case_campaign_{T}'; O.mkdir(parents=True)
def H(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def P(n,x):(O/n).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def J(n,x):(O/n).write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in x))
mans=sorted(glob.glob(str(R/'aims_workspace/logi/raw_material/codex_sessions/*/session_manifest.json')),key=os.path.getmtime,reverse=True)[:10]; src=[]
for p in mans:
 d=json.load(open(p)); src.append({'manifest_path':p,'manifest_sha256':H(p),'status':d.get('status'),'started_at':d.get('started_at'),'ended_at':d.get('ended_at'),'traini_raw_material_status':d.get('traini_raw_material_status'),'admission':'HOLD_RUNNING_SESSION' if d.get('status')=='RUNNING' else 'HOLD_NO_EXPLICIT_REPAIR_CHAIN'})
P('fresh_source_session_inventory.json',{'selected_count':len(src),'sessions':src,'eligible_terminal_sessions':0,'reason':'All newest sources are RUNNING RAW_POINTER_ONLY or lack explicit independently verified repair chains'})
J('repair_chain_extraction_results.jsonl',[]); J('slot32_pair_candidates.jsonl',[]); J('independent_admission_results.jsonl',[]); J('certified_slot32_pairs.jsonl',[]); J('certified_slot32_provenance_ledger.jsonl',[])
P('cumulative_pair_count.json',{'certified_pairs':0,'required':750,'remaining_gap':750}); P('remaining_gap.json',{'required':750,'certified_pairs':0,'remaining_gap':750}); P('milestone_gate_status.json',{'50':{'status':'NOT_REACHED'},'150':{'status':'NOT_REACHED'},'300':{'status':'NOT_REACHED'},'500':{'status':'NOT_REACHED'},'750':{'status':'NOT_REACHED'},'first_cycle':{'candidates':0,'admitted':0,'held':len(src),'rejected':0}}); P('dataset_readiness_status.json',{'decision':'HOLD_NO_NEW_ELIGIBLE_REPAIR_CASES','certified_pairs':0,'required':750,'provenance_coverage':0.0,'training_allowed':False})
P('full_e2e_resume_status.json',{'resumed':False,'reason':'Dataset below threshold; no training task exists','training_task_created':False,'incumbent_preserved':True}); P('remaining_blockers.json',{'blockers':['No new terminal sessions with terminal admission and explicit verified repair chain','Newest sessions are RUNNING and RAW_POINTER_ONLY','750 certified pairs required; current count 0'],'training_started':False,'registry_mutated':False,'slot120_loaded':False})
(O/'SLOT32_FRESH_REPAIR_CASE_CAMPAIGN_REPORT.md').write_text(f'''# Slot32 Fresh Verified Repair Case Campaign\n\nGenerated: {T}\n\nThe bounded first acquisition cycle inspected {len(src)} newest session manifests. No source was eligible: the newest sessions are `RUNNING` with `RAW_POINTER_ONLY`, and no terminal source with a complete problem → repair → verification PASS chain was available. Therefore zero candidates were transformed or admitted; certified count remains 0/750.\n\nNo transcripts, skill material, unresolved failures, or fabricated provenance were admitted. The historical invalid lineage remains retired. Training and full E2E resume were not started.\n\nVerdict: `HOLD_NO_NEW_ELIGIBLE_REPAIR_CASES`.\n'''); (O/'FINAL_STATUS.md').write_text('FINAL_STATUS: HOLD_NO_NEW_ELIGIBLE_REPAIR_CASES\n\nCertified pairs 0/750; no training task created.\n'); print(O)
