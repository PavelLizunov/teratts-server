"""Fixed offline GigaAM CPU profile; private PCM fixtures, no hints."""
import argparse
import cProfile
import hashlib
import io
import json
from pathlib import Path
import pstats
import resource
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import gigaam_multilingual_server as adapter
    runner=adapter.Recognizer(Path('/home/deck/homelab/gigaam-multilingual-20261005/models'))
    rows=[]
    fixtures=sorted((args.root/'audio').glob('*.wav'))
    if len(fixtures)<4:raise RuntimeError('Missing fixed fixtures')
    for p in fixtures:
        raw=p.read_bytes(); out=runner.transcribe(raw)
        rows.append({'file':p.name,'audio_sha256':hashlib.sha256(raw).hexdigest(),'output':out})
    profiler=cProfile.Profile();profiler.enable()
    runner.transcribe(fixtures[0].read_bytes())
    profiler.disable();buffer=io.StringIO();pstats.Stats(profiler,stream=buffer).sort_stats('cumulative').print_stats(35)
    (args.root/'profile.txt').write_text(buffer.getvalue())
    (args.root/'reference-private.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(buffer.getvalue());print('peak_rss_bytes',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)

if __name__=='__main__':main()
