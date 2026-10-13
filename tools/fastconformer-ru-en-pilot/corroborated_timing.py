"""Exact word agreement gates auxiliary timing, never final emitted words.

This is deliberately conservative and NOT a calibrated language detector.
No matched English words means explicit English abstention / all-Russian route.
"""
from english_timing import auxiliary_words


def corroborated_sequence(words, log_probs, processor, english_case):
    import numpy as np

    best=np.argmax(log_probs,axis=1)
    collapsed=[];previous=1024
    for frame,value in enumerate(best):
        token=int(value)
        if token!=previous and token!=1024:
            if not 0<token<1024:raise ValueError('Reserved greedy English label')
            collapsed.append({'token_id':token,'first_native_frame':frame})
        elif token==previous and token!=1024:
            collapsed[-1]['last_native_frame']=frame
        previous=token
    greedy_ids=[r['token_id'] for r in collapsed]
    greedy_text=processor.decode(greedy_ids)
    native_words=auxiliary_words(greedy_text)
    english=[(i,w) for i,w in enumerate(words) if w['role']=='english_timing']
    normalize=lambda s:s.lower() if english_case=='lower' else s
    aux=[normalize(w['original']) for _,w in english]
    native=[normalize(w) for w in native_words]
    # LCS over occurrences, not a set; a single acoustic occurrence cannot
    # validate an arbitrary number of repeated auxiliary occurrences.
    m,n=len(aux),len(native)
    lengths=np.zeros((m+1,n+1),dtype=np.int32)
    for i in range(m-1,-1,-1):
        for j in range(n-1,-1,-1):
            lengths[i,j]=1+lengths[i+1,j+1] if aux[i]==native[j] else max(lengths[i+1,j],lengths[i,j+1])
    matched=[];i=j=0
    while i<m and j<n:
        if aux[i]==native[j]:
            matched.append((i,j));i+=1;j+=1
        elif lengths[i+1,j]>=lengths[i,j+1]:i+=1
        else:j+=1
    if len(matched)!=int(lengths[0,0]):raise ValueError('Incomplete exact-word correspondence')
    if any(a[0]>=b[0] or a[1]>=b[1] for a,b in zip(matched,matched[1:])):raise ValueError('Repeated/reversed acoustic occurrence')
    accepted={english[i][0]:j for i,j in matched}
    sequence=[];provenance=[]
    for i,word in enumerate(words):
        if i in accepted:
            sequence.extend(('eng',t) for t in word['english_token_ids'])
            provenance.append({**word,'native_word_index':accepted[i],'corroborated':True})
        else:
            sequence.append(('rus',None))
            provenance.append({**word,'corroborated':False,'routing_role':'wildcard_gap'})
    return sequence,{
        'method':'ctc-corroborated-words-v1','greedy_english_text':greedy_text,
        'greedy_english_token_trace':collapsed,'greedy_english_words':native_words,
        'auxiliary_english_words':len(english),'corroborated_english_words':len(matched),
        'rejected_english_words':len(english)-len(matched),
        'matching':'maximum-cardinality monotone exact-word LCS; tie skips auxiliary occurrence',
        'words':provenance,'english_abstention':not matched,
        'all_russian_fallback_after_rejection':bool(english) and not matched,
        'not_calibrated_language_detection':True,'final_text_copied':False}
