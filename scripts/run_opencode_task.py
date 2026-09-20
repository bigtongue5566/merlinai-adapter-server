"""Run the user's exact scene prompt through real OpenCode in an isolated project."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
os.environ['LOG_LEVEL']='WARNING'
os.environ['LOG_TO_FILE']='false'
from smoke_test_opencode import RequestAudit
import uvicorn
from merlinai_adapter_server.app import app
from merlinai_adapter_server.config import ADAPTER_API_KEY
from merlinai_adapter_server.merlin_client import merlin_openai_client, merlin_gateway
from merlinai_adapter_server.models_catalog import MODEL_LIMITS, resolve_max_tokens

parser=argparse.ArgumentParser()
parser.add_argument('--tag',required=True)
parser.add_argument('--model',default='glm-5.3-flash')
parser.add_argument('--prompt-file',type=Path,required=True)
parser.add_argument('--timeout',type=int,default=1200)
parser.add_argument('--max-output-tokens',type=int)
parser.add_argument('--context-tokens',type=int)
args=parser.parse_args()
args.max_output_tokens = resolve_max_tokens(args.model, args.max_output_tokens)
if args.context_tokens is None:
    limits = MODEL_LIMITS.get(args.model)
    if limits is None:
        parser.error('Unknown model requires --context-tokens')
    args.context_tokens = limits.context
if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', args.tag):
    parser.error('--tag must be a short alphanumeric identifier, not a path')
if args.timeout <= 0 or args.context_tokens <= 0 or (args.max_output_tokens is not None and args.max_output_tokens <= 0):
    parser.error('Timeout and token limits must be positive')
if args.max_output_tokens and args.max_output_tokens >= args.context_tokens:
    parser.error('Output allowance must leave context room for input')
if not args.prompt_file.is_file():
    parser.error('--prompt-file must exist')
if not shutil.which('opencode'):
    parser.error('OpenCode executable was not found')
run_dir=ROOT/'logs'/('opencode-scene-e2e-'+args.tag)
run_dir.mkdir(exist_ok=False)
workdir=run_dir/'project'
workdir.mkdir()
# A separate Git root keeps OpenCode project discovery within the test folder.
subprocess.run(['git','init','--quiet',str(workdir)],check=True)
prompt=args.prompt_file.read_text(encoding='utf-8-sig')
(run_dir/'prompt.txt').write_text(prompt,encoding='utf-8')
upstream_records=[]
original_iter=merlin_gateway.iter_event_stream

def recording_iter(response,allowed_tool_names=None):
    record={'number':len(upstream_records)+1,'content':'','tokens':None,'completed':False,
            'reasoning_chars':0,'event_shapes':{}}
    upstream_records.append(record)
    try:
        for event in original_iter(response,allowed_tool_names):
            record['content']+=event.content_delta
            record['reasoning_chars']+=len(event.reasoning_delta)
            raw=event.raw_event
            shape=','.join(sorted(raw)) if isinstance(raw,dict) else type(raw).__name__
            if isinstance(raw,dict) and isinstance(raw.get('data'),dict):
                shape+='|data:'+','.join(sorted(raw['data']))
            record['event_shapes'][shape]=record['event_shapes'].get(shape,0)+1
            if event.usage:
                record['tokens']=event.usage.get('tokens')
            yield event
        record['completed']=True
    except Exception as exc:
        record['error']=str(exc)
        raise
    finally:
        (run_dir/f'upstream-{record["number"]}.json').write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'upstream':record['number'],'chars':len(record['content']),
                          'completed':record['completed'],'tokens':record['tokens']}),flush=True)

merlin_gateway.iter_event_stream=recording_iter
merlin_openai_client.tool_call_mode='emulated'
audit=RequestAudit(app)
listener=socket.socket()
listener.bind(('127.0.0.1',0))
port=listener.getsockname()[1]
server=uvicorn.Server(uvicorn.Config(audit,host='127.0.0.1',port=port,log_level='warning',access_log=False))
thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
thread.start()
deadline=time.monotonic()+10
while not server.started and time.monotonic()<deadline:
    time.sleep(.05)
if not server.started:
    raise RuntimeError('Local adapter failed to start')
env=os.environ.copy()
env['OPENCODE_CONFIG']=str(Path.home()/'.config/opencode/opencode.jsonc')
if args.max_output_tokens:
    env['OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX']=str(args.max_output_tokens)
config={
    'share':'disabled','autoupdate':False,'snapshot':False,
    'provider':{'merlinai':{'options':{'baseURL':f'http://127.0.0.1:{port}/v1','apiKey':ADAPTER_API_KEY}}},
    'agent':{'title':{'disable':True},'summary':{'disable':True}},
    'permission':{'external_directory':'deny','bash':{'*':'deny','dir*':'allow','ls*':'allow',
                  'pwd':'allow','node *':'allow','npm *':'allow','npx *':'allow'},'edit':'allow'},
}
if args.max_output_tokens:
    config['provider']['merlinai']['models']={args.model:{'limit':{'context':args.context_tokens,'output':args.max_output_tokens}}}
env['OPENCODE_CONFIG_CONTENT']=json.dumps(config)
command=[shutil.which('opencode'),'run','--pure','--format','json','--model','merlinai/'+args.model,
         '--agent','build','--title',args.model+' rain scene full prompt '+args.tag,'--dir',str(workdir),prompt]
started=time.monotonic()
timed_out=False
process=None
try:
    with (run_dir/'cli.jsonl').open('wb') as stdout, (run_dir/'cli.stderr').open('wb') as stderr:
        process=subprocess.Popen(command,cwd=workdir,env=env,stdout=stdout,stderr=stderr)
        print(json.dumps({'started':True,'directory':str(workdir),'pid':process.pid,
                          'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}),flush=True)
        last_report=started
        while process.poll() is None:
            now=time.monotonic()
            if now-started>args.timeout:
                timed_out=True
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                process.wait(timeout=15)
                break
            if now-last_report>=30:
                print(json.dumps({'elapsed_seconds':round(now-started),'requests':len(audit.records),
                                  'upstream_char_counts':[len(r['content']) for r in upstream_records]}),flush=True)
                last_report=now
            time.sleep(1)
finally:
    server.should_exit=True
    thread.join(timeout=10)
    listener.close()
    merlin_gateway.iter_event_stream=original_iter
events=[]
for line in (run_dir/'cli.jsonl').read_text(encoding='utf-8',errors='replace').splitlines():
    try:events.append(json.loads(line))
    except ValueError:pass
tool_events=[]
for event in events:
    if event.get('type')=='tool_use':
        part=event.get('part',{})
        state=part.get('state',{})
        tool_events.append({'tool':part.get('tool'),'status':state.get('status'),
                            'input':state.get('input'),'error':state.get('error'),
                            'metadata':state.get('metadata')})
errors=[e.get('error') for e in events if e.get('type')=='error']
files=[{'path':p.relative_to(workdir).as_posix(),'bytes':p.stat().st_size}
       for p in workdir.rglob('*') if p.is_file() and not any(x in p.relative_to(workdir).parts for x in ('.git','node_modules'))]
result={'max_output_tokens':args.max_output_tokens,'model':args.model,'adapter':'local current workspace; emulated','prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
        'exit_code':process.returncode,'timed_out':timed_out,'elapsed_seconds':round(time.monotonic()-started,2),
        'session_id':next((e['sessionID'] for e in events if e.get('sessionID')),None),'errors':errors,
        'final_text':'\n'.join(e.get('part',{}).get('text','') for e in events if e.get('type')=='text'),
        'tools':tool_events,'requests':audit.records,'files':files,
        'protocol_passed':bool(audit.records) and all(r['status']==200 and r['done'] and not r['errors'] and r['finish_reasons'] for r in audit.records)}
(run_dir/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('tools','requests','final_text')}),flush=True)
print(json.dumps({'tools':[{'tool':t['tool'],'status':t['status'],'error':t['error']} for t in tool_events]}),flush=True)
