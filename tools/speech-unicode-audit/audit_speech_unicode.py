"""Read-only Unicode/stage/audio audit. Private content report, no inference."""
from collections import Counter
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time
import unicodedata as u
import wave
import re


def suspicious(ch):
    cp=ord(ch);category=u.category(ch);name=u.name(ch,'unnamed')
    return (cp==0xfffd or category in ['Cc','Cf','Cs','Co','Cn','Mn'] and ch not in '\n\r\t'
        or cp>127 and 'LATIN' in name or 0x400<=cp<=0x52f and ch not in 'ёЁ' and not 0x410<=cp<=0x44f)


def audit(root,hours=48):
    counts=Counter();characters=Counter();older=Counter();examples=[];audio_checks=[];latest=[];errors=Counter()
    cutoff=time.time()-hours*3600;flagged=set();tts_counts=Counter();special_tokens=Counter();special_examples=[]
    for p in sorted(Path(root).glob('*.tar')):
        try:
            with tarfile.open(p) as archive:
                member=archive.getmember('sample.json')
                if member.size>1048576:raise ValueError('oversized metadata')
                metadata=json.load(archive.extractfile(member));kind=metadata.get('kind');backend=metadata.get('backend','unknown')
                recent=metadata.get('collected_at_unix_ns',int(p.stat().st_mtime*1e9))/1e9>=cutoff
                if kind=='stt':
                    texts={stage:metadata.get(key,'') for stage,key in [('raw','raw_text'),('pre_dictionary','pre_dictionary_text'),('pre_cleanup','pre_cleanup_text'),('final','final_text')]}
                    if recent:counts[backend]+=1
                    raw=texts['raw'];final=texts['final']
                    if recent:
                        for match in re.finditer(r'<(?:unk|\\|[^>]{1,40})>',raw):
                            special_tokens[backend+':'+match.group()]+=1
                            if len(special_examples)<20:special_examples.append({'sample_id':metadata.get('sample_id'),'token':match.group(),'raw':raw,'final':final,'duration_s':metadata.get('audio_duration_s')})
                    unique_bad=[]
                    for stage,text in texts.items():
                        for index,ch in enumerate(text):
                            cp=ord(ch);name=u.name(ch,'unnamed')
                            if recent and ch in 'ёЁ':counts[stage+'_normal_yo']+=1
                            if recent and ch in 'еЕ' and text[index+1:index+2]=='\u0308':counts[stage+'_decomposed_yo']+=1
                            if not suspicious(ch):continue
                            key=f'{backend}:{stage}:U+{cp:04X}:{name}'
                            (characters if recent else older)[key]+=1
                            if stage=='raw':unique_bad.append(ch)
                            if recent and len(examples)<80 and stage in ['raw','final']:
                                examples.append({'sample_id':metadata.get('sample_id'),'backend':backend,'stage':stage,
                                  'char':ch,'codepoint':f'U+{cp:04X}','unicode_name':name,'context':text[max(0,index-45):index+46],
                                  'raw_contains_char':ch in raw,'final_contains_char':ch in final,'model_sha':metadata.get('model_sha256')})
                    if recent:latest.append({'sample_id':metadata.get('sample_id'),'backend':backend,'raw':raw,'final':final})
                    if recent and (unique_bad or '<unk>' in raw) and len(audio_checks)<12:
                        audio=archive.extractfile('original.wav').read();digest=hashlib.sha256(audio).hexdigest()
                        with wave.open(io.BytesIO(audio)) as w:
                            info={'duration_s':w.getnframes()/w.getframerate(),'sample_rate':w.getframerate(),'channels':w.getnchannels(),'sample_width':w.getsampwidth()}
                        audio_checks.append({'sample_id':metadata.get('sample_id'),'hash_ok':digest==metadata.get('audio_sha256'),
                                             'odd_raw_symbols':sorted(set(unique_bad)),**info})
                elif recent and kind=='tts_internal_stages':
                    for key in ['input_text','post_markdown_text','post_text_mode_text']:
                        text=metadata.get(key,'')
                        for ch in text:
                            if suspicious(ch):tts_counts[f'{key}:U+{ord(ch):04X}:{u.name(ch,"unnamed")}']+=1
        except (OSError,ValueError,KeyError,EOFError,TypeError,tarfile.TarError,wave.Error) as error:errors[type(error).__name__]+=1
    return {'measured_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'hours':hours,
            'recent_stt_counts':dict(counts),'recent_suspicious_codepoints':dict(characters),
            'older_suspicious_codepoints':dict(older),'examples':examples,'audio_checks':audio_checks,
            'latest12':latest[-12:],'recent_special_tokens':dict(special_tokens),'special_token_examples':special_examples,'recent_tts_suspicious_codepoints':dict(tts_counts),'errors':dict(errors),
            'no_service_changes':True,'no_content_replacements':True}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--hours',type=int,default=48);a=p.parse_args()
    print(json.dumps(audit(a.root,a.hours),ensure_ascii=False))
