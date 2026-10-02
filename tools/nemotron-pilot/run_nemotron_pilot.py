"""Finite isolated CPU ASR pilot, not production promotion or gold WER."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import wave

ROOT=Path('/home/deck/homelab/nemotron-pilot')
CLI='/home/deck/homelab/parakeet-trial/nemo-speech-0.1.0-linux-x86_64-vulkan/bin/nemo-speech'
MODEL=ROOT/'cache/nemo-speech/models/nvidia/nemotron-3.5-asr-streaming-0.6b/1c8deaecc64b91f034d73e08dd8b64625eb3395d/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'
EXPECTED='a5c435f294eea8f88ce68dd27b8c3bfea7f777cb2fbba04fcd30eaa555f429ae'


def validate_manifest(data):
    if not 1<=len(data['samples'])<=8 or sum(s['duration_s'] for s in data['samples'])>90:
        raise ValueError('Trial exceeds approved limit')
    if len(data['hints'])>6 or data['boost']!=2:raise ValueError('Invalid hint trial')
    for sample in data['samples']:
        if not str(sample['file']).endswith('.wav') or Path(sample['file']).name!=sample['file']:
            raise ValueError('Invalid sample path')


def run(model=MODEL,expected=EXPECTED,output_name='results'):
    manifest=json.loads((ROOT/'manifest.json').read_text());validate_manifest(manifest)
    with model.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Model identity changed')
    output=ROOT/output_name;output.mkdir(mode=0o700,exist_ok=True)
    samples=[*manifest['samples'],{'file':'silence.wav','sample_id':'synthetic-silence','duration_s':1,'category':'negative_control'}]
    for mode in ['plain','hinted']:
        for i,sample in enumerate(samples,1):
            audio=ROOT/'samples'/sample['file'] if sample['file']!='silence.wav' else ROOT/'silence.wav'
            if 'audio_sha256' in sample and hashlib.sha256(audio.read_bytes()).hexdigest()!=sample['audio_sha256']:
                raise ValueError('Audio identity changed')
            dest=output/f'{mode}-{i}.json';record=output/f'{mode}-{i}.record.json'
            if record.exists():
                previous=json.loads(record.read_text())
                if (previous.get('returncode')==2 and 'unknown option: --boosted-words' in previous.get('diagnostic_tail','')
                        and mode=='hinted' and not dest.exists()):
                    preserved=record.with_suffix('.unsupported-cli-preserved.json')
                    if preserved.exists():raise ValueError('Preserved failure already exists')
                    record.rename(preserved)
                else:continue
            cmd=[CLI,'transcribe',str(audio),'--model',str(model),'--device','cpu','--language','ru',
                 '--format','json','--output',str(dest),'--no-warmup','--no-batching','--force']
            if mode=='hinted':
                for phrase in manifest['hints']:cmd+=['--speech-context',phrase]
                cmd+=['--speech-context-boost','2']
            start=time.monotonic()
            try:
                response=subprocess.run(cmd,text=True,capture_output=True,timeout=65)
                data=json.loads(dest.read_text()) if response.returncode==0 and dest.exists() else None
                row={'sample_id':sample['sample_id'],'category':sample['category'],'duration_s':sample['duration_s'],
                     'audio_sha256':sample.get('audio_sha256'),'baseline_raw':sample.get('baseline_raw'),
                     'mode':mode,'hints':manifest['hints'] if mode=='hinted' else [],'boost':2 if mode=='hinted' else 0,
                     'wall_seconds_cold_cli':round(time.monotonic()-start,3),'returncode':response.returncode,
                     'result':data,'diagnostic_tail':response.stderr[-3000:],'human_gold':False,
                     'model_sha256':expected,'device':'cpu','warm_service_comparable':False}
            except subprocess.TimeoutExpired:
                row={'sample_id':sample['sample_id'],'mode':mode,'status':'timeout_no_retry'}
            record.write_text(json.dumps(row,ensure_ascii=False,indent=2));record.chmod(0o600)
            print(json.dumps({'mode':mode,'index':i,'returncode':row.get('returncode'),
                              'seconds':row.get('wall_seconds_cold_cli'),'text_chars':len((row.get('result') or {}).get('text',''))}),flush=True)
            if row.get('returncode')!=0:raise RuntimeError('Trial stopped after failure; no retry')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,default=MODEL);p.add_argument('--sha256',default=EXPECTED);p.add_argument('--output-name',default='results')
    args=p.parse_args()
    if Path(args.output_name).name!=args.output_name:raise ValueError('Invalid output directory')
    run(args.model,args.sha256,args.output_name)
