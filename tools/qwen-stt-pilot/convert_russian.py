"""Adapt inspected upstream Whisper converter for BF16 NumPy conversion only."""
import argparse
import hashlib
from pathlib import Path
import runpy
import sys


def convert(source, model, whisper_source, output, receipt):
    source = Path(source)
    text = source.read_text()
    old = 'data = list_vars[src].squeeze().numpy()'
    if text.count(old) != 1:
        raise ValueError('upstream converter boundary changed')
    patched = text.replace(old, 'data = list_vars[src].float().squeeze().numpy()')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    adapter = output / 'bf16-compatible-converter.py'
    adapter.write_text(patched)
    sys.argv = [str(adapter), str(model), str(whisper_source), str(output)]
    runpy.run_path(str(adapter), run_name='__main__')
    result = output / 'ggml-model.bin'
    h = hashlib.sha256()
    with result.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    import json
    Path(receipt).write_text(json.dumps(dict(source_converter_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(), change='BF16 -> temporary per-tensor float32 before NumPy; upstream F16 output unchanged',
        output_sha256=h.hexdigest(), output_bytes=result.stat().st_size),indent=2))
    print('CONVERSION_SUCCESS',h.hexdigest(),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('model');p.add_argument('whisper_source');p.add_argument('output');p.add_argument('receipt');a=p.parse_args();convert(a.source,a.model,a.whisper_source,a.output,a.receipt)
