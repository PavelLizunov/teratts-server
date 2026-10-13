"""Private fixed-route context intervention, not an ASR accuracy benchmark."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re
import statistics

from corroborated_report import english_words, text
from corpus_report import comparison
from mms_pair import HINTS, digest, save


def hints(value):
    # Diagnostic literal spelling only; nested configured phrases may both match.
    return [hint for hint in HINTS if re.search(r'(?<![a-z])'+re.escape(hint.casefold())+r'(?![a-z])',value.casefold())]


def candidates(search):
    return [{k:h[k] for k in ('token_ids','raw_text','postprocessed_text','retained_same_text_logsum','context_credit','total_score')}
            for h in search['hypotheses']]


def observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round15.json';cfg=json.loads(mp.read_text());out=Path(cfg['output'])
    sup=json.loads((out/'supervisor-summary.json').read_text())
    if sup['status']!='completed':raise ValueError('Incomplete control batch')
    originals={r['id']:r for r in json.loads((root.parent/'collected-evaluation/comparison-final.json').read_text())['records']}
    rows=[]
    for r in cfg['recordings']:
        if digest(r['prior_result'])!=r['hashes']['prior_result']:raise ValueError('Prior result changed')
        before=json.loads(Path(r['prior_result']).read_text());path=out/(r['id']+'.json');after=json.loads(path.read_text())
        if after['status']!='new_constrained_output' or not after['new_decoder_run']:raise ValueError('Not a new finished control')
        if before['alignment']['selected_events']!=after['alignment']['selected_events']:raise ValueError('Route changed')
        if before['audio_sha256']!=after['audio_sha256']:raise ValueError('Different original audio')
        bs,ns=before['search'],after['search']
        if bs['context_score']!=2.5 or ns['context_score']!=0 or ns['hint_paths']:raise ValueError('Unexpected context variant')
        if any(h['context_credit']!=0. or h['total_score']!=h['retained_same_text_logsum'] for h in ns['hypotheses']):raise ValueError('Residual context credit in disabled variant')
        old,new=text(before),text(after);oc,nc=candidates(bs),candidates(ns)
        old_en,new_en=Counter(english_words(old)),Counter(english_words(new))
        bh,nh=oc[0],nc[0]
        old_off_best=max(oc,key=lambda h:h['retained_same_text_logsum'])
        rows.append({'id':r['id'],'audio_sha256':after['audio_sha256'],'prior_sha256':digest(r['prior_result']),
                     'new_sha256':digest(path),'old_text':old,'new_text':new,'auxiliary_text':after['auxiliary_raw_text'],
                     'archived_raw_not_gold':originals[r['id']]['raw_text'],'text_changed':old!=new,
                     'russian_tokens_identical':[t for t in bh['token_ids'] if t>=1025]==[t for t in nh['token_ids'] if t>=1025],
                     'english_tokens_identical':[t for t in bh['token_ids'] if t<1025]==[t for t in nh['token_ids'] if t<1025],
                     'old_candidates':oc,'new_candidates':nc,
                     'top4_zero_credit_rescore_text':old_off_best['postprocessed_text'],
                     'top4_zero_credit_rescore_matches_new':old_off_best['token_ids']==nh['token_ids'],
                     'new_top_token_path_in_old_top4':any(h['token_ids']==nh['token_ids'] for h in oc),
                     'old_hint_spellings':hints(old),'new_hint_spellings':hints(new),
                     'missing_old_english_words':list((old_en-new_en).elements()),'added_english_words':list((new_en-old_en).elements()),
                     'old_agreement_not_accuracy':comparison(old,originals[r['id']]['raw_text']),
                     'new_agreement_not_accuracy':comparison(new,originals[r['id']]['raw_text']),
                     'old_state_stats':bs['state_stats'],'new_state_stats':ns['state_stats'],
                     'native_rows':after['alignment']['native_rows'],'decode_s':after['decode_s'],
                     'peak_rss_mib':after['peak_rss_bytes']/1048576})
    samples=[s for r in sup['rows'] for s in r['samples']]
    stats={'records':len(rows),'new_decodes':len(rows),'exact_prior_routes':len(rows),'zero_credit_outputs':len(rows),
           'excluded_all_russian_records':len(cfg['excluded_records']),'new_audio_encoder_or_auxiliary_passes':0,
           'changed_text_records':[r['id'] for r in rows if r['text_changed']],
           'changed_russian_token_records':[r['id'] for r in rows if not r['russian_tokens_identical']],
           'changed_english_token_records':[r['id'] for r in rows if not r['english_tokens_identical']],
           'new_top_not_in_old_top4':[r['id'] for r in rows if not r['new_top_token_path_in_old_top4']],
           'old_top4_score_subtraction_matches':sum(r['top4_zero_credit_rescore_matches_new'] for r in rows),
           'old_hint_record_matches':dict(Counter(h for r in rows for h in r['old_hint_spellings'])),
           'new_hint_record_matches':dict(Counter(h for r in rows for h in r['new_hint_spellings'])),
           'old_agreement_not_accuracy':dict(Counter(r['old_agreement_not_accuracy']['category'] for r in rows)),
           'new_agreement_not_accuracy':dict(Counter(r['new_agreement_not_accuracy']['category'] for r in rows)),
           'batch_wall_s':sup['elapsed_s'],'decode_sum_s':sum(r['decode_s'] for r in rows),
           'decode_median_s':statistics.median(r['decode_s'] for r in rows),
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),
           'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'old_max_states':max(r['old_state_stats']['max_states'] for r in rows),
           'new_max_states':max(r['new_state_stats']['max_states'] for r in rows),'human_gold_records':0}
    value={'statistics':stats,'rows':rows,'excluded_records':cfg['excluded_records'],'manifest_sha256':digest(mp),
           'source_commit':cfg['source_commit'],'interpretation':'fixed-route context component intervention including state retention; no exact posterior/accuracy claim'}
    save(base/'round15-observation.json',value);return value


def section(root):
    value=json.loads((root.parent/'routing-repair/round15-observation.json').read_text());s=value['statistics'];esc=lambda v:html.escape(str(v))
    table_rows=[];details=[]
    for r in value['rows']:
        old,new=r['old_candidates'][0],r['new_candidates'][0]
        table_rows.append('<tr><td>'+r['id']+'</td><td>'+esc(r['old_text'])+'</td><td>'+esc(r['new_text'])+'</td><td>'+format(old['context_credit'],'.1f')+'</td></tr>')
        details.append('<details><summary>'+r['id']+' · оценки и все сохранённые альтернативы</summary>')
        details.append('<p><b>Qwen — не эталон:</b> '+esc(r['auxiliary_text'])+'<br><b>Raw production — не эталон:</b> '+esc(r['archived_raw_not_gold'])+'</p>')
        details.append('<p>Неизменные RU-токены: '+esc(r['russian_tokens_identical'])+'. Неизменные EN-токены: '+esc(r['english_tokens_identical'])+'. Новый лучший путь есть в прежнем top4: '+esc(r['new_top_token_path_in_old_top4'])+'. RU/EN кадры: '+esc(r['native_rows'])+'.</p>')
        details.append('<div class="scroll"><table><thead><tr><th>Вариант / место</th><th>Текст с отдельным форматированием пробелов</th><th>Retained acoustic logsum</th><th>Context credit</th><th>Total</th></tr></thead><tbody>')
        for label,key in [('Бонус 2.5','old_candidates'),('Бонус 0','new_candidates')]:
            for i,c in enumerate(r[key],1):
                details.append('<tr><td>'+label+' / '+str(i)+'</td><td>'+esc(c['postprocessed_text'])+'</td><td>'+format(c['retained_same_text_logsum'],'.6f')+'</td><td>'+format(c['context_credit'],'.3f')+'</td><td>'+format(c['total_score'],'.6f')+'</td></tr>')
        details.append('</tbody></table></div><p>Время нового decode '+format(r['decode_s'],'.3f')+' с; максимум состояний '+str(r['old_state_stats']['max_states'])+' → '+str(r['new_state_stats']['max_states'])+'. Акустическая сумма приблизительная: изменился отбор путей. Это не точное отношение правдоподобий.</p></details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 15 · ФИКСИРОВАННЫЕ ИНТЕРВАЛЫ, КОНТЕКСТ ВЫКЛЮЧЕН</p>
<h2>Отделяем влияние подсказок от выбора языковых интервалов.</h2>
<p>Один новый вариант: context_score 0 вместо сохранённого 2.5. Взяты все {s['records']} маршрутов Qwen с английскими кадрами, не только записи с неудобным результатом. Остальные {s['excluded_all_russian_records']} полностью русских маршрутов не запускались и не входят в знаменатель этой проверки. Новых вызовов Qwen и акустических энкодеров — 0; новых финальных декодирований — {s['new_decodes']}.</p>
<p>Во всех {s['exact_prior_routes']} случаях до и после строго совпал полный список native событий. Исходные trained IDs, русский predictor/history beam4, английские CTC-вероятности и правила переходов прежние. Все {s['zero_credit_outputs']} новых результатов имеют ровно нулевой context credit. Не было подбора коэффициента, добавления имён, исправления строк или объединения лучших фрагментов.</p>
<p>Текст изменился в {len(s['changed_text_records'])}/{s['records']}: {esc(', '.join(s['changed_text_records']))}. Русская последовательность trained IDs изменилась в {len(s['changed_russian_token_records'])}, английская — в {len(s['changed_english_token_records'])}. Наличие буквального написания фиксированных hints до: {esc(s['old_hint_record_matches'])}; после: {esc(s['new_hint_record_matches'])}. Это количество записей с написанием, не доля правильно узнанных имён; вложенные ChatGPT и ChatGPT Pro могут учитываться вместе.</p>
<h3>Все десять результатов</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Прежний бонус 2.5</th><th>Новый бонус 0</th><th>Прежняя премия</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h3>Что именно изолировано</h3><p>Выключен компонент контекстного поиска, а не только прибавка к четырём финальным строкам. В реализации при бонусе0 исчезает контекстный автомат: меняются ключи объединения и удержание промежуточных путей. Поэтому причинный вывод относится к компоненту целиком; чистое влияние финальной арифметической премии отдельно не измерено.</p>
<p>Новый лучший token path отсутствует в прежнем top4 в {len(s['new_top_not_in_old_top4'])}/{s['records']} случаях. Простое вычитание сохранённого credit из прежних top4 воспроизвело новый лучший token path в {s['old_top4_score_subtraction_matches']}/{s['records']}; это пересортировка записанных чисел, а не новые модельные вызовы. Retained acoustic logsum не является точным posterior; разные поиски могут сохранить разную массу одного текста. Контекст оплачивает также маркеры границ — его величина не уверенность в слове.</p>
<h3>Согласие и ресурсные границы</h3><p>Согласие с архивным raw ASR до: {esc(s['old_agreement_not_accuracy'])}; после: {esc(s['new_agreement_not_accuracy'])}. Человеческих эталонов0, WER не вычислялся. Ни Qwen, ни production не назначены эталоном; варианты не продвигаются по этим числам.</p>
<p>Host final-only серия {s['batch_wall_s']:.3f} с; сумма десяти decode {s['decode_sum_s']:.3f} с, медиана {s['decode_median_s']:.3f} с. High-water RSS {s['max_highwater_rss_mib']:.2f} MiB, sampled peak {s['max_sampled_rss_mib']:.2f} MiB; минимум доступно {s['minimum_available_mib']:.2f} MiB, рост swap {s['max_swap_growth_mib']:.3f} MiB. Лимит процесса1536MiB и свободный резерв2048MiB не равны выделенной памяти. Максимум состояний {s['old_max_states']} → {s['new_max_states']}. Сокращение состояний не доказывает ускорение полноценной ASR-цепочки; старые времена получены в других запусках.</p>
<p>Это не новый замер Deck и не полная цепочка с загрузкой Qwen/энкодеров. Production, словарь, исходные WAV и прежние результаты сохранены. Источник до запуска: <code>{esc(value['source_commit'])}</code>. Подробные оценки ниже включают все сохранённые альтернативы, а не выбранные удачные фрагменты.</p>
<h3>Все сохранённые альтернативы</h3>{''.join(details)}</section>'''


def graph_observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round15-graph.json';cfg=json.loads(mp.read_text())
    primary=json.loads((base/'round15-observation.json').read_text());originals={r['id']:r for r in primary['rows']}
    out=Path(cfg['output']);sup=json.loads((out/'supervisor-summary.json').read_text());rows=[]
    if sup['status']!='completed':raise ValueError('Graph-control batch incomplete')
    for item in cfg['recordings']:
        old=originals[item['id']];path=out/(item['id']+'.json');result=json.loads(path.read_text());search=result['search']
        if digest(item['prior_result'])!=item['hashes']['prior_result']:raise ValueError('Changed prior')
        before=json.loads(Path(item['prior_result']).read_text())
        if result['alignment']['selected_events']!=before['alignment']['selected_events']:raise ValueError('Changed graph-control route')
        if not result['new_decoder_run'] or result['status']!='new_constrained_output':raise ValueError('Not new graph decode')
        if search['context_score']!=0. or not search['retain_context_graph'] or search['hint_paths']!=before['search']['hint_paths']:raise ValueError('Graph-control mismatch')
        if any(h['context_credit']!=0. or h['total_score']!=h['retained_same_text_logsum'] for h in search['hypotheses']):raise ValueError('Unexpected graph credit')
        cs=candidates(search);top=cs[0];current=text(result)
        rows.append({'id':item['id'],'old_text':old['old_text'],'zero_no_graph_text':old['new_text'],'graph_text':current,
                     'baseline_changed':current!=old['old_text'],'zero_graph_changed':current!=old['new_text'],
                     'baseline_russian_tokens_equal':[t for t in top['token_ids'] if t>=1025]==[t for t in old['old_candidates'][0]['token_ids'] if t>=1025],
                     'zero_top_token_path_equal':top['token_ids']==old['new_candidates'][0]['token_ids'],
                     'graph_hint_spellings':hints(current),'graph_candidates':cs,'graph_state_stats':search['state_stats'],
                     'decode_s':result['decode_s'],'peak_rss_mib':result['peak_rss_bytes']/1048576,
                     'graph_vs_archived_not_accuracy':comparison(current,old['archived_raw_not_gold']),
                     'result_sha256':digest(path),'audio_sha256':result['audio_sha256']})
    samples=[s for r in sup['rows'] for s in r['samples']]
    stats={'records':len(rows),'new_decodes':len(rows),'exact_prior_routes':len(rows),'zero_credit_outputs':len(rows),
           'changed_vs_baseline':[r['id'] for r in rows if r['baseline_changed']],
           'changed_vs_zero_no_graph':[r['id'] for r in rows if r['zero_graph_changed']],
           'token_paths_equal_to_zero_no_graph':sum(r['zero_top_token_path_equal'] for r in rows),
           'russian_tokens_changed_vs_baseline':[r['id'] for r in rows if not r['baseline_russian_tokens_equal']],
           'hint_record_matches':dict(Counter(h for r in rows for h in r['graph_hint_spellings'])),
           'archive_agreement_not_accuracy':dict(Counter(r['graph_vs_archived_not_accuracy']['category'] for r in rows)),
           'batch_wall_s':sup['elapsed_s'],'decode_sum_s':sum(r['decode_s'] for r in rows),
           'decode_median_s':statistics.median(r['decode_s'] for r in rows),
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),
           'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'max_states':max(r['graph_state_stats']['max_states'] for r in rows),
           'combined_new_decodes':len(rows)+primary['statistics']['new_decodes'],
           'combined_batch_wall_s':sup['elapsed_s']+primary['statistics']['batch_wall_s'],
           'combined_decode_sum_s':sum(r['decode_s'] for r in rows)+primary['statistics']['decode_sum_s']}
    value={'statistics':stats,'rows':rows,'manifest_sha256':digest(mp),'source_commit':cfg['source_commit'],
           'controls':json.loads((base/'round15-graph-controls.json').read_text())}
    save(base/'round15-graph-observation.json',value);return value


def graph_section(root):
    base=root.parent/'routing-repair';value=json.loads((base/'round15-graph-observation.json').read_text());s=value['statistics'];esc=lambda v:html.escape(str(v))
    table_rows=[];details=[]
    for r in value['rows']:
        table_rows.append('<tr><td>'+r['id']+'</td>'+''.join('<td>'+esc(r[k])+'</td>' for k in ('old_text','zero_no_graph_text','graph_text'))+'</tr>')
        details.append('<details><summary>'+r['id']+' · нулевая премия, прежний автомат</summary><div class="scroll"><table><thead><tr><th>Место</th><th>Текст</th><th>Retained acoustic = total</th><th>Credit</th></tr></thead><tbody>')
        for i,c in enumerate(r['graph_candidates'],1):
            details.append('<tr><td>'+str(i)+'</td><td>'+esc(c['postprocessed_text'])+'</td><td>'+format(c['total_score'],'.6f')+'</td><td>'+format(c['context_credit'],'.1f')+'</td></tr>')
        details.append('</tbody></table></div><p>Decode '+format(r['decode_s'],'.3f')+' с; max states '+str(r['graph_state_stats']['max_states'])+'.</p></details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 15Б · ПРЕМИЯ И СОСТОЯНИЯ РАЗДЕЛЕНЫ</p>
<h2>Отключение подсказок не решает выбор имени: исчезают и нужные написания.</h2>
<p><b>Результат двух контролей совпал: все10 лучших token paths одинаковы с сохранёнными контекстными состояниями и без них.</b> На этих данных источник различия с бонусом2.5 — кредит при ранжировании/отсечении, а не само удаление контекстных состояний. Это локальный причинный вывод о данной реализации, не доказательство общего качества модели.</p>
<p>В c022 вместо DSH получилось смешанное «гид k», а не GitHub. В c018 DSH превратилось в gsi; в c027 ChatGPT Pro — в chargt fl; в c028 ChatGPT — в ch. Все пять прежних написаний DSH и оба ChatGPT исчезли. При этом Gemini/GPT в c005 остались, но перед GPT добавились русские токены. Без подсказок английская акустическая ветка всё ещё не даёт надёжных технических имён.</p>
<p><b>Решение: не включать ни один нулевой вариант вместо исходного.</b> Фиксированный общий набор имён одновременно поддерживает одни написания и влияет на чужие интервалы. Следующий механизм должен различать релевантность подсказки для конкретного интервала, а не просто усиливать или полностью выключать все имена. Такой механизм здесь ещё не проверен; ручной выбор лучших фрагментов запрещён.</p>
<h3>Дополнительный контроль: контекстные состояния сохранены, премия равна нулю</h3>
<p>После первого результата отдельно проверен механизм: те же десять записей, те же интервалы и фиксированные hint paths. Сохранён автомат с теми же переходами; каждая его премия и возврат обнулены. Это один структурный контроль, не перебор силы подсказки. До запуска {value['controls']['sequences']} последовательностей / {value['controls']['transitions']} переходов подтвердили одинаковые состояния и точное масштабирование credit. Проверка автомата — не parity всего ASR.</p>
<p>Завершились {s['new_decodes']}/{s['records']} новых декодирований; все интервалы совпали, все credit нулевые. По сравнению с исходным бонусом2.5 изменилось {len(s['changed_vs_baseline'])}/{s['records']} строк; по сравнению с нулём без автомата — {len(s['changed_vs_zero_no_graph'])}/{s['records']}. С полным удалением автомата совпали {s['token_paths_equal_to_zero_no_graph']}/{s['records']} лучших token paths. Написания фиксированных hints теперь: {esc(s['hint_record_matches'])}.</p>
<p>Удержание одинакового автомата отделяет роль его состояний от роли премии, но премия всё ещё влияет на промежуточное ранжирование/отсечение, не только на финальную арифметику. Равенство текстов не означает равенство всех оценок или всех состояний. Этот follow-up зафиксирован после просмотра первого контроля, а не выдаётся за слепую предварительную регистрацию.</p>
<h3>Все десять тройных сравнений</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Бонус2.5 + автомат</th><th>Ноль без автомата</th><th>Ноль с автоматом</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h3>Общий учёт раунда</h3><p>Два новых структурно разных варианта на десяти записях: всего {s['combined_new_decodes']} финальных декодирований. Новых акустических проходов и вызовов Qwen0. Суммарное supervised wall двух последовательных серий {s['combined_batch_wall_s']:.3f} с, из них decode {s['combined_decode_sum_s']:.3f} с. Это не20 независимых записей и не повторение исходного бонуса2.5.</p>
<p>Вторая серия: wall {s['batch_wall_s']:.3f} с, decode {s['decode_sum_s']:.3f} с, медиана {s['decode_median_s']:.3f} с. High-water RSS {s['max_highwater_rss_mib']:.2f} MiB, sampled RSS {s['max_sampled_rss_mib']:.2f} MiB; минимум доступно {s['minimum_available_mib']:.2f} MiB, swap growth {s['max_swap_growth_mib']:.3f} MiB. Пики последовательных серий не складываются. Max states {s['max_states']}. Только хост, не Deck/полная цепочка. Human gold0, согласие с архивом не точность: {esc(s['archive_agreement_not_accuracy'])}.</p>
<p>Источник второго прогона: <code>{esc(value['source_commit'])}</code>. Старый default2.5 оставлен, production не менялся. Все сохранённые альтернативы второго контроля:</p>{''.join(details)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--graph',action='store_true');a=p.parse_args()
    print(json.dumps((graph_observation if a.graph else observation)(a.root)['statistics'],ensure_ascii=False,indent=2))
