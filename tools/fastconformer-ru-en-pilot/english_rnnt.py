"""New English RNNT decoder on activations recovered from retained CTC outputs."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from ctc_lm import pilot
from decoder import ContextBias, decode
from english_fc import ORIGINAL_SHA, EXPORT_SHA
from mms_pair import digest, save
from rnnt_fp32 import OriginalDecoder
from run import Guard
from subword_pair import BOUNDARY, TokenRules


class BoundaryContext:
    def __init__(self, rules, bonus):
        self.rules=rules
        self.graph=ContextBias(rules.paths if bonus else (),bonus)
    def step(self,state,token):
        total=0.
        for symbol in self.rules.symbols(token):
            delta,state=self.graph.step(state,symbol);total+=delta
        return total,state
    def finalize(self,state):
        delta,state=self.graph.step(state,BOUNDARY)
        return delta+self.graph.finalize(state)


def cell(args):
    import numpy as np
    import onnx
    from onnx import numpy_helper
    import sentencepiece as spm
    import torch
    output,root,parent=Path(args.output),Path(args.model),Path(args.receipt)
    recovered_path=output.with_name(output.stem+'-encoder.npz')
    if output.exists() or recovered_path.exists():raise FileExistsError('Consumed or unknown English RNNT cell')
    start=time.monotonic();guard=Guard(600,4096)
    result={'status':'failed','variants':{},'encoder_rerun':False,'audio_input':False,'bilingual':False,
            'postprocessing':'none','parameters':{'beam':4,'max_symbols':10,'context':[0.,1.5]},
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        receipt=json.loads(parent.read_text());prepared=json.loads((root/'prepared.json').read_text())
        if digest(root/'prepared.json')!=receipt['prepared_sha256'] or digest(root/'model.onnx')!=EXPORT_SHA or digest(parent.with_suffix('.npz'))!=receipt['retained_logits_sha256']:raise ValueError('Changed English CTC provenance')
        model=OriginalDecoder(root/'original.nemo',expected_sha=ORIGINAL_SHA,classes=1025)
        if model.weights['decoder.prediction.embed.weight'][-1].abs().max().item()!=0.:raise ValueError('Blank embedding differs from NeMo zero start')
        graph=onnx.load(root/'model.onnx')
        tensors={t.name:numpy_helper.to_array(t).copy() for t in graph.graph.initializer if t.name.startswith('ctc_decoder.')}
        del graph
        weight=torch.from_numpy(tensors['ctc_decoder.decoder_layers.0.weight']).squeeze(-1).double()
        bias=torch.from_numpy(tensors['ctc_decoder.decoder_layers.0.bias']).double()
        matrix=weight-weight.mean(0,keepdim=True)
        with np.load(parent.with_suffix('.npz')) as f:logp=torch.from_numpy(f['log_probs']).double()
        target=logp-bias;target-=target.mean(1,keepdim=True)
        solution=torch.linalg.lstsq(matrix,target.T,driver='gelsd')
        if int(solution.rank)!=512:raise ValueError('CTC projection is not full column rank')
        hidden=solution.solution.T
        delta=(hidden@weight.T+bias).log_softmax(-1)-logp
        if delta.abs().max().item()>.001:raise ValueError('Recovered encoder reprojection failed')
        encoded=hidden.float().T[None].contiguous().numpy()
        with recovered_path.open('xb') as f:np.savez_compressed(f,encoded=encoded,length=np.array([len(logp)],np.int64))
        recovery={'audio_sha256':receipt['audio_sha256'],'parent_sha256':digest(parent),'retained_encoder_sha256':digest(recovered_path),
                  'encoded_frames':len(logp),'projection_rank':int(solution.rank),
                  'projection_condition':float(solution.singular_values[0]/solution.singular_values[-1]),
                  'reprojection_max_error':float(delta.abs().max()),'reprojection_rms_error':float(delta.square().mean().sqrt()),
                  'encoder_rerun':False,'not_bit_identical':True}
        save(recovered_path.with_suffix('.json'),recovery)
        if digest(root/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed tokenizer')
        processor=spm.SentencePieceProcessor(model_file=str(root/'tokenizer.model'))
        pieces={int(k):v for k,v in prepared['vocab'].items()}
        rules=TokenRules(pieces,{0:' ',33:'<blk>'},processor)
        result.update(recovery=recovery,tensor_hashes=model.tensor_hashes,load_recovery_s=time.monotonic()-start)
        for name,bonus in (('no-context',0.),('context',1.5)):
            before=time.monotonic()
            value=decode(model,encoded,len(logp),range(1,1024),1024,BoundaryContext(rules,bonus),beam=4,max_symbols=10,check=guard.check)
            value.update(raw_text=''.join(pieces[i] for i in value['token_ids']).replace('▁',' ').strip(),decode_s=time.monotonic()-before,
                         context_score=bonus,context_paths=rules.hint_receipts if bonus else [])
            value['postprocessed_text']=value['raw_text']
            save(output.with_name(output.stem+'-'+name+'.json'),value);result['variants'][name]=value
            print(name,value['raw_text'],flush=True)
        result['status']='success'
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);c=s.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    q=s.add_parser('pilot');q.add_argument('manifest');args=p.parse_args()
    if args.mode=='cell':cell(args)
    else:pilot(args,cell_script=__file__)
