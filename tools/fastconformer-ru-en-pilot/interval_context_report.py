"""Private interval-context comparison; auxiliary agreement is not truth."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re
import statistics

from context_ablation_report import candidates
from corroborated_report import english_words, text
from corpus_report import comparison
from mms_pair import digest, save


def contains(value, phrase):
    return bool(re.search(r'(?<![a-z])'+re.escape(phrase.casefold())+r'(?![a-z])',value.casefold()))


def observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round16.json';cfg=json.loads(mp.read_text());out=Path(cfg['output'])
    sup=json.loads((out/'supervisor-summary.json').read_text())
    if sup['status']!='completed':raise ValueError('Incomplete interval-context run')
    old_control=json.loads((base/'round15-observation.json').read_text());control={r['id']:r for r in old_control['rows']}
    prepared=json.loads((Path(cfg['english_model'])/'prepared.json').read_text());vocab={int(k):v for k,v in prepared['vocab'].items()}
    rows=[]
    for item in cfg['recordings']:
        if digest(item['prior_result'])!=item['hashes']['prior_result']:raise ValueError('Baseline changed')
        prior=json.loads(Path(item['prior_result']).read_text());path=out/(item['id']+'.json');new=json.loads(path.read_text());old=control[item['id']]
        if new['status']!='new_constrained_output' or not new['new_decoder_run']:raise ValueError('Missing new decoder result')
        if new['alignment']['selected_events']!=prior['alignment']['selected_events']:raise ValueError('Changed route')
        search=new['search'];paths=search['hint_paths'];alignment=new['alignment']
        if search['context_mode']!='auxiliary-interval-v1' or search['context_score']!=2.5 or not search['credit_partitioned_state']:raise ValueError('Unexpected search mode')
        if [p['token_ids'] for p in paths]!=alignment['english_phrases']:raise ValueError('Context not from unchanged proposal')
        if len(search['interval_context_graph_ids'])!=len(alignment['selected_events']):raise ValueError('Missing graph schedule')
        for event,gid in zip(alignment['selected_events'],search['interval_context_graph_ids']):
            if (event['head']=='eng')!=(gid>0):raise ValueError('Context leaked to Russian event')
        cs=candidates(search);top=cs[0];current=text(new);before=text(prior)
        if any(abs(c['total_score']-c['context_credit']-c['retained_same_text_logsum'])>1e-8 for c in cs):raise ValueError('Invalid score decomposition')
        phrases=[''.join(vocab[t] for t in p['token_ids']).replace('▁',' ').strip() for p in paths]
        source=next(r for r in old_control['rows'] if r['id']==item['id'])
        rows.append({'id':item['id'],'audio_sha256':new['audio_sha256'],'new_sha256':digest(path),
                     'auxiliary_text':new['auxiliary_raw_text'],'archived_raw_not_gold':source['archived_raw_not_gold'],
                     'baseline_text':before,'zero_text':old['new_text'],'interval_text':current,
                     'baseline_candidates':candidates(prior['search']),'interval_candidates':cs,
                     'context_phrases':phrases,'context_paths':paths,
                     'baseline_proposed_phrases_present':[contains(before,p) for p in phrases],
                     'zero_proposed_phrases_present':[contains(old['new_text'],p) for p in phrases],
                     'interval_proposed_phrases_present':[contains(current,p) for p in phrases],
                     'changed_vs_baseline':current!=before,'changed_vs_zero':current!=old['new_text'],
                     'russian_tokens_changed':[t for t in top['token_ids'] if t>=1025]!=[t for t in prior['search']['hypotheses'][0]['token_ids'] if t>=1025],
                     'new_english_words':list((Counter(english_words(current))-Counter(english_words(before))).elements()),
                     'lost_english_words':list((Counter(english_words(before))-Counter(english_words(current))).elements()),
                     'agreement_not_accuracy':comparison(current,source['archived_raw_not_gold']),
                     'baseline_agreement_not_accuracy':comparison(before,source['archived_raw_not_gold']),
                     'decode_s':new['decode_s'],'peak_rss_mib':new['peak_rss_bytes']/1048576,
                     'state_stats':search['state_stats'],'native_rows':alignment['native_rows'],
                     'duplicate_top4_texts':len(cs)-len({c['postprocessed_text'] for c in cs})})
    samples=[s for r in sup['rows'] for s in r['samples']]
    stats={'records':len(rows),'new_decodes':len(rows),'exact_prior_routes':len(rows),
           'context_phrases':sum(len(r['context_phrases']) for r in rows),
           'baseline_proposed_phrase_matches':sum(sum(r['baseline_proposed_phrases_present']) for r in rows),
           'zero_proposed_phrase_matches':sum(sum(r['zero_proposed_phrases_present']) for r in rows),
           'interval_proposed_phrase_matches':sum(sum(r['interval_proposed_phrases_present']) for r in rows),
           'changed_vs_baseline':[r['id'] for r in rows if r['changed_vs_baseline']],
           'changed_vs_zero':[r['id'] for r in rows if r['changed_vs_zero']],
           'changed_russian_token_records':[r['id'] for r in rows if r['russian_tokens_changed']],
           'records_with_nonzero_credit':sum(r['interval_candidates'][0]['context_credit']!=0 for r in rows),
           'records_with_duplicate_top4_texts':[r['id'] for r in rows if r['duplicate_top4_texts']],
           'baseline_agreement_not_accuracy':dict(Counter(r['baseline_agreement_not_accuracy']['category'] for r in rows)),
           'interval_agreement_not_accuracy':dict(Counter(r['agreement_not_accuracy']['category'] for r in rows)),
           'batch_wall_s':sup['elapsed_s'],'decode_sum_s':sum(r['decode_s'] for r in rows),
           'decode_median_s':statistics.median(r['decode_s'] for r in rows),
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),
           'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'max_states':max(r['state_stats']['max_states'] for r in rows),
           'new_audio_encoder_or_auxiliary_calls':0,'excluded_all_russian':len(cfg['excluded_records']),
           'human_gold_records':0}
    value={'statistics':stats,'rows':rows,'source_commit':cfg['source_commit'],'manifest_sha256':digest(mp),
           'controls_sha256':cfg['control_sha256'],'limitations':'coupled auxiliary timing/context; no accuracy or calibrated confidence'}
    save(base/'round16-observation.json',value);return value


def section(root):
    value=json.loads((root.parent/'routing-repair/round16-observation.json').read_text());s=value['statistics'];esc=lambda v:html.escape(str(v))
    table_rows=[];details=[]
    for r in value['rows']:
        table_rows.append('<tr><td>'+r['id']+'</td>'+''.join('<td>'+esc(v)+'</td>' for v in (' / '.join(r['context_phrases']),r['baseline_text'],r['interval_text']))+'</tr>')
        details.append('<details><summary>'+r['id']+' · источник и все сохранённые варианты</summary>')
        for label,key in [('Qwen — не эталон','auxiliary_text'),('Raw production — не эталон','archived_raw_not_gold'),('Прежний нулевой контроль','zero_text')]:
            details.append('<p><b>'+label+':</b> '+esc(r[key])+'</p>')
        details.append('<p>Русские trained IDs изменились: '+esc(r['russian_tokens_changed'])+'. RU/EN кадры: '+esc(r['native_rows'])+'. Decode '+format(r['decode_s'],'.3f')+' с, max states '+str(r['state_stats']['max_states'])+'.</p>')
        details.append('<div class="scroll"><table><thead><tr><th>Место</th><th>Вывод с отдельным форматированием пробелов</th><th>Retained acoustic</th><th>Context credit</th><th>Total</th></tr></thead><tbody>')
        for i,c in enumerate(r['interval_candidates'],1):
            details.append('<tr><td>'+str(i)+'</td><td>'+esc(c['postprocessed_text'])+'</td>'+''.join('<td>'+format(c[k],'.6f')+'</td>' for k in ('retained_same_text_logsum','context_credit','total_score'))+'</tr>')
        details.append('</tbody></table></div></details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 16 · ПОДСКАЗКА ТОЛЬКО В СВОЁМ ИНТЕРВАЛЕ</p>
<h2>Появились GitHub и GPT, но закрепились и ошибки вспомогательной модели.</h2>
<p><b>Итог: полезное изменение механизма, но не готовая замена baseline.</b> В c003 прежнее DSH заменилось на GPT; в c015 — на GitHub. В c022 тоже появился GitHub, но остались лишнее русское «гид» перед ним и отличие начала фразы. ChatGPT Pro в c027 и ChatGPT в c028 сохранились. Это наблюдаемые написания, а не подтверждённая человеком точность.</p>
<p>Обратная сторона видна на том же полном наборе: c018 теперь выдаёт GSH из предложения Qwen вместо прежнего DSH; c002 закрепляет латинскую фразу «nie proplayer v dsh», хотя другой ASR и контекст указывают на русскую речь. Неправильное направление языка здесь не исправлено. В c009 GitHub не победил — остался прежний повреждённый вариант с нулевой премией.</p>
<p>В c015 один новый decode занял55.984с на хосте. Пиковое число состояний выросло до58 400: режим хранит раздельно разные накопленные премии. Без профилирования нельзя всю задержку приписать этому фактору; пригодность по скорости не установлена. Production и базовый режим не переключены.</p>
<h3>Вместо общего списка имён — неизменённая фраза Qwen в своём участке</h3>
<p>Выполнены {s['new_decodes']} новых декодирований на всех {s['records']} прежних EN-маршрутах. Все {s['exact_prior_routes']} последовательностей native событий точно совпали с baseline. Новых вызовов Qwen/акустических энкодеров0; {s['excluded_all_russian']} all-Russian маршрутов не запускались. Фиксированный коэффициент2.5 не менялся; новых имён вручную не добавляли.</p>
<p>Каждая из {s['context_phrases']} английских фраз вспомогательной модели стала мягкой контекстной подсказкой только для своего уже существующего интервала. За его пределами подсказок нет. Полный обученный EN/RU-словарь открыт, акустические токены не подменяются, русский predictor не сбрасывается. Это не нарезка waveform и не отдельное распознавание фрагментов. Никакие слова Qwen не вставляются в итоговую строку напрямую.</p>
<p><b>Теперь Qwen влияет и на время, и на премию кандидату.</b> Его ошибки могут закрепляться; совпадение моделей больше не является независимым подтверждением. Буквально встретились предложенные фразы: общий baseline {s['baseline_proposed_phrase_matches']}/{s['context_phrases']}, без бонуса {s['zero_proposed_phrase_matches']}/{s['context_phrases']}, локальная подсказка {s['interval_proposed_phrase_matches']}/{s['context_phrases']}. Это проверка написания где-либо в строке, не WER, не временная оценка и не число правильно распознанных фраз.</p>
<p>Против общего baseline изменились {len(s['changed_vs_baseline'])}/{s['records']} строк; против нулевого контроля — {len(s['changed_vs_zero'])}/{s['records']}. Русские последовательности IDs изменились в {len(s['changed_russian_token_records'])} записях: {esc(s['changed_russian_token_records'])}. Ненулевая премия у {s['records_with_nonzero_credit']} лучших выходов.</p>
<h3>Все десять сравнений</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Локальная подсказка из Qwen</th><th>Прежний общий контекст</th><th>Новый интервальный контекст</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h3>Численный учёт, не уверенность в слове</h3><p>При выходе из интервала виртуальная контекстная граница завершает целую фразу или возвращает заёмную премию незаконченного префикса. Граница не является выходным акустическим токеном. Ранее накопленный контекст не переносится в следующий интервал. История RU, output prefix и CTC blank продолжаются без сброса.</p>
<p>Одинаковые output IDs могут получить разную премию при разных временах эмиссии. Поэтому накопленная премия входит в ключ состояния; суммы акустических путей объединяются только при одинаковом тексте и одинаковой премии. Top4 могут содержать одинаковые строки с разными оценками — это не четыре независимых текста. Такие повторы наблюдаются в {esc(s['records_with_duplicate_top4_texts'])}. Приблизительный retained logsum не является точным posterior и не сравнивается как точное отношение акустических вероятностей между прогонами.</p>
<p>До корпуса выполнены шесть контролей расчёта премии, два крошечных синтетических открытых поиска и проверка ключей: неполная подсказка возвращает премию; перенос через интервал не завершает слово; слабая подсказка может проиграть иному обученному токену; одинаковый текст с премиями0 и7.5 остаётся разделён. Это не доказательство точности речи и не полный parity-тест.</p>
<h3>Ресурсы и ограничения</h3><p>Host final-only wall {s['batch_wall_s']:.3f} с; сумма decode {s['decode_sum_s']:.3f} с, медиана {s['decode_median_s']:.3f} с. High-water RSS {s['max_highwater_rss_mib']:.2f} MiB, sampled peak {s['max_sampled_rss_mib']:.2f} MiB; минимум доступно {s['minimum_available_mib']:.2f} MiB, swap growth {s['max_swap_growth_mib']:.3f} MiB. Максимум состояний {s['max_states']}. Лимит1536MiB/свободный резерв2048MiB — не выделенная память. Это не новый Deck или полный ASR pipeline замер.</p>
<p>Архивное raw agreement до: {esc(s['baseline_agreement_not_accuracy'])}; после: {esc(s['interval_agreement_not_accuracy'])}. Human gold0. Production, gateway, словарь и baseline сохранены. Источник <code>{esc(value['source_commit'])}</code>; все локальные подсказки получены из сохранённых Qwen-токенов, не из архивного текста или желаемых ответов.</p>
<h3>Все сохранённые альтернативы</h3>{''.join(details)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
