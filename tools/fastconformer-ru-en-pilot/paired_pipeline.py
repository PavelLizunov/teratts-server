"""Sequential whole-audio RU/EN pipeline with independent guarded model lifetimes.

Auxiliary Whisper supplies timing proposals only. Final output is one constrained
open CTC32/RNNT4 path; only boundary spaces are formatted after decoding.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import wave

from mms_pair import digest, save
from pilot import rss_bytes
from run import Guard, memory_snapshot, sensors


def audio(path,expected):
    import numpy as np
    if digest(path)!=expected:raise ValueError('Original waveform changed')
    with wave.open(str(path),'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('Original monoPCM16/16k required')
        count=f.getnframes();x=np.frombuffer(f.readframes(count),dtype='<i2').astype(np.float32)/32768.
    if len(x)!=count:raise ValueError('Truncated original audio')
    return x


def features(x,root,head):
    import numpy as np
    with np.load(root/'frontend.npz') as f:
        if head=='eng':window=f['window'];bank=f['bank'][0]
        else:window=f['spectrogram.window'];bank=f['mel_scale.fb'].T
    if head=='eng':
        x=np.concatenate((x[:1],x[1:]-np.float32(.97)*x[:-1]));window=np.pad(window,(56,56))
        frames=np.lib.stride_tricks.sliding_window_view(np.pad(x,(256,256),mode='reflect'),512)[::160]
    else:frames=np.lib.stride_tricks.sliding_window_view(x,320)[::160]
    spectrum=np.fft.rfft(frames*window,axis=-1);power=(np.abs(spectrum)**2).astype(np.float32)
    mel=power@bank.T
    if head=='eng':
        mel=np.log(mel+np.float32(2**-24));mel=(mel-mel.mean(0,keepdims=True))/(mel.std(0,ddof=1,keepdims=True)+np.float32(1e-5))
    else:mel=np.log(np.clip(mel,np.float32(1e-9),np.float32(1e9)))
    return np.ascontiguousarray(mel.T[None],dtype=np.float32)


def auxiliary(cfg,clip,out,guard):
    import numpy as np
    import ctranslate2
    from faster_whisper.feature_extractor import FeatureExtractor
    from tokenizers import Tokenizer
    root=Path(cfg['whisper_model']);receipt=json.loads((root/'download-receipt.json').read_text())
    if receipt['revision']!='bf64d2a976a268e35041f74233f889f951f0f676':raise ValueError('Wrong auxiliary model')
    for f in receipt['files']:
        if digest(root/f['name'])!=f['sha256']:raise ValueError('Changed auxiliary model file')
    x=audio(clip['wav'],clip['sha256']);pre=json.loads((root/'preprocessor_config.json').read_text())
    f=FeatureExtractor(feature_size=pre['feature_size'])(x,padding=0)
    model=ctranslate2.models.Whisper(str(root),device='cpu',compute_type='int8',intra_threads=2,inter_threads=1)
    tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'));guard.check();start=time.monotonic()
    encoded=model.encode(ctranslate2.StorageView.from_array(f[None]));encode_s=time.monotonic()-start;guard.check()
    hint='ChatGPT, ChatGPT Pro, DSH, Oracle.'
    base=[tokenizer.token_to_id(t) for t in ('<|startoftranscript|>','<|ru|>','<|transcribe|>','<|notimestamps|>')]
    prompt=[tokenizer.token_to_id('<|startofprev|>'),*tokenizer.encode(' '+hint,add_special_tokens=False).ids,*base]
    start=time.monotonic();r=model.generate(encoded,[prompt],beam_size=5,num_hypotheses=3,max_length=448,return_scores=True,return_no_speech_prob=True,sampling_temperature=0,suppress_blank=True,suppress_tokens=[-1])[0];guard.check()
    return {'audio_sha256':clip['sha256'],'proposal_only_not_final_output':True,'selected_rank':1,'encode_s':encode_s,'decode_s':time.monotonic()-start,
            'hypotheses':[{'raw_text':tokenizer.decode(ids,skip_special_tokens=True),'token_ids':ids,'score':score} for ids,score in zip(r.sequences_ids,r.scores)],
            'prompt_ids':prompt,'feature_frames':f.shape[-1],'asset_receipt_sha256':digest(root/'download-receipt.json')}


def acoustic(cfg,clip,out,head,guard):
    import numpy as np
    import onnxruntime as ort
    root=Path(cfg['english_model' if head=='eng' else 'russian_model']);receipt=json.loads((root/'prepared.json').read_text())
    if digest(root/'frontend.npz')!=receipt['frontend_sha256']:raise ValueError('Changed trained frontend')
    x=audio(clip['wav'],clip['sha256']);f=features(x,root,head)
    if head=='eng':
        files=receipt['runtime_external_files'];graph=root/'runtime.onnx'
    else:files={'encoder.int8.onnx':receipt['files']['encoder.int8.onnx']};graph=root/'encoder.int8.onnx'
    for name,sha in files.items():
        if digest(root/name)!=sha:raise ValueError('Changed acoustic model')
    opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
    model=ort.InferenceSession(str(graph),sess_options=opts,providers=['CPUExecutionProvider']);guard.check();start=time.monotonic()
    result=model.run(None,{'audio_signal':f,'length':np.array([f.shape[-1]],np.int64)});guard.check();forward_s=time.monotonic()-start
    values=result[0][0] if head=='eng' else result[0]
    if head=='eng':
        if values.shape!=((f.shape[-1]+7)//8,1025) or np.max(np.abs(np.logaddexp.reduce(values.astype(float),axis=1)))>.001:raise ValueError('English native output mismatch')
    elif values.shape!=(1,768,(f.shape[-1]+3)//4) or int(result[1][0])!=values.shape[-1]:raise ValueError('Russian native output mismatch')
    if not np.isfinite(values).all():raise ValueError('Nonfinite acoustic result')
    with out.with_suffix('.npz').open('xb') as file:np.savez_compressed(file,values=values,features=f)
    return {'audio_sha256':clip['sha256'],'head':head,'whole_audio_samples':len(x),'forward_s':forward_s,'feature_shape':list(f.shape),'output_shape':list(values.shape),
            'retained_array_sha256':digest(out.with_suffix('.npz')),'prepared_sha256':digest(root/'prepared.json'),'onnxruntime':ort.__version__,'numpy':np.__version__}


def final_decode(cfg,clip,out,guard):
    import numpy as np
    import sentencepiece as spm
    from giga_transducer import Model
    from subword_pair import auxiliary_labels
    from russian_boundary import NativeWordRules
    from phrase_guidance import align_phrases
    from mixed_transducer import search
    folder=Path(cfg.get('retained_inputs_directory',out.parent));stem=clip['id'];results={k:json.loads((folder/(stem+'-'+k+'.json')).read_text()) for k in ('aux','eng','rus')}
    for h in ('eng','rus'):
        if digest(folder/(stem+'-'+h+'.npz'))!=results[h]['retained_array_sha256']:raise ValueError('Changed retained pipeline scores')
    with np.load(folder/(stem+'-eng.npz')) as f:lp=f['values'].astype(np.float64)
    with np.load(folder/(stem+'-rus.npz')) as f:encoded=f['values']
    em=Path(cfg['english_model']);p=json.loads((em/'prepared.json').read_text());model=Model(Path(cfg['russian_model']))
    if digest(em/'tokenizer.model')!=p['tokenizer_sha256']:raise ValueError('Changed tokenizer')
    if digest(em/'prepared.json')!=results['eng']['prepared_sha256'] or digest(Path(cfg['russian_model'])/'prepared.json')!=results['rus']['prepared_sha256']:raise ValueError('Changed acoustic mapping')
    tokens={int(k):v for k,v in model.prepared['tokens'].items()};sp=spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model'))
    rules=NativeWordRules({int(k):v for k,v in p['vocab'].items()},tokens,sp,p['english_case'])
    sequence,words,_=auxiliary_labels(results['aux']['hypotheses'][0]['raw_text'],sp,{v:k for k,v in tokens.items() if k!=33},p['english_case'])
    lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
    events=[{'head':'eng','native_frame':i,'center_s':i*.08,'log_probs':r} for i,r in enumerate(lp)]
    events.extend({'head':'rus','native_frame':i,'center_s':i*.04+model.prepared['nominal_origin_s']} for i in range(encoded.shape[-1]));events.sort(key=lambda e:e['center_s'])
    start=time.monotonic();selected,alignment=align_phrases(events,sequence,guard.check);align_s=time.monotonic()-start
    alignment.update(audio_sha256=clip['sha256'],label_path=sequence,proposal_words=words);save(out.with_name(stem+'-alignment.json'),alignment)
    start=time.monotonic();value=search(selected,encoded,lp,model,rules,2.5,guard.check,rnnt_head='rus',ctc_beam=32)
    if not value['hypotheses']:raise ValueError('No finite bilingual path')
    return {'audio_sha256':clip['sha256'],'alignment_s':align_s,'decode_s':time.monotonic()-start,'search':value,'formatting':rules.formatting,
            'alignment_sha256':digest(out.with_name(stem+'-alignment.json')),'input_receipt_sha256':{k:digest(folder/(stem+'-'+k+'.json')) for k in results}}


def stage(args):
    cfg=json.loads(Path(args.manifest).read_text());clip=next(c for c in cfg['recordings'] if c['id']==args.clip);out=Path(cfg['results_directory'])/(args.clip+'-'+args.stage+'.json')
    if out.exists() or out.with_suffix('.npz').exists():raise FileExistsError('Consumed/unknown pipeline stage')
    start=time.monotonic();guard=Guard(600,cfg['rss_mib']);receipt={'status':'failed','source_commit':cfg['source_commit'],'stage':args.stage}
    try:
        if args.stage=='aux':receipt.update(auxiliary(cfg,clip,out,guard))
        elif args.stage in ('eng','rus'):receipt.update(acoustic(cfg,clip,out,args.stage,guard))
        else:receipt.update(final_decode(cfg,clip,out,guard))
        receipt['status']='success'
    except Exception as error:receipt['error']=type(error).__name__+': '+str(error);raise
    finally:receipt.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(out,receipt)


def pilot(args):
    cfg=json.loads(Path(args.manifest).read_text());folder=Path(cfg['results_directory']);folder.mkdir(mode=0o700,exist_ok=False)
    source=Path(__file__).parent
    for name,sha in cfg['source_files'].items():
        if digest(source/name)!=sha:raise ValueError('Changed pinned runtime code')
    for clip in cfg['recordings']:
        begin=time.monotonic();baseline=memory_snapshot();stages=[]
        for name in (('final',) if cfg.get('retained_inputs_directory') else ('aux','eng','rus','final')):
            interpreter=cfg['whisper_python'] if name=='aux' else cfg['acoustic_python'];out=folder/(clip['id']+'-'+name+'.json')
            cmd=[interpreter,str(Path(__file__).resolve()),'stage',args.manifest,'--clip',clip['id'],'--stage',name]
            samples=[];reason=None;started=time.monotonic();peak=0
            with out.with_suffix('.stdout').open('xb') as stdout,out.with_suffix('.stderr').open('xb') as stderr:
                proc=subprocess.Popen(['nice','-n','19',*cmd],stdout=stdout,stderr=stderr,start_new_session=True,
                                      env=dict(os.environ,OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1'))
                try:
                    while proc.poll() is None:
                        memory=memory_snapshot();sensor=sensors();rss=rss_bytes(proc.pid);peak=max(peak,rss)
                        sample={'elapsed_s':time.monotonic()-started,'rss_bytes':rss,'available_bytes':memory['MemAvailable'],'swap_growth_bytes':memory['swap_used']-baseline['swap_used'],**sensor};samples.append(sample)
                        if rss>cfg['rss_mib']*1048576:reason='rss_limit'
                        if memory['MemAvailable']<2048*1048576:reason='available_memory_floor'
                        if sample['swap_growth_bytes']>256*1048576:reason='swap_growth_limit'
                        if any(v>=85000 for v in sensor['temperatures_millic'].values()):reason='thermal_limit'
                        if time.monotonic()-begin>600:reason='recording_timeout'
                        if reason:break
                        time.sleep(.25)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid,signal.SIGTERM)
                        try:proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
                    code=proc.wait()
            r={'stage':name,'exit_code':code,'stop_reason':reason,'elapsed_s':time.monotonic()-started,'peak_rss_bytes':peak,'samples':samples,'command':cmd}
            save(out.with_name(out.stem+'-supervisor.json'),r);stages.append({k:v for k,v in r.items() if k not in ('samples','command')})
            print(clip['id'],name,'exit',code,'stop',reason,flush=True)
            if code or reason:
                save(folder/(clip['id']+'-pipeline.json'),{'status':'failed','elapsed_s':time.monotonic()-begin,'stages':stages,'limits_source':'agent-selected isolated method protection'})
                raise RuntimeError('Stopped pipeline; retain all consumed stages, no automatic retry')
        save(folder/(clip['id']+'-pipeline.json'),{'status':'success','elapsed_s':time.monotonic()-begin,'audio_sha256':clip['sha256'],'stages':stages,'source_commit':cfg['source_commit'],
                                               'manifest_sha256':digest(args.manifest),'limits_source':'agent-selected isolated method protection'})


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);r=s.add_parser('pilot');r.add_argument('manifest');r=s.add_parser('stage');r.add_argument('manifest');r.add_argument('--clip',required=True);r.add_argument('--stage',choices=('aux','eng','rus','final'),required=True);args=p.parse_args()
    if args.mode=='stage':stage(args)
    else:pilot(args)
