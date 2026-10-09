"""All retained STT sentence inventory and bounded local SystemOne semantic triage."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import time
import urllib.request
import urllib.error


def inventory(corpus, output):
    import sqlite3
    c=sqlite3.connect('file:'+str(Path(corpus)/'vocabulary.sqlite')+'?mode=ro',uri=True)
    sources=[r[0] for r in c.execute("SELECT DISTINCT source FROM observations WHERE stage='stt_raw' ORDER BY source")]
    c.close();lines=[];missing=[]
    for name in sources:
        try:
            with tarfile.open(Path(corpus)/name) as t:d=json.load(t.extractfile('sample.json'))
            text=d.get('raw_text','')
            if not isinstance(text,str):continue
            parts=re.split(r'(?<=[.!?])\s+|\n+',text)
            for index,part in enumerate(parts):
                if not part.strip():continue
                # Long unpunctuated utterances are split at whitespace, without dropping words.
                words=part.split();chunk=[]
                for word in words:
                    if len(' '.join(chunk+[word]))>600 and chunk:
                        lines.append(dict(source=name,index=index,text=' '.join(chunk)));chunk=[]
                    chunk.append(word)
                if chunk:lines.append(dict(source=name,index=index,text=' '.join(chunk)))
        except (OSError,tarfile.TarError,ValueError):missing.append(name)
    root=Path(output);root.mkdir(parents=True,exist_ok=True);p=root/'sentences.json';p.write_text(json.dumps(lines,ensure_ascii=False));p.chmod(0o600)
    manifest=dict(sources=len(sources),sentences=len(lines),missing=missing,sentence_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),method='all raw STT text, sentence/whitespace splits, no deleted words')
    (root/'inventory.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)


def review(root,endpoint,seconds=7200):
    root=Path(root);sentences=json.loads((root/'sentences.json').read_text());output=root/'semantic-choice-answers.jsonl'
    existing=[]
    if output.exists():
        summarize(root)  # Validate receipts before trusting resumed coverage.
        existing=[json.loads(l) for l in output.read_text().splitlines() if l]
    done={idx for r in existing for idx in r['indices']};remaining=[(i,r) for i,r in enumerate(sentences) if i not in done]
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}));start=time.monotonic();reviewed=0;max_batch=2
    with output.open('a') as out:
        while remaining:
            if time.monotonic()-start>seconds:break
            batch=[];chars=0
            while remaining and len(batch)<max_batch:
                if batch and chars+len(remaining[0][1]['text'])>300:break
                item=remaining.pop(0);batch.append(item);chars+=len(item[1]['text'])
            state='Russian ASR data. Casual grammar/profanity normal; wrong names/words only.\n'+''.join(f'\n{k}: {row["text"]}' for k,(_,row) in enumerate(batch))
            questions={str(k):dict(type='choice',instructions=f'Assess {k}.',criteria={'clean':'Natural understandable speech','suspect':'Wrong ASR word damages meaning','uncertain':'Need audio to decide'}) for k in range(len(batch))}
            req=urllib.request.Request(endpoint,data=json.dumps(dict(model='clef-flash',state=state,questions=questions),ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
            tick=time.monotonic()
            try:
                with http.open(req,timeout=45) as r:response=json.load(r)
            except urllib.error.HTTPError as e:
                message=e.read().decode()
                if e.code==500 and 'too large to process' in message and len(batch)>1:
                    # Known physical-batch limit: change the request, do not retry identical work.
                    remaining=batch+remaining
                    root.joinpath('batch-limit-events.jsonl').open('a').write(json.dumps(dict(indices=[i for i,_ in batch],error=message))+'\n')
                    max_batch=max(1,len(batch)-1)
                    continue
                raise RuntimeError(f'local semantic HTTP {e.code}: {message}') from e
            if set(response.get('answers',{}))!=set(questions):raise ValueError('partial decision response')
            if response.get('usage',{}).get('output_tokens')!=0:raise ValueError('not typed decisions')
            for a in response['answers'].values():
                p=a['probabilities']['suspect']
                if not isinstance(p,(float,int)) or not 0<=p<=1:raise ValueError('invalid probability')
            response['answers']={str(batch[int(k)][0]):v for k,v in response['answers'].items()}
            row=dict(indices=[i for i,_ in batch],elapsed_s=time.monotonic()-tick,response=response)
            out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush();reviewed+=len(batch)
            if reviewed%80==0:print('SEMANTIC_REVIEWED',len(done)+reviewed,'OF',len(sentences),flush=True)
    summarize(root, time.monotonic()-start)


def summarize(root, elapsed_s=None):
    """Count validated choice receipts, including uncertain and low-confidence flags."""
    root=Path(root);sentences=json.loads((root/'sentences.json').read_text())
    seen=set();flags=[];counts={'clean':0,'suspect':0,'uncertain':0}
    output=root/'semantic-choice-answers.jsonl'
    for line in output.read_text().splitlines() if output.exists() else []:
        if not line:continue
        receipt=json.loads(line);answers=receipt['response']['answers']
        if set(answers)!=set(map(str,receipt['indices'])):raise ValueError('partial decision receipt')
        for idx in receipt['indices']:
            if type(idx) is not int or not 0<=idx<len(sentences) or idx in seen:raise ValueError('invalid or duplicate sentence index')
            answer=answers[str(idx)];choice=answer['choice'];p=answer['probabilities']['suspect']
            if choice not in counts or not isinstance(p,(int,float)) or isinstance(p,bool) or not 0<=p<=1:raise ValueError('invalid decision receipt')
            seen.add(idx);counts[choice]+=1
            if choice!='clean':flags.append(dict(**sentences[idx],sentence_id=idx,choice=choice,suspect_probability=p))
    summary=dict(total_sentences=len(sentences),unique_texts=len({r['text'] for r in sentences}),reviewed=len(seen),unique_texts_reviewed=len({sentences[i]['text'] for i in seen}),complete=len(seen)==len(sentences),choices=counts,flagged_count=len(flags),high_suspect_count=sum(f['suspect_probability']>=.8 for f in flags),method='local Clef typed plausibility triage, not audio truth',elapsed_s=elapsed_s)
    (root/'semantic-flags.json').write_text(json.dumps(flags,ensure_ascii=False,indent=2))
    (root/'semantic-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True);a=s.add_parser('inventory');a.add_argument('corpus');a.add_argument('output');a=s.add_parser('review');a.add_argument('root');a.add_argument('--endpoint',default='http://127.0.0.1:8092/v1/systemone');args=p.parse_args()
    if args.action=='inventory':inventory(args.corpus,args.output)
    else:review(args.root,args.endpoint)
