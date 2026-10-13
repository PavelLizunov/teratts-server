"""Compare every spelling-context output with its retained token-context route."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import statistics

from context_ablation_report import candidates
from corroborated_report import text
from corpus_report import comparison
from interval_context_report import contains
from mms_pair import digest, save


def observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round18.json';cfg=json.loads(mp.read_text());folder=Path(cfg['output'])
    sup=json.loads((folder/'supervisor-summary.json').read_text());control_path=base/'round18-controls.json'
    if sup['status']!='completed':raise ValueError('Spelling batch not completed')
    if digest(control_path)!=cfg['controls_sha256']:raise ValueError('Changed controls')
    control=json.loads(control_path.read_text());older={r['id']:r for r in json.loads((base/'round16-observation.json').read_text())['rows']}
    rows=[]
    for item in cfg['recordings']:
        if digest(item['prior_result'])!=item['hashes']['prior_result']:raise ValueError('Changed prior result')
        old=json.loads(Path(item['prior_result']).read_text());path=folder/(item['id']+'.json');new=json.loads(path.read_text());search=new['search'];prior=old['search'];source=older[item['id']]
        if new['status']!='new_constrained_output' or not new['new_decoder_run']:raise ValueError('Missing new decode')
        if new['alignment']!=old['alignment']:raise ValueError('Changed timing or phrase alignment')
        if search['interval_context_graph_ids']!=prior['interval_context_graph_ids']:raise ValueError('Changed context schedule')
        if search['context_mode']!='auxiliary-spelling-interval-v1' or search['context_score']!=2.5:raise ValueError('Changed context mode/score')
        if not search['all_trained_non_special_tokens_considered'] or not search['credit_partitioned_state']:raise ValueError('Closed or merged search')
        if len(search['hint_paths'])!=len(prior['hint_paths']):raise ValueError('Changed phrase count')
        for h,prev in zip(search['hint_paths'],prior['hint_paths']):
            if h['token_ids']!=prev['token_ids'] or h['context_symbols']!=prev['context_symbols']:raise ValueError('Changed phrase spelling')
            if h['original_completion_credit']!=2.5*len(prev['context_symbols']) or sum(h['spelling_unit_weights'])*2.5!=h['original_completion_credit']:raise ValueError('Changed full reward budget')
        now=candidates(search);before=candidates(prior);top=now[0];oldtop=before[0]
        if any(abs(c['total_score']-c['retained_same_text_logsum']-c['context_credit'])>1e-8 or c['context_credit']/2.5!=round(c['context_credit']/2.5) for c in now):raise ValueError('Invalid score/credit accounting')
        current=text(new);previous=text(old);phrases=[h['spelling'] for h in search['hint_paths']]
        rows.append({'id':item['id'],'audio_sha256':new['audio_sha256'],'new_sha256':digest(path),
                     'auxiliary_text':new['auxiliary_raw_text'],'archived_raw_not_gold':source['archived_raw_not_gold'],
                     'token_context_text':previous,'spelling_context_text':current,'context_phrases':phrases,
                     'context_paths':search['hint_paths'],'token_candidates':before,'spelling_candidates':now,
                     'changed_text':current!=previous,'changed_tokens':top['token_ids']!=oldtop['token_ids'],
                     'changed_russian_tokens':[t for t in top['token_ids'] if t>=1025]!=[t for t in oldtop['token_ids'] if t>=1025],
                     'changed_english_tokens':[t for t in top['token_ids'] if t<1025]!=[t for t in oldtop['token_ids'] if t<1025],
                     'prior_matches':[contains(previous,p) for p in phrases],'new_matches':[contains(current,p) for p in phrases],
                     'agreement_not_accuracy':comparison(current,source['archived_raw_not_gold']),
                     'decode_s':new['decode_s'],'prior_decode_s':old['decode_s'],
                     'peak_rss_mib':new['peak_rss_bytes']/1048576,'state_stats':search['state_stats'],
                     'duplicate_top4_texts':len(now)-len({c['postprocessed_text'] for c in now})})
    samples=[s for r in sup['rows'] for s in r['samples']]
    stats={'records':len(rows),'new_decodes':len(rows),'exact_prior_alignments':len(rows),
           'phrases':sum(len(r['context_phrases']) for r in rows),
           'changed_texts':[r['id'] for r in rows if r['changed_text']],
           'changed_tokens':[r['id'] for r in rows if r['changed_tokens']],
           'changed_russian_tokens':[r['id'] for r in rows if r['changed_russian_tokens']],
           'changed_english_tokens':[r['id'] for r in rows if r['changed_english_tokens']],
           'prior_phrase_matches':sum(sum(r['prior_matches']) for r in rows),'new_phrase_matches':sum(sum(r['new_matches']) for r in rows),
           'duplicate_top4_text_records':[r['id'] for r in rows if r['duplicate_top4_texts']],
           'agreement_not_accuracy':dict(Counter(r['agreement_not_accuracy']['category'] for r in rows)),
           'batch_wall_s':sup['elapsed_s'],'decode_sum_s':sum(r['decode_s'] for r in rows),
           'decode_median_s':statistics.median(r['decode_s'] for r in rows),'decode_max_s':max(r['decode_s'] for r in rows),
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'max_states':max(r['state_stats']['max_states'] for r in rows),
           'new_auxiliary_or_encoder_calls':0,'excluded_all_russian':len(cfg['excluded_records']),'human_gold_records':0}
    result={'statistics':stats,'rows':rows,'controls':control,'source_commit':cfg['source_commit'],'manifest_sha256':digest(mp)}
    save(base/'round18-observation.json',result);return result


def section(root):
    value=json.loads((root.parent/'routing-repair/round18-observation.json').read_text());s=value['statistics'];c=value['controls'];esc=lambda x:html.escape(str(x))
    table=[];detail=[]
    for r in value['rows']:
        table.append('<tr><td>'+r['id']+'</td><td>'+esc(' / '.join(r['context_phrases']))+'</td><td>'+esc(r['token_context_text'])+'</td><td>'+esc(r['spelling_context_text'])+'</td><td>'+format(r['decode_s'],'.3f')+'</td></tr>')
        detail.append('<details><summary>'+r['id']+' · источник, премии и все альтернативы</summary><p><b>Qwen, не gold:</b> '+esc(r['auxiliary_text'])+'<br><b>Raw production, не gold:</b> '+esc(r['archived_raw_not_gold'])+'</p>')
        detail.append('<p>Изменение RU IDs: '+esc(r['changed_russian_tokens'])+'; EN IDs: '+esc(r['changed_english_tokens'])+'. Max states '+esc(r['state_stats']['max_states'])+'.</p>')
        for h in r['context_paths']:
            detail.append('<p>Фраза '+esc(h['spelling'])+'; прежняя полная премия '+esc(h['original_completion_credit'])+'; целочисленные веса границ/букв '+esc(h['spelling_unit_weights'])+'.</p>')
        for label,key in [('Прежний token-context','token_candidates'),('Новый spelling-context','spelling_candidates')]:
            detail.append('<h4>'+label+'</h4><div class="scroll"><table><thead><tr><th>№</th><th>Текст</th><th>Retained acoustic</th><th>Credit</th><th>Total</th><th>Trained IDs</th></tr></thead><tbody>')
            for i,row in enumerate(r[key],1):
                detail.append('<tr><td>'+str(i)+'</td><td>'+esc(row['postprocessed_text'])+'</td>'+''.join('<td>'+format(row[k],'.6f')+'</td>' for k in ('retained_same_text_logsum','context_credit','total_score'))+'<td>'+esc(row['token_ids'])+'</td></tr>')
            detail.append('</tbody></table></div>')
        detail.append('</details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 18 · ПОДСКАЗКА ПО НАПИСАНИЮ</p>
<h2>Премия исправлена, но ни одна итоговая строка не улучшилась.</h2>
<p><b>Итог: все десять top1текстов остались прежними.</b> В пяти случаях изменились EN-token пути того же написания, русские IDs не изменились ни в одном. GitHub в c009 по-прежнему повреждён; c022 сохраняет «гид github»; c018 сохраняет ошибочное GSH; c002 остаётся латинизацией русского. ChatGPT/ChatGPT Pro и ранее появившиеся GitHub/GPT тоже сохранены. Это механическое исправление представления, не улучшение ASR на данном наборе.</p>
<p>Устранено конкретное неравенство премии между двумя наборами IDs для GPT. Однако разные токенизации текста всё ещё max-конкурируют, а не объединяются в единую вероятность написания. Полный перебор всех английских написаний или исправление языковых границ этим прогоном не выполнены. Не переключать baseline/production на основании этого результата.</p>
<p>Все {s['new_decodes']} новых поисков завершены. Все {s['exact_prior_alignments']} прежних alignments и расписаний контекста совпали; полная премия за каждую из {s['phrases']} фраз не изменилась. Никаких ручных имён, новых энкодерных/Qwen-проходов, сдвига границ или подмены output IDs.</p>
<p>Изменились строки {esc(s['changed_texts'])}, полные trained-token пути {esc(s['changed_tokens'])}; русские пути {esc(s['changed_russian_tokens'])}. Буквальное совпадение с Qwen-подсказками {s['prior_phrase_matches']}/{s['phrases']} → {s['new_phrase_matches']}/{s['phrases']}. Это связанное с подсказкой совпадение, не точность. Production и прежние режимы сохранены.</p>
<h3>Все десять сравнений</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Подсказка</th><th>Прежние токены</th><th>Новое сопоставление написания</th><th>Decode, с</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<h3>Что именно изменено</h3><p>Контекст видит символы, реально выданные обученными EN-токенами. Начальный SentencePiece-маркер, пробелы и пунктуация категории PZS, кроме апострофа, обозначают контекстную границу слова. Нет исправления регистра, транслитерации, синонимов или приблизительного совпадения. Совпасть должно полное написание в своём прежнем интервале; vocabulary остаётся открытым.</p>
<p>Прежняя единица премии2.5 сохранена. Внешние границы получают по одной единице, оставшийся прежний бюджет распределён по символам целыми единицами через накопительное округление вниз. Полный бюджет не увеличен; промежуточная форма премии меняется и может повлиять на pruning. Все накопления — точные кратные2.5, без дробных ключей и округлительных различий между токенизациями. Неоконченные/ошибочные префиксы возвращают заёмную премию, общие покрытые символы при повторном совпадении не оплачиваются второй раз.</p>
<p>Контроли до корпуса: {c['all_chunkings']} разбиения «alpha» с равенством каждого общего символьного префикса; {len(c['cases'])} случаев полного/неполного/чужого/вложенного слова, пунктуации, повторов и EOS; ноль вне интервала и при попытке продолжить через другой интервал; слабая подсказка проигрывает альтернативе в маленьком открытом поиске. Все11прежних полных бюджетов проверены отдельно. Реальные GPT IDs [41,287] и [41,1015,998] теперь получают10и10 вместо10и0. Это численные контроли, не human gold или полный decoder parity.</p>
<h3>Ресурсы и ограничения</h3><p>Host final-only supervised {s['batch_wall_s']:.3f}с, decode sum {s['decode_sum_s']:.3f}с, median {s['decode_median_s']:.3f}с, max {s['decode_max_s']:.3f}с. High-water RSS {s['max_highwater_rss_mib']:.2f}MiB, sampled {s['max_sampled_rss_mib']:.2f}MiB; минимум доступно {s['minimum_available_mib']:.2f}MiB, swap growth {s['max_swap_growth_mib']:.3f}MiB. Max states {s['max_states']}. Лимиты1536MiB/резерв2048MiB — агентские границы, не выделенная память. Не Deck, не полный cold pipeline, не доказательство ускорения.</p>
<p>Новые aux/encoder calls0; {s['excluded_all_russian']} прежних all-RU маршрутов не запускались. Архивное agreement {esc(s['agreement_not_accuracy'])}, gold0. Разные токенизации одного текста НЕ суммируются в единую текстовую вероятность; approximate search по-прежнему max-конкурирует разные output IDs. Совпадение строк в top4: {esc(s['duplicate_top4_text_records'])}; такие строки не независимые гипотезы. Ошибки языка/написания Qwen и неверные границы этот механизм сам по себе не устраняет.</p>
<p>Источник <code>{esc(value['source_commit'])}</code>. Исходные акустические токены, премия и форматирование сохранены отдельно. Новую схему нельзя объявлять решением непрерывного двуязычного ASR только на основании корректного учёта премии.</p>
<h3>Сохранённые варианты и provenance</h3>{''.join(detail)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
