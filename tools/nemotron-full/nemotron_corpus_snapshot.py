"""Immutable retained STT corpus snapshot for explicitly authorized full ASR run.

No inference/network calls. Every eligible source maps to exact WAV SHA, including
empty primary transcripts and valid failed STT uploads. Synthetic/TTS not human.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import time
import wave

MAX_AUDIO=11*1024*1024
MAX_METADATA=1024*1024
RESERVE=5_000_000_000


def atomic_json(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def wav_info(audio):
    with wave.open(io.BytesIO(audio),'rb') as sound:
        n,channels,width,rate=sound.getnframes(),sound.getnchannels(),sound.getsampwidth(),sound.getframerate()
        if sound.getcomptype()!='NONE' or not 8000<=rate<=96000 or channels not in [1,2] or width not in [1,2,3,4] or n<=0:
            raise ValueError('Unsupported WAV')
        frames=sound.readframes(n)
        if len(frames)!=n*channels*width:raise ValueError('Truncated WAV')
        return {'duration_s':n/rate,'sample_rate':rate,'channels':channels,'sample_width':width,'audio_frames':n}


def read_source(path):
    if path.is_symlink():raise ValueError('Archive symlink')
    with tarfile.open(path) as archive:
        member=archive.getmember('sample.json')
        if not member.isfile() or member.size>MAX_METADATA:raise ValueError('Invalid metadata')
        meta=json.load(archive.extractfile(member))
        kind=meta.get('kind')
        if kind not in ['stt','stt_failure']:return None,'not_submitted_stt'
        rid=next((v for k,v in meta.get('client_context',{}).get('headers',{}).items() if k.lower()=='x-request-id'),'')
        if isinstance(rid,str) and rid.startswith('synthetic'):return None,'synthetic_control'
        name='original.wav' if kind=='stt' else 'original.bin'
        member=archive.getmember(name)
        if not member.isfile() or not 44<=member.size<=MAX_AUDIO:raise ValueError('Invalid source audio size')
        audio=archive.extractfile(member).read()
    info=wav_info(audio);digest=hashlib.sha256(audio).hexdigest()
    if meta.get('audio_sha256') and meta['audio_sha256']!=digest:raise ValueError('Audio hash mismatch')
    source={'archive':path.name,'sample_id':meta.get('sample_id'),'kind':kind,
            'baseline_raw':meta.get('raw_text'),'recorded_final_text':meta.get('final_text'),
            'recorded_backend':meta.get('backend'),'human_reference_text':meta.get('human_reference_text'),
            'failure_status':meta.get('status') if kind=='stt_failure' else None}
    return {'audio':audio,'audio_sha256':digest,'audio_bytes':len(audio),**info,'source':source},None


def snapshot(corpus,destination):
    corpus,destination=Path(corpus),Path(destination)
    if corpus.is_symlink() or not corpus.is_dir():raise ValueError('Invalid corpus root')
    if (destination/'manifest.json').exists():raise ValueError('Immutable manifest already exists')
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    audio_root=destination/'audio';audio_root.mkdir(mode=0o700)
    paths=sorted(corpus.glob('*.tar'))
    started=time.time();unique={};excluded=[];counts=Counter();source_count=0
    for path in paths:
        try:
            record,reason=read_source(path)
            if record is None:
                counts[reason]+=1
                continue
        except (OSError,ValueError,KeyError,EOFError,tarfile.TarError,wave.Error,TypeError) as error:
            reason='missing_rotated' if isinstance(error,FileNotFoundError) else 'invalid_or_unreadable'
            excluded.append({'archive':path.name,'reason':reason,'error_type':type(error).__name__})
            counts[reason]+=1;continue
        digest=record['audio_sha256'];source=record.pop('source');audio=record.pop('audio');source_count+=1
        if digest not in unique:
            if shutil.disk_usage(destination).free-len(audio)<RESERVE:raise RuntimeError('Snapshot headroom exhausted')
            p=audio_root/(digest+'.wav')
            fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as out:out.write(audio);out.flush();os.fsync(out.fileno())
            unique[digest]={**record,'file':'audio/'+digest+'.wav','sources':[]}
        unique[digest]['sources'].append(source);counts[source['kind']]+=1
    data={'schema_version':1,'started_unix':started,'finished_unix':time.time(),
          'corpus_root':str(corpus),'archive_paths_at_snapshot':len(paths),'source_counts':dict(counts),
          'eligible_sources':source_count,'unique_audio':len(unique),'duplicate_sources':source_count-len(unique),
          'unique_audio_seconds':round(sum(r['duration_s'] for r in unique.values()),6),
          'snapshot_audio_bytes':sum(r['audio_bytes'] for r in unique.values()),
          'excluded_sources':excluded,'records':list(unique.values()),'new_audio_after_snapshot_included':False,
          'training_started':False,'gold_reference_available':False}
    atomic_json(destination/'manifest.json',data)
    digest=hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()
    (destination/'manifest.sha256').write_text(digest+'\n');(destination/'manifest.sha256').chmod(0o600)
    return {k:data[k] for k in ['archive_paths_at_snapshot','source_counts','eligible_sources','unique_audio','duplicate_sources','unique_audio_seconds','snapshot_audio_bytes']}|{'manifest_sha256':digest}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('corpus',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(json.dumps(snapshot(args.corpus,args.destination)))
