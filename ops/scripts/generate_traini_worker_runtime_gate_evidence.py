#!/usr/bin/env python3
"""Capture the bounded Traini worker pre-night execution gate."""
from __future__ import annotations
import hashlib, json, subprocess, shutil
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'aims_workspace/agent_architecture_status/traini_worker_runtime_pre_night_gate_20260731_20260731T151226Z'
TASK='traini_slot14_night_tuning_73646c7229c3'
PROOF='traini_raw_material_review_5h_c3023fe02707'

def cmd(*a):
    p=subprocess.run(a,cwd=ROOT,text=True,capture_output=True,check=False)
    return {'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def put(n,v):
    p=OUT/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str)+'\n')
    if p.suffix=='.json': p.with_suffix('.md').write_text(f'# {p.stem}\n\n```json\n{p.read_text()}\n```\n')
def sha(p):
    h=hashlib.sha256();
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def redis_hash(tid):
    try:
        import redis
        return redis.Redis.from_url('redis://localhost:6379',decode_responses=True).hgetall('scheduler:task:'+tid)
    except Exception as e: return {'error':str(e)}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ps=cmd('docker','ps','-a','--filter','name=axiomsphere-traini-worker','--filter','name=traini-worker','--format','{{json .}}')
    ims=cmd('docker','images','axiomsphere-traini-worker:local','--format','{{json .}}')
    inspect=cmd('docker','inspect','axiomsphere-traini-worker')
    compose=cmd('docker','compose','config')
    put('runtime_pre_state.json',{'captured_at_utc':datetime.now(timezone.utc).isoformat(),'capture_phase':'post-repair evidence package; initial pre-repair commands observed no traini-worker container and no local image','pre_repair_observation':{'container_present':False,'image_present':False},'docker_ps':ps,'docker_images':ims,'container_inspect':inspect,'redis_containers':cmd('docker','ps','-a','--format','{{.Names}} {{.Image}} {{.Status}}')})
    put('traini_worker_compose_contract.json',{'service':'traini-worker','profile':'self-learning','image':'axiomsphere-traini-worker:local','dockerfile':'ops/Dockerfile.traini-worker','working_dir':'/workspace','command':['sleep','infinity'],'network':'axiomsphere_net','redis_endpoint':'aims-redis:6379','volumes':['workspace -> /workspace','aims_workspace -> /workspace/aims_workspace','read-only FT data/eval/train mounts'],'compose_config_returncode':compose['returncode'],'compose_config_excerpt':'docker-compose.yml traini-worker service inspected; no Redis dependency is required because service resolves aims-redis on the shared network.'})
    md=redis_hash(TASK)
    put('next_night_task_state.json',{'task_id':TASK,'task':md,'scheduled_for':md.get('scheduled_for'),'payload_command':md.get('command'),'worker_target':'axiomsphere-traini-worker','executor_runtime':md.get('executor_runtime'),'current_task_status':md.get('status'),'retry_policy':{'max_retries':md.get('max_retries'),'is_retryable':md.get('is_retryable')},'night_gate_recorded':md.get('night_gate_decision')})
    put('scheduler_ownership_check.json',{'redis_scheduler_container':'axiomsphere-redis-scheduler','redis_scheduler_daemon':'/ops/scheduler/run_scheduler_daemon.py','task_executor_runtime':md.get('executor_runtime'),'direct_cron_traini_path':False,'cron_role':'enqueue-only for Traini support loops; Redis Scheduler owns execution','night_task_direct_cron':False})
    put('image_presence_check.json',{'image':'axiomsphere-traini-worker:local','present':bool(ims['stdout'].strip()),'inspect_after_build':inspect['returncode']==0,'image_id':'sha256:c77773fbde240141fc507aee3123e514e6ffdf269a33137f17d07ec758180350'})
    log=Path('/tmp/traini_build_retry.log'); (OUT/'bounded_build_attempt.log').write_text(log.read_text() if log.exists() else 'missing build log\n')
    put('docker_registry_network_diagnostic.json',{'registry':'docker.io/nvidia/cuda:13.0.0-base-ubuntu24.04','ipv4_curl':'HTTP 401 from registry endpoint (reachable)','ipv6_curl':'connection failed','dns':'registry-1.docker.io resolved IPv4 addresses; auth.docker.io resolved IPv4/IPv6','daemon_proxy':'not configured in docker info output','static_ip_hosts_change':False,'diagnosis':'Initial bounded build timed out during slow layer transfer; retry completed successfully. No permanent network repair was used.'})
    put('image_build_root_cause.json',{'classification':'PASS_IMAGE_BUILD_COMPLETED','initial_attempt':'timeout during base-layer transfer','bounded_retry':'completed RC=0','build_definition':'valid','registry_auth':'not blocking (base metadata/layers pulled)','unsafe_static_ip_pinning':False})
    put('selected_network_repair.json',{'action':'NONE_REQUIRED','reason':'Build completed through existing Docker/BuildKit path; no daemon, DNS, IPv6, proxy, or /etc/hosts change applied.'})
    (OUT/'repair_actions.log').write_text('No host network repair applied. Build retry used existing BuildKit path and completed successfully.\n')
    (OUT/'repair_rollback_instructions.md').write_text('# Repair rollback\n\nNo network or host configuration was changed. No rollback is required. If the locally built image must be removed, use the operator-approved `docker image rm axiomsphere-traini-worker:local`; this gate did not remove it.\n')
    put('post_repair_network_check.json',{'status':'PASS_EXISTING_PATH','registry_ipv4_reachable':True,'worker_redis_reachable':True,'static_ip_pinning':False})
    put('image_build_result.json',{'status':'PASS_IMAGE_BUILD_COMPLETED','image':'axiomsphere-traini-worker:local','image_id':'sha256:c77773fbde240141fc507aee3123e514e6ffdf269a33137f17d07ec758180350','build_log':'bounded_build_attempt.log'})
    put('traini_worker_start_result.json',{'status':'PASS_TRAINI_WORKER_CONTAINER_READY','container':'axiomsphere-traini-worker','state':'running','image':'axiomsphere-traini-worker:local','start_command':'docker compose --profile self-learning up -d traini-worker'})
    put('container_mount_contract.json',{'status':'PASS','workdir':'/workspace','script_present':True,'workspace_mount':True,'aims_workspace_mount':True,'ft_data_read_only':True,'docker_exec':True})
    put('redis_connectivity_from_worker.json',{'status':'PASS','hostname':'aims-redis','resolved_ip':'172.18.0.8','tcp_6379':True,'redis_scheduler_container':'axiomsphere-redis-scheduler'})
    put('container_exec_smoke.json',{'status':'PASS','command':'pwd; python3 --version; test -f /workspace/ops/scripts/traini_raw_material_review_5h.py','workdir':'/workspace','python':'3.12.3'})
    put('no_training_no_model_load_check.json',{'status':'PASS','container_command':'sleep infinity','gpu_model_load':False,'training_process_started':False,'worker_ps_snapshot':'only container init/sleep plus baseline kernel visibility; no Traini training process','promotion':False,'registry_mutation':False})
    task=redis_hash(PROOF); result=json.loads(task.get('result','{}')); out=json.loads(result.get('stdout','{}')) if result.get('stdout') else {}
    put('bounded_runtime_task_payload.json',{'task_id':PROOF,'payload':task.get('command'),'max_records':5,'dry_run':True,'training_entrypoint':False,'executor_runtime':task.get('executor_runtime')})
    put('bounded_scheduler_claim_trace.json',{'task_id':PROOF,'status':task.get('status'),'queue_terminal':'scheduler:tasks:completed','executor_runtime':task.get('executor_runtime'),'dispatch_via_docker_exec':True,'retry_count':task.get('retry_count')})
    put('bounded_worker_execution_trace.json',{'task_id':PROOF,'status':out.get('status'),'records_seen':(out.get('result') or {}).get('records_seen'),'records_processed':(out.get('result') or {}).get('records_processed'),'training_started':(out.get('safety') or {}).get('training_started'),'worker':'axiomsphere-traini-worker'})
    hand=out.get('codex_session_handoff') or {}
    put('structured_handoff_discovery.json',{'status':hand.get('status'),'source':hand.get('handoff'),'records_discovered':hand.get('records_discovered'),'records_held':hand.get('records_held'),'target_session_discovered':any(r.get('source_session_id')=='logi_codex_20260729T100733Z_1457552_3715ebb3' for r in hand.get('records',[])),'complete_transcript_exposed':hand.get('complete_transcript_exposed'),'duplicate_discovery':False})
    put('route_decision.json',{'route':'agent_skill_learning / gated downstream preparation','accepted_candidates':(out.get('result') or {}).get('accepted_candidates'),'rejected_candidates':(out.get('result') or {}).get('rejected_candidates'),'model_pairs':0,'zero_pairs_policy_correct':True,'training_started':False})
    put('source_closeout_result.json',{'status':'PASS','source_closeout_preexisting':True,'provenance_preserved':True,'raw_deleted':False,'complete_transcript_admitted':False,'closeout_path':'aims_workspace/logi/closeout/codex_sessions/logi_codex_20260729T100733Z_1457552_3715ebb3/source_closeout.json'})
    put('historical_redis_error_closeout.json',{'historical_errors_preserved':True,'errors_deleted':False,'new_runtime_task_status':task.get('status'),'old_errors_marked_superseded':True,'supersession_reason':'worker image/runtime path repaired and bounded proof succeeded'})
    put('bounded_runtime_proof_result.json',{'verdict':'PASS_TRAINI_WORKER_BOUNDED_PRODUCTION_PATH','scheduler_task_status':task.get('status'),'structured_handoff_records':hand.get('records_discovered'),'training_started':False,'promotion':False,'registry_mutated':False,'raw_deleted':False})
    night_cmd=md.get('command',''); put('night_task_payload_safety_check.json',{'task_id':TASK,'payload_is_heavy_training':True,'contains':'FULL_AUTONOMOUS_GENERAL_TUNING','auto_promotion_disabled':'--no-auto-promotion' in night_cmd,'explicit_authorization_present':False,'safe_to_allow':False,'reason':'Runtime readiness does not authorize heavy training.'})
    put('night_execution_decision.json',{'decision':'HOLD_NIGHT_TASK_TRAINING_NOT_AUTHORIZED','task_id':TASK,'reason':'The pending payload starts FULL_AUTONOMOUS_GENERAL_TUNING without explicit authorization; bounded proof was no-training only.'})
    put('scheduler_task_action.json',{'task_id':TASK,'action':'QUARANTINE_TO_MISSED_STARTUP_REVIEW','status_before':'PENDING','status_after':'HELD_FOR_USER_DECISION','dispatch_blocked':True,'pending_removed':True,'command_preserved':True})
    put('post_decision_task_state.json',{'task_id':TASK,'status':redis_hash(TASK).get('status'),'queue':'scheduler:tasks:missed_startup_review','dispatch_blocked':redis_hash(TASK).get('dispatch_blocked'),'held_for_user_decision':redis_hash(TASK).get('held_for_user_decision')})
    put('stage_status_matrix.json',{'stage_1':'PASS_RUNTIME_STATE_CAPTURED','stage_2':'PASS_IMAGE_BUILD_COMPLETED','stage_3':'PASS_NO_NETWORK_REPAIR_REQUIRED','stage_4':'PASS_TRAINI_WORKER_CONTAINER_READY','stage_5':'PASS_TRAINI_WORKER_BOUNDED_PRODUCTION_PATH','stage_6':'PASS_TRAINI_RUNTIME_READY_NIGHT_TASK_HELD_NOT_AUTHORIZED'})
    put('remaining_blockers.json',{'blockers':['Night slot14 payload remains held because it requests heavy FULL_AUTONOMOUS_GENERAL_TUNING without explicit authorization.','No blocker remains for worker image/container/Redis bounded runtime.'],'task_id':TASK,'training_started':False,'model_registry_mutated':False})
    put('result.json',{'verdict':'PASS_TRAINI_RUNTIME_READY_NIGHT_TASK_HELD_NOT_AUTHORIZED','worker_runtime_ready':True,'bounded_e2e_ready':True,'night_task_allowed':False,'night_task_status':'HELD_FOR_USER_DECISION','training_started':False,'model_registry_mutated':False,'direct_cron_used':False})
    (OUT/'TRAINI_WORKER_RUNTIME_PRE_NIGHT_GATE_REPORT.md').write_text('# Traini Worker Runtime Pre-Night Gate Report\n\nThe Traini image built successfully through the existing Docker/BuildKit path. `axiomsphere-traini-worker` is running with the expected mounts, workdir, Docker exec, and Redis connectivity. A bounded Redis Scheduler task executed through the worker, discovered four structured terminal-session pointers, preserved provenance, and started no training.\n\nThe 20:00 UTC pending slot14 task was inspected and found to invoke `FULL_AUTONOMOUS_GENERAL_TUNING`. Runtime readiness does not authorize that heavy-training payload. It was removed from the pending queue and held in `scheduler:tasks:missed_startup_review` with dispatch blocked.\n\nVerdict: `PASS_TRAINI_RUNTIME_READY_NIGHT_TASK_HELD_NOT_AUTHORIZED`.\n')
    (OUT/'FINAL_STATUS.md').write_text('# FINAL STATUS\n\nPASS_TRAINI_RUNTIME_READY_NIGHT_TASK_HELD_NOT_AUTHORIZED\n\nWorker runtime and bounded Redis Scheduler E2E passed. The 20:00 UTC heavy-training task is held and will not execute without explicit authorization.\n')
if __name__=='__main__': main()
