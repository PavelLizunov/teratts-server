"""Read-only bounded GGUF metadata inspection; never loads/infer weights."""
import argparse
import json
from pathlib import Path
import struct


def inspect(path):
    with Path(path).open('rb') as stream:
        def take(n):
            data=stream.read(n)
            if len(data)!=n:raise ValueError('Truncated GGUF metadata')
            return data
        def integer(code):return struct.unpack('<'+code,take(struct.calcsize(code)))[0]
        def string():
            count=integer('Q')
            if count>4*1024*1024:raise ValueError('Oversized metadata string')
            return take(count).decode('utf-8')
        def value(kind):
            formats={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
            if kind in formats:return integer(formats[kind])
            if kind==8:return string()
            if kind==9:
                subtype,count=integer('I'),integer('Q')
                if count>200000:raise ValueError('Oversized metadata array')
                return [value(subtype) for _ in range(count)]
            raise ValueError('Unknown GGUF type')
        if take(4)!=b'GGUF':raise ValueError('Not GGUF')
        version,tensors,metadata=integer('I'),integer('Q'),integer('Q')
        if version not in [2,3] or metadata>100000:raise ValueError('Unsupported GGUF header')
        selected={};tokens=[];types=[]
        for _ in range(metadata):
            key,kind=string(),integer('I');data=value(kind)
            if key=='tokenizer.ggml.tokens':tokens=data
            elif key=='tokenizer.ggml.token_type':types=data
            elif key in ['general.architecture','general.name','tokenizer.ggml.model','tokenizer.ggml.unknown_token_id'] or 'prompt' in key:
                if not isinstance(data,list) or len(data)<100:selected[key]=data
        return {'version':version,'tensor_count':tensors,'metadata':selected,'token_count':len(tokens),
                'literal_yo_tokens':[{'id':i,'token':t} for i,t in enumerate(tokens) if 'ё' in t or 'Ё' in t][:10],
                'byte_fallback_token_count':sum(t.startswith('<0x') and t.endswith('>') for t in tokens),
                'unknown_tokens':[{'id':i,'token':t,'type':types[i] if i<len(types) else None} for i,t in enumerate(tokens) if t=='<unk>'],
                'no_weights_loaded':True}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('path',type=Path);a=p.parse_args();print(json.dumps(inspect(a.path),ensure_ascii=False))
