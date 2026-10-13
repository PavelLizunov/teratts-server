"""Whole-audio/text EmbeddingGemma2 ranking diagnostic, never text generation."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import resource
import time
import wave

from mms_pair import digest, save
from run import Guard


def run(root,base):
    import numpy as np
    import torch
    from transformers import AutoConfig,AutoModel,AutoProcessor
    output=root/'embedding-results';output.mkdir(exist_ok=False);start=time.monotonic();guard=Guard(900,6144)
    result={'status':'failed','rows':[],'text_controls':[],'generation':False,'audio_upload':False,'audio_segmentation':False,'appended_waveform_padding':False,
            'dtype':'float32','vision_tower_loaded':False,'dimensions':768,'prompt':'task: sentence similarity | query: ',
            'pooling':'attention-mask mean, then float32 L2 normalize','score_not_acoustic_probability':True}
    try:
        torch.set_num_threads(2);torch.set_num_interop_threads(1);modelroot=root/'embeddinggemma2';receipt=json.loads((modelroot/'download-receipt.json').read_text())
        if receipt['revision']!='914f7f89142e33e77833254d9c9b90c3cef7303b':raise ValueError('Wrong embedding checkpoint')
        for asset in receipt['files']:
            if digest(modelroot/asset['name'])!=asset['sha256']:raise ValueError('Changed embedding asset')
        config=AutoConfig.from_pretrained(modelroot,local_files_only=True);config.vision_config=None
        model,loading=AutoModel.from_pretrained(modelroot,config=config,dtype=torch.float32,attn_implementation='eager',local_files_only=True,output_loading_info=True)
        if loading.get('missing_keys') or loading.get('mismatched_keys'):raise ValueError('Unloaded expected embedding parameters')
        unexpected=loading.get('unexpected_keys',[])
        if any(not k.startswith(('vision_tower.','embed_vision.')) for k in unexpected):raise ValueError('Unexpected nonvision checkpoint tensors')
        model.eval();processor=AutoProcessor.from_pretrained(modelroot,local_files_only=True)
        loading=json.loads(json.dumps(loading,default=lambda value:sorted(value) if isinstance(value,set) else str(value)))
        result.update(loading=loading,loaded_parameters=sum(p.numel() for p in model.parameters()),load_s=time.monotonic()-start,
                      asset_receipt_sha256=digest(modelroot/'download-receipt.json'),runtime={k:importlib.metadata.version(k) for k in ('torch','transformers','numpy','tokenizers','librosa')})
        guard.check()
        def embed(inputs):
            guard.check();t=time.monotonic()
            with torch.inference_mode():
                out=model(**inputs).last_hidden_state.float();mask=inputs['attention_mask'].unsqueeze(-1).float()
                vector=(out*mask).sum(1)/mask.sum(1).clamp_min(1);vector=torch.nn.functional.normalize(vector,p=2,dim=-1)
            if vector.shape[-1]!=768 or not torch.isfinite(vector).all():raise ValueError('Invalid native embedding')
            guard.check();return vector.cpu().numpy()[0],time.monotonic()-t
        cache={}
        def text_embed(text):
            if text not in cache:
                values=processor.tokenizer(result['prompt']+text,return_tensors='pt',padding=False,truncation=False)
                if values['input_ids'].shape[1]>8192:raise ValueError('Text context limit')
                cache[text]=embed(values)
            return cache[text]
        suite=json.loads((root/'suite.json').read_text());result['suite_sha256']=digest(root/'suite.json')
        for row in suite['rows']:
            if row['kind']!='synthetic_text_control':continue
            a,_=text_embed(row['input']);choices=[text_embed(t)[0] for t in row['candidates']];scores=[float(a@b) for b in choices];idx=int(np.argmax(scores))
            control={'id':row['id'],'input':row['input'],'candidates':row['candidates'],'reference':row['reference'],'scores':scores,'selected_index':idx,'selected_text':row['candidates'][idx]}
            result['text_controls'].append(control)
        save(output/'text-controls.json',result['text_controls'])
        for clip,wav in (('short','chatgpt-pro-original.wav'),('long','original.wav')):
            row=next(x for x in suite['rows'] if x['id']==clip);path=base/wav
            if digest(path)!=row['audio_sha256']:raise ValueError('Changed original audio')
            with wave.open(str(path),'rb') as f:
                if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,16000):raise ValueError('Original mono16k PCM required')
                samples=f.getnframes();audio=np.frombuffer(f.readframes(samples),dtype='<i2').astype(np.float32)/32768.
            # No batch padding or truncation of waveform. Native semicausal STFT
            # internally prepends half a window, as required by original model.
            inputs=processor(audio=audio,return_tensors='pt',audio_kwargs={'sampling_rate':16000,'padding':False,'truncation':False,'max_length':None,'pad_to_multiple_of':None})
            if inputs['input_ids'].shape[1]>8192:raise ValueError('Audio context limit')
            save(output/(clip+'-started.json'),{'audio_sha256':row['audio_sha256'],'samples':samples,'inputs':{k:list(v.shape) for k,v in inputs.items()}})
            a,audio_s=embed(inputs);candidates=[{'source':'asr_nbest_'+str(i),'text':t} for i,t in enumerate(row['candidates'])]
            for m in ('qwen25','qwen3'):
                p=root/f'results-{m}/edit-{clip}.json';r=json.loads(p.read_text());candidates.append({'source':m+'_edit','text':r['selected_text'],'receipt_sha256':digest(p)})
            original=row['input'];negative=original.replace('не ','',1);changed=original.replace('oracle','postgresql',1) if clip=='short' else original.replace('dsh','ssh',1)
            candidates.extend([{'source':'probe_negation_removed_not_ASR','text':negative},{'source':'probe_name_replaced_not_ASR','text':changed},
                               {'source':'probe_unrelated_not_ASR','text':'Сегодня солнечная погода и мы идём гулять в парк.'}])
            vectors=[]
            for c in candidates:
                b,seconds=text_embed(c['text']);vectors.append(b);c.update(cosine=float(a@b),text_forward_s=seconds)
            ordering=sorted(range(len(candidates)),key=lambda i:candidates[i]['cosine'],reverse=True)
            observation={'id':clip,'audio_sha256':row['audio_sha256'],'samples':samples,'duration_s':samples/16000,'audio_forward_s':audio_s,
                         'input_shapes':{k:list(v.shape) for k,v in inputs.items()},'valid_feature_frames':int(inputs['input_features_mask'].sum()),
                         'audio_placeholder_tokens':int((inputs['input_ids']==config.audio_token_id).sum()),'candidates':candidates,'ranking':ordering,
                         'no_human_reference':True,'negation_probe_equal_input':negative==original,'name_probe_equal_input':changed==original}
            with (output/(clip+'-vectors.npz')).open('xb') as f:np.savez_compressed(f,audio=a,text=np.stack(vectors))
            observation['vectors_sha256']=digest(output/(clip+'-vectors.npz'));save(output/(clip+'.json'),observation);result['rows'].append(observation)
            print(clip,[(candidates[i]['source'],round(candidates[i]['cosine'],6)) for i in ordering],flush=True)
        result['status']='success'
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output/'summary.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--base',required=True);a=p.parse_args();run(Path(a.root),Path(a.base))
