"""Separate Russian GigaAM-v3 RNNT component, whole audio and official frontend."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time
import wave

from giga_component import FRONTEND
from mms_pair import digest, save, supervise
from run import Guard

ORIGINAL_SHA='a89b662052ad2b8129b334ab45c171b04fc6699d69bd6917575013ff79172ec2'
FILES={'encoder.int8.onnx':'0ec54e5f130a91c0f228d21795ede10b31c992a1f73e45dcd827e843a71a9b50',
       'decoder.onnx':'5d1cfef155d8e07f213bd2f3229b5f6c5c29355c7fa5c1b9eb62cb1925725254',
       'joiner.onnx':'fd1d02f45c2ad3d6b67cc149811ad794ab4b020ed49a0a9e2790a8619d1cddd8'}


def prepare(root):
    import numpy as np
    import onnx
    from onnx import numpy_helper
    import torch
    import torchaudio
    torch.set_num_threads(2)
    if (root/'prepared.json').exists():raise FileExistsError('Consumed preparation')
    if digest(root/'original.bin')!=ORIGINAL_SHA:raise ValueError('Wrong original checkpoint')
    for name,expected in FILES.items():
        if digest(root/name)!=expected:raise ValueError('Changed published export')
    weights=torch.load(root/'original.bin',map_location='cpu',weights_only=True)
    cfg=json.loads((root/'original-config.json').read_text())['cfg']['model']['cfg']
    tokens={int(s.rsplit(' ',1)[1]):s.rsplit(' ',1)[0] for s in (root/'tokens.txt').read_text().splitlines()}
    if cfg['model_name']!='v3_rnnt' or [tokens[i] for i in range(33)]!=cfg['decoding']['vocabulary'] or tokens[33]!='<blk>':raise ValueError('Original trained token map differs')
    frontend=torchaudio.transforms.MelSpectrogram(**FRONTEND)
    frontend_buffers={};frontend_differences=[]
    for name,buffer in (('spectrogram.window',frontend.spectrogram.window),('mel_scale.fb',frontend.mel_scale.fb)):
        original=weights['model.preprocessor.featurizer.0.'+name]
        if original.shape!=buffer.shape or original.dtype!=torch.float32 or not torch.isfinite(original).all():raise ValueError('Invalid original frontend buffer')
        frontend_buffers[name]=original.numpy()
        frontend_differences.append({'name':name,'runtime_max_difference':float((buffer-original).abs().max()),'runtime_rms_difference':float((buffer-original).square().mean().sqrt())})
    models={name:onnx.load(root/name) for name in FILES}
    arrays={name:{t.name:numpy_helper.to_array(t) for t in graph.graph.initializer} for name,graph in models.items()}
    direct=[]
    def exact(array,key,transform=None):
        original=weights[key].float().numpy()
        if transform is not None:original=transform(original)
        if not np.array_equal(original,array):raise ValueError('Original trained tensor mismatch: '+key)
        direct.append({'key':key,'sha256':hashlib.sha256(original.tobytes()).hexdigest()})
    da=arrays['decoder.onnx'];decoder=models['decoder.onnx']
    exact(da['m.head.decoder.embed.weight'],'model.head.decoder.embed.weight')
    lstm=next(n for n in decoder.graph.node if n.op_type=='LSTM')
    # PyTorch i,f,g,o -> ONNX i,o,f,c. Bias concatenates both originals.
    reorder=lambda a:np.concatenate([a[:320],a[960:1280],a[320:640],a[640:960]])
    for index,name in ((1,'weight_ih_l0'),(2,'weight_hh_l0')):
        exact(da[lstm.input[index]],'model.head.decoder.lstm.'+name,lambda a:reorder(a)[None])
    bias=np.concatenate([reorder(weights['model.head.decoder.lstm.'+name].numpy()) for name in ('bias_ih_l0','bias_hh_l0')])[None]
    if not np.array_equal(bias,da[lstm.input[3]]):raise ValueError('ONNX LSTM original bias permutation mismatch')
    blank=float(weights['model.head.decoder.embed.weight'][33].abs().max())
    if blank!=0:raise ValueError('Original zero-input start differs from blank embedding')
    ja=arrays['joiner.onnx'];joint=models['joiner.onnx']
    for name in ('enc','pred','joint_net.1'):
        exact(ja[name+'.bias'],'model.head.joint.'+name+'.bias')
        node=next(n for n in joint.graph.node if n.op_type=='MatMul' and (n.name.startswith('/'+name+'/') if '.' not in name else '/joint_net.1/' in n.name))
        exact(ja[node.input[1]],'model.head.joint.'+name+'.weight',lambda a:a.T)
    if joint.graph.node[-1].op_type!='LogSoftmax':raise ValueError('Unexpected joiner score type')
    graph=models['encoder.int8.onnx'];ea=arrays['encoder.int8.onnx'];encoder_direct=[];quant=[]
    for name,array in ea.items():
        key='model.encoder.'+name
        if key in weights:
            exact(array,key);encoder_direct.append(key)
    for node in graph.graph.node:
        if node.op_type not in ('ConvInteger','MatMulInteger'):continue
        quant_name=node.input[1]
        if quant_name not in ea or not quant_name.endswith('_quantized'):continue
        base=quant_name.removesuffix('_quantized');scale=ea[base+'_scale'];zero=ea[base+'_zero_point'];q=ea[quant_name]
        if node.op_type=='ConvInteger':
            key='model.encoder.'+base;original=weights[key].float().numpy()
            if scale.ndim:scale=scale.reshape((-1,)+(1,)*(q.ndim-1));zero=zero.reshape((-1,)+(1,)*(q.ndim-1))
        else:
            module=node.name.removesuffix('/MatMul_quant').strip('/').replace('/','.')
            key='model.encoder.'+module+'.weight'
            if key not in weights:raise ValueError('Unknown original quantized projection '+key)
            original=weights[key].float().numpy().T
        decoded=(q.astype(np.float64)-zero)*scale
        if decoded.shape!=original.shape:raise ValueError('Quantized tensor shape mismatch')
        error=np.abs(decoded-original);maximum=float(error.max());units=float(np.max(error/scale))
        if units>1.01:raise ValueError('Quantized export outside original quantization bin: '+key+' '+str(units))
        quant.append({'key':key,'max_abs_difference':maximum,'max_scale_units':units})
    convs=[n for n in graph.graph.node if n.op_type=='ConvInteger' and n.name.startswith('/pre_encode/')]
    if len(convs)!=2 or any({a.name:list(a.ints) for a in n.attribute}.get('pads')!=[2,2] or {a.name:list(a.ints) for a in n.attribute}.get('strides')!=[2] for n in convs):raise ValueError('Unknown native stride/origin')
    with (root/'frontend.npz').open('xb') as file:np.savez_compressed(file,**frontend_buffers)
    receipt={'original_sha256':ORIGINAL_SHA,'files':FILES,'tokens':tokens,'frontend':FRONTEND,'frontend_buffers_exact':True,
             'frontend_sha256':digest(root/'frontend.npz'),'runtime_frontend_differences':frontend_differences,
             'decoder_joint_original_matches':direct[:9],'encoder_direct_matches':encoder_direct,'encoder_quantized_matches':quant,
             'lstm_gate_and_bias_permutation_exact':True,'blank_embedding_max_abs':blank,'native_stride_s':.04,'nominal_origin_s':159.5/16000,
             'original_config_sha256':digest(root/'original-config.json'),'original_source_sha256':digest(root/'original-modeling.py'),
             'download_receipt_sha256':digest(root/'download-receipt.json'),'tokens_sha256':digest(root/'tokens.txt'),
             'parameter_correspondence_not_full_graph_equivalence':True}
    save(root/'prepared.json',receipt)
    print(json.dumps({'direct_encoder_tensors':len(encoder_direct),'quantized_tensors':len(quant),'quantized_max_scale_units':max(x['max_scale_units'] for x in quant),**{k:v for k,v in receipt.items() if k not in ('tokens','encoder_direct_matches','encoder_quantized_matches','decoder_joint_original_matches')}},indent=2))


class Model:
    def __init__(self,root,encoder=False):
        import onnxruntime as ort
        self.root=Path(root);self.prepared=json.loads((self.root/'prepared.json').read_text())
        for name,expected in self.prepared['files'].items():
            if digest(self.root/name)!=expected:raise ValueError('Changed prepared Giga RNNT model')
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        names=['decoder.onnx','joiner.onnx']+(['encoder.int8.onnx'] if encoder else [])
        self.sessions={name:ort.InferenceSession(str(self.root/name),sess_options=opts,providers=['CPUExecutionProvider']) for name in names}
    def initial_states(self):
        import numpy as np
        return np.zeros((1,1,320),np.float32),np.zeros((1,1,320),np.float32)
    def predict(self,token,states):
        import numpy as np
        session=self.sessions['decoder.onnx'];values=(np.array([[token]],np.int32),np.array([1],np.int32),*states)
        out=session.run(None,{i.name:v for i,v in zip(session.get_inputs(),values)})
        return out[0],(out[2],out[3])
    def join(self,encoded,prediction):
        return self.sessions['joiner.onnx'].run(None,{'enc':encoded.reshape(1,768,1),'dec':prediction.reshape(1,320,1)})[0].reshape(34)
    def encode(self,features):
        import numpy as np
        return self.sessions['encoder.int8.onnx'].run(None,{'audio_signal':features,'length':np.array([features.shape[-1]],np.int64)})


def cell(args):
    import numpy as np
    import torch
    import torchaudio
    output,root=Path(args.output),Path(args.model)
    if output.exists() or output.with_suffix('.npz').exists():raise FileExistsError('Consumed Russian RNNT pass')
    start=time.monotonic();guard=Guard(600,8192)
    result={'status':'failed','bilingual':False,'language':'Russian','segmentation':False,'audio_padding':False,'postprocessing':'none',
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        if digest(args.wav)!=args.audio_sha256:raise ValueError('Changed original waveform')
        with wave.open(args.wav,'rb') as file:
            if (file.getnchannels(),file.getsampwidth(),file.getframerate(),file.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('Original PCM16 mono16k required')
            count=file.getnframes();waveform=torch.from_numpy(np.frombuffer(file.readframes(count),dtype='<i2').copy().astype(np.float32)/32768.)[None]
        prepared=json.loads((root/'prepared.json').read_text())
        if digest(root/'frontend.npz')!=prepared['frontend_sha256']:raise ValueError('Changed original frontend buffers')
        frontend=torchaudio.transforms.MelSpectrogram(**FRONTEND)
        with np.load(root/'frontend.npz') as file:
            frontend.spectrogram.window.copy_(torch.from_numpy(file['spectrogram.window']))
            frontend.mel_scale.fb.copy_(torch.from_numpy(file['mel_scale.fb']))
        with torch.inference_mode():features=frontend(waveform).clamp(1e-9,1e9).log().numpy()
        model=Model(root,encoder=True);guard.check();before=time.monotonic();encoded,length=model.encode(features);forward_s=time.monotonic()-before
        if encoded.shape!=(1,768,(features.shape[-1]+3)//4) or int(length[0])!=encoded.shape[-1] or not np.isfinite(encoded).all():raise ValueError('Native encoder geometry mismatch')
        with output.with_suffix('.npz').open('xb') as f:np.savez_compressed(f,encoded=encoded,length=length)
        ids=[];frames=[];cap_count=0;prediction,states=model.predict(33,model.initial_states());normalization_error=0.
        before=time.monotonic()
        for frame in range(encoded.shape[-1]):
            guard.check()
            for symbols in range(10):
                lp=model.join(encoded[:,:,frame:frame+1],prediction)
                normalization_error=max(normalization_error,abs(float(np.logaddexp.reduce(lp.astype(np.float64)))))
                token=int(lp.argmax())
                if token==33:break
                ids.append(token);frames.append(frame);prediction,states=model.predict(token,states)
            else:cap_count+=1
        if normalization_error>.001:raise ValueError('Unnormalized original RNNT joint')
        text=''.join(model.prepared['tokens'][str(t)] for t in ids)
        result.update(status='success',raw_text=text,postprocessed_text=text,token_ids=ids,frame_indices=frames,
                      audio_sha256=args.audio_sha256,audio_duration_s=count/16000,feature_frames=features.shape[-1],native_output_frames=encoded.shape[-1],
                      native_stride_s=.04,nominal_origin_s=159.5/16000,encoder_forward_s=forward_s,greedy_decode_s=time.monotonic()-before,
                      greedy_semantics='original zero-input start, max10symbols per frame, repeated labels allowed, no transcript repair',
                      frames_at_symbol_cap=cap_count,normalization_error=normalization_error,
                      retained_encoder_sha256=digest(output.with_suffix('.npz')),prepared_sha256=digest(root/'prepared.json'))
        print(text,flush=True)
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('--model',required=True)
    c=sub.add_parser('cell')
    for key in ('model','wav','audio-sha256','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='prepare':prepare(Path(args.model))
    elif args.mode=='cell':cell(args)
    else:supervise(args,cell_script=__file__)
