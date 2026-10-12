"""Pinned English-only FastConformer CTC component, original frontend buffers.

Prepare verifies tokenizer/head and exported parameters without model inference.
Cell performs one whole original recording forward and retains all native scores.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import tarfile
import time
import wave

from mms_pair import digest, save, supervise
from run import Guard

ORIGINAL_SHA = 'ad9953401a4080e501fe86b36159f94d2bb84da3f07b5613fb0f99057e40d0c2'
EXPORT_SHA = 'c07e9b3809e1dae5f3e376ce0dc5b7593ba8180bf7dc5a78fd522582e7191d1f'


def prepare(args):
    import numpy as np
    import onnx
    from onnx import numpy_helper
    import sentencepiece as spm
    import torch
    import yaml
    root = Path(args.model)
    if (root/'prepared.json').exists(): raise FileExistsError('Prepared assets already exist')
    if digest(root/'original.nemo') != ORIGINAL_SHA or digest(root/'model.onnx') != EXPORT_SHA:
        raise ValueError('Published asset digest mismatch')
    with tarfile.open(root/'original.nemo') as archive:
        config = yaml.safe_load(archive.extractfile('./model_config.yaml'))
        name = './'+config['tokenizer']['model_path'].removeprefix('nemo:')
        serialized = archive.extractfile(name).read()
        with archive.extractfile('./model_weights.ckpt') as file:
            weights = torch.load(file, map_location='cpu', weights_only=True)
    processor = spm.SentencePieceProcessor(model_proto=serialized)
    vocab = config['aux_ctc']['decoder']['vocabulary']
    exported_tokens = {int(line.rsplit(' ',1)[1]):line.rsplit(' ',1)[0] for line in (root/'vocab.txt').read_text().splitlines()}
    if len(vocab)!=1024 or processor.get_piece_size()!=1024 or any(processor.id_to_piece(i)!=piece or exported_tokens[i]!=piece for i,piece in enumerate(vocab)) or exported_tokens[1024]!='<blk>':
        raise ValueError('Original tokenizer, CTC head and export ID mismatch')
    window, bank = weights['preprocessor.featurizer.window'],weights['preprocessor.featurizer.fb']
    if tuple(window.shape)!=(400,) or tuple(bank.shape)!=(1,80,257):raise ValueError('Unexpected frontend buffers')
    cfg=config['preprocessor']
    expected={'sample_rate':16000,'normalize':'per_feature','window_size':.025,'window_stride':.01,'window':'hann','features':80,'n_fft':512,'frame_splicing':1,'pad_to':0}
    if any(cfg.get(k)!=v for k,v in expected.items()):raise ValueError('Unsupported original frontend')
    model=onnx.load(root/'model.onnx')
    arrays={t.name:numpy_helper.to_array(t) for t in model.graph.initializer}
    checked,folds,unmatched=[],[],[]
    for name,array in arrays.items():
        if name in weights and tuple(weights[name].shape)==array.shape and np.array_equal(weights[name].numpy(),array):checked.append(name)
        else:unmatched.append(name)
    for layer in range(config['encoder']['n_layers']):
        p=f'encoder.layers.{layer}.conv.'
        scale=weights[p+'batch_norm.weight']/torch.sqrt(weights[p+'batch_norm.running_var']+1e-5)
        folded=[(weights[p+'depthwise_conv.weight']*scale[:,None,None]).numpy(),((weights[p+'depthwise_conv.bias']-weights[p+'batch_norm.running_mean'])*scale+weights[p+'batch_norm.bias']).numpy()]
        nodes=[n for n in model.graph.node if n.op_type=='Conv' and n.name.endswith('/depthwise_conv/Conv') and f'/layers.{layer}/' in n.name]
        if len(nodes)!=1:raise ValueError('Unknown folded convolution mapping')
        for i,a in enumerate(folded,1):
            name=nodes[0].input[i]
            delta=float(np.max(np.abs(a.astype(np.float64)-arrays[name])))
            if delta>1e-4:raise ValueError('Folded parameter mismatch')
            folds.append({'name':name,'max_abs_difference':delta})
            if name in unmatched:unmatched.remove(name)
    # Export may transpose a constant matrix while preserving every value.
    remaining=[]
    for name in unmatched:
        array=arrays[name]
        matches=[key for key,value in weights.items() if value.ndim==2 and tuple(value.T.shape)==array.shape and np.array_equal(value.T.numpy(),array)]
        if matches:checked.append({'export':name,'transpose_original':matches})
        else:remaining.append({'name':name,'shape':list(array.shape)})
    if remaining:raise ValueError('Unaccounted exported learned parameters: '+repr(remaining))
    for key in ('ctc_decoder.decoder_layers.0.weight','ctc_decoder.decoder_layers.0.bias'):
        if key not in checked:raise ValueError('Unverified original CTC output head')
    with (root/'tokenizer.model').open('xb') as file:file.write(serialized)
    with (root/'frontend.npz').open('xb') as file:np.savez_compressed(file,window=window.numpy(),bank=bank.numpy())
    receipt={'original_sha256':ORIGINAL_SHA,'export_sha256':EXPORT_SHA,'preprocessor':cfg,'vocab':exported_tokens,'blank_id':1024,'unknown_id':0,
             'tokenizer_sha256':digest(root/'tokenizer.model'),'frontend_sha256':digest(root/'frontend.npz'),
             'direct_or_transpose_parameter_matches':checked,'folded_parameters':folds,'unmatched_parameters':remaining,
             'all_export_parameters_accounted':True,'full_operator_equivalence':False,'native_stride_s':.08,'nominal_origin_s':0.,
             'hint_ids':{hint:processor.encode(hint) for hint in ('ChatGPT','ChatGPT Pro','DSH','Oracle')}}
    save(root/'prepared.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('vocab','direct_or_transpose_parameter_matches','folded_parameters')},indent=2))


def cell(args):
    import numpy as np
    import onnxruntime as ort
    import torch
    root,output=Path(args.model),Path(args.output)
    if output.exists() or output.with_suffix('.npz').exists():raise FileExistsError('Consumed acoustic cell')
    started=time.monotonic();guard=Guard(600,8192)
    result={'status':'failed','language':'English','bilingual':False,'waveform_segmentation':False,'audio_padding':False,'postprocessing':'none',
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        receipt=json.loads((root/'prepared.json').read_text())
        if digest(root/'model.onnx')!=receipt['export_sha256'] or digest(root/'frontend.npz')!=receipt['frontend_sha256'] or digest(root/'tokenizer.model')!=receipt['tokenizer_sha256']:raise ValueError('Prepared model changed')
        if digest(args.wav)!=args.audio_sha256:raise ValueError('Original audio changed')
        with wave.open(args.wav,'rb') as file:
            if (file.getnchannels(),file.getsampwidth(),file.getframerate(),file.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('Original mono16PCM required')
            count=file.getnframes();x=torch.from_numpy(np.frombuffer(file.readframes(count),dtype='<i2').copy().astype(np.float32))/32768.
        with np.load(root/'frontend.npz') as file:window=torch.from_numpy(file['window']);bank=torch.from_numpy(file['bank'])
        x=torch.cat((x[:1],x[1:]-.97*x[:-1]))
        spectrum=torch.stft(x[None],n_fft=512,hop_length=160,win_length=400,center=True,window=window,return_complex=True)
        power=torch.sqrt(torch.view_as_real(spectrum).pow(2).sum(-1)).pow(2)
        mel=torch.log(torch.matmul(bank,power)+2**-24)
        features=(mel-mel.mean(-1,keepdim=True))/(mel.std(-1,keepdim=True)+1e-5)
        if features.shape!=(1,80,count//160+1) or not torch.isfinite(features).all():raise ValueError('Frontend geometry')
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        model=ort.InferenceSession(str(root/'model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
        guard.check();before=time.monotonic()
        lp=model.run(None,{'audio_signal':features.numpy(),'length':np.array([features.shape[-1]],np.int64)})[0][0]
        forward_s=time.monotonic()-before
        if lp.shape!=((features.shape[-1]+7)//8,1025) or not np.isfinite(lp).all():raise ValueError('Native CTC output geometry')
        with output.with_suffix('.npz').open('xb') as file:np.savez_compressed(file,log_probs=lp)
        normalizer=np.logaddexp.reduce(lp.astype(np.float64),axis=1)
        if np.abs(normalizer).max()>.001:raise ValueError('Non-normalized original CTC output')
        guard.check();ids=[];previous=None
        for token in lp.argmax(-1).tolist():
            if token!=1024 and token!=previous:ids.append(token)
            previous=token
        text=''.join(receipt['vocab'][str(i)] for i in ids).replace('▁',' ').strip()
        result.update(status='success',raw_text=text,postprocessed_text=text,token_ids=ids,audio_sha256=args.audio_sha256,audio_duration_s=count/16000,
                      input_samples=count,feature_frames=features.shape[-1],native_output_frames=len(lp),native_stride_s=.08,nominal_origin_s=0.,
                      retained_logits_sha256=digest(output.with_suffix('.npz')),prepared_sha256=digest(root/'prepared.json'),
                      forward_s=forward_s,frontend='original stored Hann/mel buffers, NeMo eval math, no appended waveform',
                      normalization_error=float(np.abs(normalizer).max()),runtime={'torch':torch.__version__,'onnxruntime':ort.__version__})
        print(text,flush=True)
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('--model',required=True)
    c=sub.add_parser('cell')
    for key in ('model','wav','audio-sha256','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='prepare':prepare(args)
    elif args.mode=='cell':cell(args)
    else:supervise(args,cell_script=__file__)
