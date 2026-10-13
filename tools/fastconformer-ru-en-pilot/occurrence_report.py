"""Private complete CTC-event evidence, explicitly not word confidence or WER."""
import html
import json
from pathlib import Path
import statistics

from mms_pair import digest,save


def observation(root):
    base=root.parent/'routing-repair';folder=base/'round13-occurrence'
    cfg=json.loads((base/'manifest-round13.json').read_text());summary=json.loads((folder/'summary.json').read_text())
    supervisor=json.loads((folder/'supervisor.json').read_text());controls=json.loads((folder/'enumeration-controls.json').read_text())
    if summary['status']!='success' or supervisor['exit_code'] or supervisor['stop_reason']:raise ValueError('Incomplete occurrence experiment')
    rows=[]
    for r in cfg['recordings']:
        file=folder/(r['id']+'.json');row=json.loads(file.read_text());row['receipt_sha256']=digest(file);rows.append(row)
    events=[t for r in rows for t in r['targets']]
    samples=supervisor['samples']
    stats={'records':len(rows),'word_events':len(events),'auxiliary_unique_record_words':sum('auxiliary_word' in t['sources'] for t in events),
           'greedy_present_events':sum(t['greedy_contains_whole_target'] for t in events),'not_greedy_events':sum(not t['greedy_contains_whole_target'] for t in events),
           'worker_wall_s':summary['elapsed_s'],'supervised_wall_s':supervisor['elapsed_s'],
           'median_per_record_s':statistics.median(r['elapsed_s'] for r in rows),
           'highwater_rss_mib':summary['peak_rss_mib'],'sampled_peak_rss_mib':max(s['rss_mib'] for s in samples),
           'min_available_mib':min(s['available_mib'] for s in samples),'max_swap_growth_mib':max(s['swap_growth_mib'] for s in samples),
           'max_log_mass_error':max(t['maximum_log_total_mass_error'] for t in events),
           'enumeration_controls':len(controls['rows']),'max_enumeration_abs_error':max(c['absolute_error'] for c in controls['rows']),
           'new_model_calls':0,'new_transcripts':0,'human_gold_records':0}
    value={'statistics':stats,'rows':rows,'source_commit':cfg['source_commit'],'manifest_sha256':digest(base/'manifest-round13.json'),
           'no_threshold_selected':True,'word_event_not_semantic_confidence':True}
    save(base/'round13-observation.json',value);return value


def section(root):
    base=root.parent/'routing-repair';r=json.loads((base/'round13-observation.json').read_text());s=r['statistics']
    esc=lambda x:html.escape(str(x))
    tables=[]
    for row in r['rows']:
        body=[]
        for t in sorted(row['targets'],key=lambda t:t['probability'],reverse=True):
            body.append('<tr><td>'+esc(t['target'])+'</td><td>'+format(t['probability'],'.8g')+'</td><td>'+esc(t['greedy_contains_whole_target'])+'</td><td>'+esc(', '.join(t['sources']))+'</td><td>'+esc(t['auxiliary_occurrences'])+'</td></tr>')
        tables.append('<details><summary>'+esc(row['id'])+' · '+str(len(row['targets']))+' событий · '+format(row['elapsed_s'],'.3f')+' с</summary><p><b>Native greedy, не эталон:</b> '+esc(row['greedy_english_text'])+'</p><div class="scroll"><table><thead><tr><th>Целевая буквенная запись</th><th>Масса события 0–1, не уверенность</th><th>Есть в greedy</th><th>Источник запроса</th><th>Повторы в подсказке</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>')
        if row['unsupported_auxiliary_words']:tables.append('<p>Непредставимые вспомогательные слова пропущены только как диагностические запросы: '+esc(', '.join(row['unsupported_auxiliary_words']))+'. Прежние отказы ASR сохранены.</p>')
        tables.append('</details>')
    illustrative=[]
    for clip,query in [('c005','gemini'),('c005','gpt'),('c018','dsh'),('c028','chatgpt'),('c021','chatgpt'),('c026','chatgpt'),('c002','v')]:
        row=next(x for x in r['rows'] if x['id']==clip);t=next(x for x in row['targets'] if x['target']==query)
        illustrative.append('<tr><td>'+clip+'</td><td>'+esc(query)+'</td><td>'+format(t['probability'],'.8g')+'</td><td>'+esc(t['greedy_contains_whole_target'])+'</td></tr>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 13 · ВСЕ CTC-ПУТИ, НЕ ТОЛЬКО TOP1</p>
<h2>Альтернативы измерены; надёжный критерий исправления пока не найден.</h2>
<p>Новый диагностический алгоритм вычисляет вероятность события «CTC-вывод содержит целое слово или фразу» в собственном распределении английской головы. Он суммирует все времена и варианты разбиения на обученные subword-токены, а не только каноническую токенизацию. Повторы сворачиваются до удаления blank; начало и конец слова обязательны. В отличие от forced alignment, присутствие слова не навязывается.</p>
<p>На {s['records']} сохранённых записях рассчитаны <b>{s['word_events']} событий</b>: четыре прежние подсказки на каждой записи плюс уникальные представимые английские слова Whisper. Пересекающиеся запросы объединены. Уникальных пар «запись — вспомогательное слово» {s['auxiliary_unique_record_words']}; это не прежние 223 вхождения с повторами. В greedy есть {s['greedy_present_events']} запрошенных событий, нет {s['not_greedy_events']}.</p>
<p><b>Нет новых расшифровок, автоматического удаления английского или подобранного порога.</b> Число ниже относится к буквенной форме внутри модели, а не к вероятности, что человек произнёс это слово. Даже суммирование всех CTC-путей не исправляет слабую акустическую модель, несоответствие произношения и написания или её калибровку.</p>
<h3>Показательные наблюдения из полного набора</h3><div class="scroll"><table><thead><tr><th>Запись</th><th>Запрос</th><th>Масса события 0–1</th><th>Есть в greedy</th></tr></thead><tbody>'''+''.join(illustrative)+f'''</tbody></table></div>
<p>DSH и ChatGPT, которые прежний контекстный поиск выводил в c018/c028, имеют очень малую безбонусную массу. Отсутствие в greedy не равно нулевой массе, но ненулевая масса также не подтверждает правильность слова. Повторяющиеся ChatGPT в c021/c026 имеют ещё меньшую массу; это полезное различие именно этих наблюдений, не проверенный порог для других слов или записей. Вероятности зависят от длины и буквенной формы. Контекстный бонус в расчёт не включён.</p>
<p>«Все разбиения» означает разные subword-разбиения одной и той же буквенной формы. Это <b>не</b> суммирование транслитераций, фонетических замен или вариантов вроде аббревиатуры с дополнительными пробелами. Границы слов следуют опубликованному маркеру ▁ и прежней политике пунктуации. Для длинной записи событие означает хотя бы одно появление где-либо, не число повторов. Сохранённая масса первого завершения по кадрам не является разметкой границ аудио.</p>
<h3>Что проверено численно</h3><p>{s['enumeration_controls']} синтетических событий сверены с отдельным полным перебором сырых путей: один маленький словарь даёт 243 пути, второй 256. Максимальное расхождение {s['max_enumeration_abs_error']:.3g}. Это десять численных контролей, не десять записей речи и не тысячи модельных тестов. Максимальная ошибка сохранения полной массы на корпусе {s['max_log_mass_error']:.3g} в лог-пространстве. Проверены хеши, нормализация и диапазон события. Независимая внешняя реализация не проверялась; математические контроли не дают human gold.</p>
<h3>Стоимость на локальном хосте</h3><p>Время worker {s['worker_wall_s']:.3f} с, всего под наблюдением {s['supervised_wall_s']:.3f} с; медиана записи {s['median_per_record_s']:.3f} с. High-water RSS {s['highwater_rss_mib']:.2f} MiB, sampled peak {s['sampled_peak_rss_mib']:.2f} MiB; доступно минимум {s['min_available_mib']:.2f} MiB, прирост swap {s['max_swap_growth_mib']:.3f} MiB. Это NumPy-анализ сохранённых Deck-выходов на другом хосте, не полная задержка ASR и не новый замер Deck.</p>
<p>Новых модельных вызовов {s['new_model_calls']}, новых расшифровок {s['new_transcripts']}, человеческих эталонов {s['human_gold_records']}. Аудио, рабочие сервисы, словарь и основной pipeline не менялись. Код до запуска: <code>{esc(r['source_commit'])}</code>. <a href="https://github.com/huggingface/audio-transformers-course/blob/main/chapters/en/chapter3/ctc.mdx">Справка о CTC</a> объясняет свёртку путей; конкретный конечный автомат этого эксперимента — собственная реализация, не официальный benchmark.</p>
<h3>Все28 записей и все133 события</h3>'''+''.join(tables)+'</section>'


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
