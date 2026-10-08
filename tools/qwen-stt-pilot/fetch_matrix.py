"""Pinned public model file fetch, verified size/LFS SHA, no private audio."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

PROXY = 'http://192.168.0.142:18080'


def api(model):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': PROXY}))
    with opener.open('https://huggingface.co/api/models/' + model + '?blobs=true', timeout=30) as r:
        return json.load(r)


def fetch(model, dest, pattern=None):
    dest = Path(dest)
    dest.mkdir(parents=True, mode=0o700, exist_ok=True)
    receipt_path = dest / 'fetch-receipt.json'
    metadata_path = dest / 'pinned-api.json'
    j = json.loads(metadata_path.read_text()) if metadata_path.exists() else api(model)
    if not metadata_path.exists():
        metadata_path.write_text(json.dumps(j, ensure_ascii=False, indent=2))
    import fnmatch
    files = [f for f in j['siblings'] if f['rfilename'] not in ['.gitattributes', 'README.md']
             and (fnmatch.fnmatch(f['rfilename'], pattern) if pattern else
                  f['rfilename'].endswith(('.json', '.txt', '.safetensors')))]
    if not files:
        raise ValueError('No matching model files')
    receipts = []
    for f in files:
        rel = Path(f['rfilename'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('unsafe model filename')
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = f.get('lfs', {}).get('sha256')
        if not target.exists():
            part = Path(str(target) + '.part')
            url = f"https://huggingface.co/{model}/resolve/{j['sha']}/{f['rfilename']}"
            print('FETCH', model, f['rfilename'], f['size'], flush=True)
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--connect-timeout', '10', '--max-time', '1800', '--proxy', PROXY,
                            url, '-o', str(part)], check=True)
            if part.stat().st_size != f['size']:
                raise ValueError('Downloaded size mismatch')
            digest = hashfile(part)
            if expected and digest != expected:
                raise ValueError('Downloaded SHA mismatch')
            part.rename(target)
        digest = hashfile(target)
        if target.stat().st_size != f['size'] or (expected and digest != expected):
            raise ValueError('Existing model file does not match pinned source')
        receipts.append(dict(path=f['rfilename'], bytes=f['size'], sha256=digest))
        receipt_path.write_text(json.dumps(dict(model=model, revision=j['sha'], files=receipts), indent=2))
        print('VERIFIED', f['rfilename'], digest, flush=True)
    print('COMPLETE', model, sum(r['bytes'] for r in receipts), flush=True)


def hashfile(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('model')
    p.add_argument('destination')
    p.add_argument('--pattern')
    a = p.parse_args()
    fetch(a.model, a.destination, a.pattern)
