"""Stage 0 bootstrap: create pipeline dirs, resolve docx path, write pipeline-state.yaml."""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta

WS = r"D:\AAA-My-project\ICT"
PY = r"C:\Users\liyup\.workbuddy\binaries\python\versions\3.13.12\python.exe"
RESOLVE = (r"C:\Users\liyup\.workbuddy\plugins\cache\workbuddy-builtin\tencent-docx"
           r"\5.5.6-wb.38337834.g5f969292.h4918b5ced607\scripts\wb\local\resolve_output_docx_path.py")

rid = str(uuid.uuid4())
now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
root = os.path.join(WS, "output", rid)
for sub in ("stage1", "stage2/intermediate", "stage3", "working", "trace"):
    os.makedirs(os.path.join(root, sub), exist_ok=True)

p = subprocess.run([PY, RESOLVE, "--workspace", WS, "--request-id", rid,
                    "--filename", "毫芒Hairline-项目进展汇报.docx"],
                   capture_output=True, text=True, encoding="utf-8")
info = json.loads(p.stdout)
assert info["success"], p.stderr
docx_path = info["output_docx_path"]

state = f"""schema_version: 1
request_id: {rid}
created_at: {now}
updated_at: {now}

entry_type: full_pipeline
stage_chain: [1, 2, 3]

output_docx_path: {docx_path}
output_docx_user_specified: false

current_stage: 1

stages:
  stage_0:
    status: completed
    completed_at: {now}
    decision: full_pipeline
  stage_1:
    status: in_progress
    started_at: {now}
    completed_at: null
    output_path: null
    genre: null
    expert_used: null
    route_tag: null
    critic_decision: null
  stage_2:
    status: pending
    started_at: null
    completed_at: null
    route: null
    html_sub: null
    output_path: null
    output_format: null
    skills_invoked: []
    design_tokens_path: null
    fallback: false
    fallback_reason: null
  stage_3:
    status: pending
    started_at: null
    completed_at: null
    executor: null
    input_format: null
    output_path: null
    skill_used: []
    present_files_opened: false
    fallback: false
    fallback_reason: null

consistency_check:
  output_files_exist: null
  stage_chain_complete: null
  last_checked_at: null
  errors: []
"""
with open(os.path.join(root, "pipeline-state.yaml"), "w", encoding="utf-8") as f:
    f.write(state)

# remove the no-request-id stray dir if it was created earlier
stray = os.path.join(WS, "output")
print("request_id =", rid)
print("docx_path  =", docx_path)
print("root       =", root)
print("stray_dir_contents =", os.listdir(stray))
