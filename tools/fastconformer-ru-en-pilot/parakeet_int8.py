"""One pinned dynamic-int8 export of the already verified English checkpoint."""
import argparse
import json
from pathlib import Path

from english_fc import cell
from mms_pair import digest, save, supervise

SHA='3cfe22e14a7adf70b7b4ab33109a6fad4d7ca61821ca1f37168dc9b3d04b963b'


def prepare(args):
    import numpy as np
    import onnx
    from onnx import numpy_helper
    root,parent=Path(args.model),Path(args.parent)
    if (root/'prepared.json').exists():raise FileExistsError('Consumed preparation')
    prior=json.loads((parent/'prepared.json').read_text())
    for name,expected in (('model.onnx',prior['export_sha256']),('model.onnx.data',prior['external_sha256'])):
        if digest(parent/name)!=expected:raise ValueError('Changed verified FP32 parent')
    if digest(root/'model.onnx')!=SHA:raise ValueError('Wrong pinned int8 export')
    original=onnx.load(parent/'model.onnx',load_external_data=False);reference={}
    for t in original.graph.initializer:
        if t.data_location==onnx.TensorProto.EXTERNAL:
            e={x.key:x.value for x in t.external_data}
            if e['location']!='model.onnx.data' or t.data_type!=onnx.TensorProto.FLOAT:raise ValueError('Unknown FP32 storage')
            reference[t.name]=np.memmap(parent/'model.onnx.data',dtype='<f4',mode='r',offset=int(e['offset']),shape=tuple(t.dims))
        else:reference[t.name]=numpy_helper.to_array(t)
    model=onnx.load(root/'model.onnx');arrays={t.name:numpy_helper.to_array(t) for t in model.graph.initializer};matched=set();used=set();quant=[]
    for name,a in arrays.items():
        if name in reference:
            if not np.array_equal(a,reference[name]):raise ValueError('Changed nonquantized tensor '+name)
            matched.add(name);used.add(name)
    for n in model.graph.node:
        if n.op_type not in ('ConvInteger','MatMulInteger') or n.input[1] not in arrays:continue
        qname=n.input[1];base=qname.removesuffix('_quantized');q=arrays[qname];scale=arrays[base+'_scale'];zero=arrays[base+'_zero_point']
        if base not in reference:raise ValueError('Unknown quantized original '+base)
        if n.op_type=='ConvInteger' and scale.ndim:
            scale=scale.reshape((-1,)+(1,)*(q.ndim-1));zero=zero.reshape((-1,)+(1,)*(q.ndim-1))
        decoded=(q.astype(np.float64)-zero)*scale;orig=reference[base]
        if decoded.shape!=orig.shape or not np.all(scale>0):raise ValueError('Invalid quantized tensor shape/scale')
        error=np.abs(decoded-orig);units=float((error/scale).max())
        if units>1.01:raise ValueError('Quantized tensor differs from verified checkpoint '+base+' '+str(units))
        matched.add(base);used.update((qname,base+'_scale',base+'_zero_point'))
        quant.append({'name':base,'max_abs_difference':float(error.max()),'max_scale_units':units})
    if matched!=set(reference):raise ValueError('Unaccounted parent parameters '+repr(set(reference)-matched))
    extras={name:a for name,a in arrays.items() if name not in used}
    if any(a.dtype!=np.int64 or a.ndim!=1 or any(int(x) not in (-1,1) for x in a) for a in extras.values()):raise ValueError('Unexpected auxiliary int8 initializer '+repr(list(extras)))
    stride=[n for n in model.graph.node if n.op_type=='ConvInteger' and n.name.startswith('/pre_encode/') and any(a.name=='strides' and list(a.ints)==[2,2] for a in n.attribute)]
    if len(stride)!=3 or any(next(list(a.ints) for a in n.attribute if a.name=='pads')!=[1,1,1,1] for n in stride):raise ValueError('Changed native clock')
    for name,key in (('tokenizer.model','tokenizer_sha256'),('frontend.npz','frontend_sha256')):
        if digest(parent/name)!=prior[key]:raise ValueError('Changed original frontend/tokenizer')
        with (root/name).open('xb') as f:f.write((parent/name).read_bytes())
    receipt={**prior,'export_sha256':SHA,'external_sha256':None,'precision':'published dynamic int8, original FP32 nonquantized parameters',
             'fp32_parent_prepared_sha256':digest(parent/'prepared.json'),'quantized_parameters':quant,
             'accounted_parent_initializers':len(matched),'extra_reshape_constants':{n:a.tolist() for n,a in extras.items()},
             'full_operator_equivalence':False}
    save(root/'prepared.json',receipt)
    print(json.dumps({'matched_parent_initializers':len(matched),'quantized_tensors':len(quant),'maximum_quantization_step_difference':max(r['max_scale_units'] for r in quant),'extra_reshape_constants':len(extras),'prepared_sha256':digest(root/'prepared.json')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);p=sub.add_parser('prepare');p.add_argument('--model',required=True);p.add_argument('--parent',required=True)
    c=sub.add_parser('cell')
    for key in ('model','wav','audio-sha256','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='prepare':prepare(args)
    elif args.mode=='cell':cell(args)
    else:supervise(args,cell_script=__file__)
