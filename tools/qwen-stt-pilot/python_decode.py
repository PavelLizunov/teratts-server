"""One private local audio file to JSON; supported HF/ONNX engines, no prompts."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['omni','tone']);p.add_argument('model');p.add_argument('audio');a=p.parse_args()
    import numpy as np
    import soundfile as sf
    pcm, rate=sf.read(a.audio,dtype='float32')
    if rate!=16000 or pcm.ndim!=1:raise ValueError('expected frozen 16kHz mono')
    if a.kind=='omni':
        import torch
        from transformers import AutoProcessor, AutoModelForCTC
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        processor=AutoProcessor.from_pretrained(a.model,local_files_only=True)
        model=AutoModelForCTC.from_pretrained(a.model,local_files_only=True).eval()
        inputs=processor(pcm,sampling_rate=rate,return_tensors='pt')
        with torch.inference_mode():logits=model(**inputs).logits
        text=processor.batch_decode(logits.argmax(dim=-1))[0]
    else:
        from scipy.signal import resample_poly
        import onnx_asr
        import onnxruntime as ort
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        model=onnx_asr.load_model('t-one-ctc',a.model,providers=['CPUExecutionProvider'],sess_options=opts)
        pcm=resample_poly(pcm,1,2).astype(np.float32)
        text=model.recognize(pcm,sample_rate=8000)
    print(json.dumps(dict(text=text),ensure_ascii=False))


if __name__=='__main__':main()
