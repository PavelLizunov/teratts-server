"""All-record compact mixed-head comparison, including proved all-RU reuse."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import statistics

from acoustic_cache import reuse_identity
from context_ablation_report import candidates
from corroborated_report import text
from corpus_report import comparison
from interval_context_report import contains
from mms_pair import digest, save


def observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round20.json';cfg=json.loads(mp.read_text());folder=Path(cfg['output'])
    sup=json.loads((folder/'supervisor-summary.json').read_text());cp=base/'round20-controls.json'
    if sup['status']!='completed' or digest(cp)!=cfg['controls_sha256']:raise ValueError('Incomplete run or changed controls')
    control=json.loads(cp.read_text());older={r['id']:r for r in json.loads((base/'round14-observation.json').read_text())['rows']}
    compact={r['id']:r for r in json.loads((base/'round19-observation.json').read_text())['rows']};ep=json.loads((Path(cfg['english_model'])/'prepared.json').read_text());vocab={int(k):v for k,v in ep['vocab'].items()}
    rows=[]
    for item in cfg['recordings']:
        clip=item['id'];path=folder/(clip+'.json');new=json.loads(path.read_text());old=json.loads(Path(item['prior_result']).read_text());source=older[clip]
        if digest(item['prior_result'])!=item['hashes']['prior_result'] or new['audio_sha256']!=old['audio_sha256']:raise ValueError('Changed baseline or originalaudio')
        if new['auxiliary_raw_text']!=old['auxiliary_raw_text']:raise ValueError('Auxiliary proposal changed')
        if new['encoder_rerun'] or new['audio_modified']:raise ValueError('Repeated encoder or changed waveform')
        result={'id':clip,'audio_sha256':new['audio_sha256'],'result_sha256':digest(path),'status':new['status'],
                'auxiliary_text':new['auxiliary_raw_text'],'archived_raw_not_gold':source['archived_raw_not_gold'],
                'old_mixed_text':text(old),'new_mixed_text':text(new),'new_english_whole_greedy':compact[clip]['new_english_greedy'],
                'old_candidates':candidates(old['search']),'new_candidates':candidates(new.get('search',{})) if new.get('search') else [],
                'old_intervals':old['alignment']['english_phrase_intervals'],'new_intervals':new.get('alignment',{}).get('english_phrase_intervals'),
                'old_en_events':old['alignment']['native_rows']['eng'],'new_en_events':new.get('alignment',{}).get('native_rows',{}).get('eng'),
                'new_decoder_run':new['new_decoder_run'],'decode_s':new.get('decode_s'),'elapsed_s':new['elapsed_s'],
                'peak_rss_mib':new['peak_rss_bytes']/1048576,'error':new.get('error'),'reuse_reason':new.get('prior_acoustic_reuse_reason'),
                'acoustic_identity':new['acoustic_identity']}
        if result['new_candidates']:
            search=new['search'];top=result['new_candidates'][0];prev=result['old_candidates'][0]
            if new['new_decoder_run'] and search['hint_paths']!=control['new_global_hints']:raise ValueError('New head hint mapping differs')
            if any(abs(c['total_score']-c['context_credit']-c['retained_same_text_logsum'])>1e-8 for c in result['new_candidates']):raise ValueError('Score decomposition failed')
            same=new['alignment']['selected_events']==old['alignment']['selected_events']
            if not new['new_decoder_run']:
                if not same or new['search']!=old['search'] or not reuse_identity(old,item['hashes'],new['alignment']['selected_events'],'global-fixed'):raise ValueError('Unproved reuse')
                if result['new_en_events']!=0:raise ValueError('Unexpected old English-head reuse')
            if any(t==0 or t==1024 or not 0<t<1058 for t in top['token_ids']):raise ValueError('Forbidden trained token')
            phrases=[''.join(vocab[t] for t in p).replace('▁',' ').strip() for p in new['alignment']['english_phrases']]
            result.update(same_route=same,changed_text=result['old_mixed_text']!=result['new_mixed_text'],
                          changed_casefold_text=result['old_mixed_text'].casefold()!=result['new_mixed_text'].casefold(),
                          russian_tokens_changed=[t for t in prev['token_ids'] if t>=1025]!=[t for t in top['token_ids'] if t>=1025],
                          new_phrase_spellings=phrases,old_proposal_matches=[contains(result['old_mixed_text'],p) for p in phrases],
                          new_proposal_matches=[contains(result['new_mixed_text'],p) for p in phrases],
                          agreement_not_accuracy=comparison(result['new_mixed_text'],source['archived_raw_not_gold']),
                          state_stats=search['state_stats'])
        rows.append(result)
    samples=[s for r in sup['rows'] for s in r['samples']];complete=[r for r in rows if r['new_candidates']];fresh=[r for r in rows if r['new_decoder_run']]
    stats={'records':len(rows),'complete_outputs':len(complete),'new_decodes':len(fresh),'proved_reuses':len(complete)-len(fresh),
           'failures':[{'id':r['id'],'status':r['status'],'error':r['error']} for r in rows if not r['new_candidates']],
           'exact_prior_routes':sum(r['same_route'] for r in complete),'changed_routes':[r['id'] for r in complete if not r['same_route']],
           'english_route_records':sum(r['new_en_events']>0 for r in complete),'all_russian_records':sum(r['new_en_events']==0 for r in complete),
           'changed_texts':[r['id'] for r in complete if r['changed_text']],
           'changed_casefold_texts':[r['id'] for r in complete if r['changed_casefold_text']],
           'changed_russian_tokens':[r['id'] for r in complete if r['russian_tokens_changed']],
           'phrases':sum(len(r['new_phrase_spellings']) for r in complete),
           'prior_proposal_matches':sum(sum(r['old_proposal_matches']) for r in complete),
           'new_proposal_matches':sum(sum(r['new_proposal_matches']) for r in complete),
           'agreement_not_accuracy':dict(Counter(r['agreement_not_accuracy']['category'] for r in complete)),
           'batch_wall_s':sup['elapsed_s'],'new_decode_sum_s':sum(r['decode_s'] for r in fresh),
           'new_decode_median_s':statistics.median(r['decode_s'] for r in fresh) if fresh else None,
           'new_decode_max_s':max((r['decode_s'] for r in fresh),default=0),
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'max_new_states':max((r['state_stats']['max_states'] for r in fresh if r['new_candidates']),default=0),
           'new_encoder_or_auxiliary_calls':0,'human_gold_records':0}
    value={'statistics':stats,'rows':rows,'controls':control,'source_commit':cfg['source_commit'],'manifest_sha256':digest(mp)}
    save(base/'round20-observation.json',value);return value


def section(root):
    value=json.loads((root.parent/'routing-repair/round20-observation.json').read_text());s=value['statistics'];esc=lambda x:html.escape(str(x));table=[];details=[];hints=[]
    for old,new in zip(value['controls']['prior_global_hints'],value['controls']['new_global_hints']):
        hints.append('<tr><td>'+esc(new['hint'])+'</td><td>'+str(len(old['context_symbols'])*2.5)+'</td><td>'+str(len(new['context_symbols'])*2.5)+'</td></tr>')
    for r in value['rows']:
        table.append('<tr><td>'+r['id']+'</td><td>'+('новый поиск' if r['new_decoder_run'] else esc(r['status']))+'</td><td>'+str(r['old_en_events'])+' → '+str(r['new_en_events'])+'</td><td>'+esc(r['old_mixed_text'])+'</td><td>'+esc(r['new_mixed_text'] or r['error'])+'</td></tr>')
        details.append('<details><summary>'+r['id']+' · маршруты, источник и top4</summary><p><b>Неизменённый Qwen:</b> '+esc(r['auxiliary_text'])+'<br><b>Архив, не gold:</b> '+esc(r['archived_raw_not_gold'])+'<br><b>Новая английская акустика wholegreedy, не bilingual:</b> '+esc(r['new_english_whole_greedy'])+'</p>')
        details.append('<p>Старые интервалы '+esc(r['old_intervals'])+'<br>Новые интервалы '+esc(r['new_intervals'])+'<br>Основание reuse '+esc(r['reuse_reason'])+'; RU IDs изменились '+esc(r.get('russian_tokens_changed'))+'.</p>')
        for title,key in [('CTC0.6B + прежний globalcontext','old_candidates'),('CTC110M + recomputedtiming/globalcontext','new_candidates')]:
            details.append('<h4>'+title+'</h4><div class="scroll"><table><thead><tr><th>№</th><th>Текст</th><th>Acoustic retained mass</th><th>Credit</th><th>Total</th></tr></thead><tbody>')
            for i,c in enumerate(r[key],1):details.append('<tr><td>'+str(i)+'</td><td>'+esc(c['postprocessed_text'])+'</td>'+''.join('<td>'+format(c[k],'.5f')+'</td>' for k in ('retained_same_text_logsum','context_credit','total_score'))+'</tr>')
            details.append('</tbody></table></div>')
        details.append('</details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 20 · КОМПАКТНАЯ EN-ГОЛОВА В СМЕШАННОМ ПОИСКЕ</p>
<h2>Компактная связка проверена. Замену не рекомендую.</h2>
<p><b>Нужного улучшения нет:</b> ChatGPT Pro в c027 сохранился с исходным регистром, но ChatGPT в c028 потерялся, Gemini в c005 превратилось в Germini. GitHub не восстановился в c009/c015/c022. В c003 вместо прежнего неверного DSH теперь GBT — это другая ошибка, не исправление. Ошибочная латинизация русской речи в c002 осталась.</p>
<p>Пересчёт границ исправил именно несовместимость старого участка с новой эмиссией clear: c020 перешёл с одного кадра58 (4.60–4.68с) на кадры57–59 (4.52–4.76с). Итоговая строка осталась прежней, включая лишнее «к» после clear. В c018 при DSH появился добавочный русский фрагмент «эйч». Русский токенный путь изменился также в c009/c015. По одним итоговым строкам нельзя доказать, какие русские эмиссии вызвали повтор: временной след RU-предиктора ещё не разобран.</p>
<p>Совпадение с Qwen-фразами снизилось с5/11до3/11: остались GPT, clear и ChatGPT Pro; потерялись Gemini и ChatGPT. Это зависимое модельное согласие, не оценка человеческой точности. Последние интервальные варианты раундов16/18 имели другое контекстное правило и здесь не являются сопоставимым baseline.</p>
<p>Обработаны все{s['records']}записи; полных outputs{s['complete_outputs']}, новых mixeddecodes{s['new_decodes']}, доказанных all-RUreuses{s['proved_reuses']}. Новых энкодерных/Qwenпроходов0. Изменились маршруты{esc(s['changed_routes'])}; ENмаршрутов{s['english_route_records']}, all-RU{s['all_russian_records']}. Отказы{esc(s['failures'])}. Покрытие не равно точности или двуязычному успеху.</p>
<p>Сравнение с раундом14: те же Qwenтексты, GigaAMv3RNNT, глобальные четыре имени, score2.5 и открытый trainedvocabulary. Сменились английскийcheckpoint0.6Bint8→110MF32, его исходный регистр/токенизация и автоматически выведенные границы. Интервальные подсказки раундов16/18 здесь не используются. Это проверка новой комбинации, не изолированная причина улучшения/ухудшения.</p>
<p>Изменённые строки{esc(s['changed_texts'])}; даже после casefold{esc(s['changed_casefold_texts'])}; изменённые русскиеIDs{esc(s['changed_russian_tokens'])}. Casefold — только сравнение, не постобработка. Буквальное совпадение с11QwenENфразами: {s['prior_proposal_matches']}/{s['phrases']} → {s['new_proposal_matches']}/{s['phrases']}; связанное модельное agreement, не goldaccuracy. Архивноеagreement{esc(s['agreement_not_accuracy'])} тоже неWER.</p>
<h3>Все28сравнений</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Исполнение</th><th>ENкадры до/после</th><th>Прежняя пара</th><th>Новая пара</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<h3>Прежние подсказки, но другой trainedtokenizer</h3><p>Общий список не менялся, GitHub не добавлялся. Полная изолированная премия за каноническую подсказку зависит от числа контекстных символов; вложенные/повторные подсказки сохраняют прежние правила общего покрытия. Изменение этого бюджета явно учтено, а не спрятано за одинаковым coefficient2.5.</p><table><thead><tr><th>Hint</th><th>CTC0.6B</th><th>CTC110M</th></tr></thead><tbody>{''.join(hints)}</tbody></table>
<h3>Почему18русских выходов не запускались заново</h3><p>Кэш теперь требует совпадения не только selectedevents, но и проверенных акустических receipts. При любом ENсобытии разные Englishheads запрещают reuse. Полностью русский маршрут допускает reuse только при тех жеRUданных/событиях, globalcontext/score, исключительно RUtokenIDs, нулевой итоговой премии и EN-onlyhintpaths. Английские полные подсказки не могут завершиться в таком потоке. Сохранённые search/hints у reusedвыходов остаются историческими, не объявлены newheadoutputs. Недостающая provenance запрещает reuse.</p>
<p>До запуска прошли9cacheконтролей и2array-schemaконтроля; все28Qwenтекстов представимы новымtokenizer. ChangedEN/sameroute, changedRU, missingidentity, ENoutputonRUroute, nonzerocredit и RUhint отвергаютreuse. Это проверки механизма, не речи. Новые receipts содержат отдельные prepared/array/receiptSHA для обоих голов. Оригинальные NPZ не перепаковывались; поддержаны keys values/log_probs, неизвестныйEN0маскируется передпоиском.</p>
<h3>Ресурсы и нерешённое</h3><p>Hostfinal-stagewall{s['batch_wall_s']:.3f}с; новыеdecodes сумма{s['new_decode_sum_s']:.3f}с, медиана{s['new_decode_median_s']:.3f}с, max{s['new_decode_max_s']:.3f}с. High-waterRSS{s['max_highwater_rss_mib']:.2f}MiB,sampled{s['max_sampled_rss_mib']:.2f}MiB,minavailable{s['minimum_available_mib']:.2f}MiB,swapgrowth{s['max_swap_growth_mib']:.3f}MiB,maxnewstates{s['max_new_states']}. Лимиты1536MiB/резерв2048MiB — агентские, не выделенная память. Ресурсы раунда19 отдельно: их сумма не является измеренной полной цепочкой или Deckзамером.</p>
<p>Финальные токены остаются из trainedEN/RUголов; русскийpredictor продолжает свою nativeисторию, форматирование отделено от rawpieces. Это не совместно обученная bilingualмодель и не независимый language-detector. Qwenошибки языка/имён и forcedphraseграницы остаются возможными. Humanreferences0; успешный поиск не доказывает usableaccuracy. Production, gateway, словарь и исходныеWAVне изменены. Источник <code>{esc(value['source_commit'])}</code>.</p>
<h3>Все источники, границы и альтернативы</h3>{''.join(details)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
