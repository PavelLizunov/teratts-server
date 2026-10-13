"""Compare frozen timing gate with prior raw outputs, never human-gold accuracy."""
import html
import json
from collections import Counter
from pathlib import Path
import re
import statistics

from corpus_report import comparison
from mms_pair import digest, save


def text(row):
    return row.get('search',{}).get('hypotheses',[{}])[0].get('postprocessed_text','')


def english_words(value):
    # Diagnostics only. Never fed back into routing, decoder or edited output.
    return re.findall(r"[a-z]+(?:'[a-z]+)?",value.casefold())


def observation(root):
    base=root.parent/'routing-repair';manifest_path=base/'manifest-round12.json'
    manifest=json.loads(manifest_path.read_text());folder=base/'round12-results'
    supervisor=json.loads((folder/'supervisor-summary.json').read_text())
    if supervisor['status']!='completed':raise ValueError('Do not report incomplete batch as finished')
    production=json.loads((root.parent/'collected-evaluation/comparison-final.json').read_text())
    originals={r['id']:r for r in production['records']};rows=[]
    for item in manifest['recordings']:
        path=folder/(item['id']+'.json');new=json.loads(path.read_text());old=json.loads(Path(item['prior_result']).read_text())
        new_text,old_text=text(new),text(old);evidence=new.get('corroboration',{})
        before=Counter(english_words(old_text));after=Counter(english_words(new_text))
        row={'id':item['id'],'status':new['status'],'old_status':old['status'],
             'old_text':old_text,'new_text':new_text,'archived_raw_not_gold':originals[item['id']]['raw_text'],
             'auxiliary_text':new.get('auxiliary_raw_text',''),'greedy_english_text':evidence.get('greedy_english_text',''),
             'new_decoder_run':new['new_decoder_run'],'decode_s':new.get('decode_s'),
             'route_identical':new.get('selected_events_identical'),
             'audio_sha256':new['audio_sha256'],'result_sha256':digest(path),
             'new_text_vs_old_changed':bool(old_text and new_text and new_text!=old_text),
             'english_words_missing_vs_prior':list((before-after).elements()),
             'english_words_added_vs_prior':list((after-before).elements()),
             'corroboration':evidence,'new_english_frames':new.get('alignment',{}).get('native_rows',{}).get('eng'),
             'old_english_frames':old.get('alignment',{}).get('native_rows',{}).get('eng'),
             'error':new.get('error')}
        if new_text:
            row['new_vs_archived_raw_not_accuracy']=comparison(new_text,row['archived_raw_not_gold'])
        if old_text:
            row['old_vs_archived_raw_not_accuracy']=comparison(old_text,row['archived_raw_not_gold'])
        rows.append(row)
    comparisons=[r for r in rows if r['old_text'] and r['new_text']]
    samples=[s for r in supervisor['rows'] for s in r['samples']]
    decoded=[r['decode_s'] for r in rows if r['new_decoder_run']]
    stats={'retained_head_sets':len(rows),'prior_outputs':sum(bool(r['old_text']) for r in rows),
           'outputs':sum(bool(r['new_text']) for r in rows),'status_counts':dict(Counter(r['status'] for r in rows)),
           'new_decodes':len(decoded),'unchanged_route_reuses':sum(r['status']=='reused_unchanged' for r in rows),
           'new_outputs_without_prior':sum(bool(r['new_text']) and not r['old_text'] for r in rows),
           'changed_text_pairs':sum(r['new_text_vs_old_changed'] for r in rows),'paired_outputs':len(comparisons),
           'english_fallback_records':[r['id'] for r in rows if r['corroboration'].get('all_russian_fallback_after_rejection')],
           'retained_any_english_frames':sum(bool(r['new_english_frames']) for r in rows),
           'prior_english_records':sum(bool(r['old_english_frames']) for r in rows),
           'missing_prior_english_word_records':[r['id'] for r in comparisons if r['english_words_missing_vs_prior']],
           'english_aux_words':sum(r['corroboration'].get('auxiliary_english_words',0) for r in rows),
           'corroborated_english_words':sum(r['corroboration'].get('corroborated_english_words',0) for r in rows),
           'paired_old_primary_agreement_not_accuracy':dict(Counter(r['old_vs_archived_raw_not_accuracy']['category'] for r in comparisons)),
           'paired_new_primary_agreement_not_accuracy':dict(Counter(r['new_vs_archived_raw_not_accuracy']['category'] for r in comparisons)),
           'batch_wall_s':supervisor['elapsed_s'],'sum_new_decode_s':sum(decoded),'median_new_decode_s':statistics.median(decoded) if decoded else None,
           'sampled_peak_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'maximum_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'human_gold_records':0,'audio_encoder_passes':0,'local_host_not_deck':True}
    result={'statistics':stats,'rows':rows,'manifest_sha256':digest(manifest_path),'source_commit':manifest['source_commit'],
            'selection':'same28 previously inspected original head sets; no output-based subset','not_accuracy_or_wer':True}
    save(base/'round12-observation.json',result)
    return result


def section(root):
    base=root.parent/'routing-repair';result=json.loads((base/'round12-observation.json').read_text());s=result['statistics']
    esc=lambda x:html.escape(str(x));blocks=[]
    for r in result['rows']:
        blocks.append('<details><summary>'+esc(r['id'])+' · '+esc(r['status'])+'</summary>')
        for label,value in [('Сохранённый raw production — не эталон',r['archived_raw_not_gold']),('До проверки английского',r['old_text']),('После проверки английского',r['new_text']),('Whisper — только предложение',r['auxiliary_text']),('Native English greedy — только подтверждение',r['greedy_english_text'])]:
            blocks.append('<p><b>'+esc(label)+'</b><br>'+esc(value or 'Нет текста')+'</p>')
        c=r['corroboration']
        blocks.append('<p>Английские слова подсказки: '+esc(c.get('auxiliary_english_words','—'))+'; подтверждено: '+esc(c.get('corroborated_english_words','—'))+'; английских кадров раньше / теперь: '+esc(r['old_english_frames'])+' / '+esc(r['new_english_frames'])+'.</p>')
        if c.get('all_russian_fallback_after_rejection'):blocks.append('<p><b>Все английские подсказки отвергнуты: явный all-Russian fallback, не двуязычный успех.</b></p>')
        if r['english_words_missing_vs_prior']:blocks.append('<p>Английские слова прежнего вывода, которых теперь нет: '+esc(', '.join(r['english_words_missing_vs_prior']))+'. Прежний вывод тоже не эталон.</p>')
        if r['error']:blocks.append('<p>Сохранившийся отказ: '+esc(r['error'])+'</p>')
        blocks.append('</details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 12 · АКУСТИЧЕСКОЕ ПОДТВЕРЖДЕНИЕ ПОДСКАЗКИ</p>
<h2>Больше завершённых записей не означает лучшее двуязычное распознавание.</h2>
<p>Проверен один заранее фиксированный метод: английское слово из Whisper допускается во временную подсказку только при точном монотонном совпадении с отдельным вхождением в native greedy пути английской CTC-головы. Это не fuzzy-поиск, не замена слов и не усиление имён. Финальный открытый поиск RU/EN остаётся прежним. Если подтверждений нет, результат явно помечен как отказ от английской ветки / all-Russian fallback.</p>
<p><b>{s['outputs']} из {s['retained_head_sets']} полных наборов получили текст</b>; новых декодирований {s['new_decodes']}, неизменных маршрутов с повторным использованием результата {s['unchanged_route_reuses']}. Новых выходов вместо прежнего отказа {s['new_outputs_without_prior']}. Ранее запущенная 29-я запись без полного набора акустических данных не повторялась. {s['changed_text_pairs']} из {s['paired_outputs']} прежних строк изменились.</p>
<p>Из {s['english_aux_words']} английских слов-вхождений вспомогательного текста подтверждены {s['corroborated_english_words']}. Всю английскую подсказку пришлось отвергнуть в {len(s['english_fallback_records'])} записях. Хотя бы один английский кадр остался в {s['retained_any_english_frames']} записях; раньше такие кадры были в {s['prior_english_records']} успешных записях. Это разные знаменатели: раньше неуспешные маршруты тоже входят в новый набор.</p>
<p>Большой знаменатель 223 включает повторяющиеся подсказки, в том числе 146 повторов в одной записи; это не число разных имён. Все 16 новых декодирований в этом запуске оказались all-Russian fallback. Уменьшение времени не означает ускорение полноценного двуязычного поиска.</p>
<p><b>Слишком жёсткое совпадение может терять нужные названия вместе с ложными повторами.</b> В {len(s['missing_prior_english_word_records'])} сопоставимых записях исчезло хотя бы одно английское слово прежнего результата. Ни прежние слова, ни новые не подтверждены человеком. Поэтому рост числа завершений нельзя объявить ростом точности, а согласие двух моделей — уверенностью в языке. Порог не ослаблялся после просмотра результатов. Метод не включён в production или основной pipeline.</p>
<h3>Сопоставление с сохранённым текстом — не WER</h3><p>На одинаковых {s['paired_outputs']} парах прежние категории agreement: {esc(s['paired_old_primary_agreement_not_accuracy'])}; новые: {esc(s['paired_new_primary_agreement_not_accuracy'])}. Использована прежняя диагностическая нормализация и SequenceMatcher; архивный текст модели не является эталоном. Проверенного human gold: {s['human_gold_records']}.</p>
<h3>Фактическая стоимость только этого локального дополнения</h3><p>Полное время серии {s['batch_wall_s']:.3f} с, сумма новых финальных decode {s['sum_new_decode_s']:.3f} с, медиана {s['median_new_decode_s']:.3f} с. Sampled RSS максимум {s['sampled_peak_rss_mib']:.2f} MiB; доступно минимум {s['minimum_available_mib']:.2f} MiB; рост swap {s['maximum_swap_growth_mib']:.3f} MiB. Лимит RSS 1536 MiB, резерв доступной памяти 2048 MiB — это пределы, не занятая память. Это хостовый joiner/predictor с ранее сохранёнными Deck-активациями, не скорость полной цепочки или новый замер Deck.</p>
<p>Новых encoder/WAV проходов {s['audio_encoder_passes']}; обучение, нарезка, добавление тишины, загрузка частного аудио наружу и изменения рабочего ASR отсутствуют. Во время фактического выполнения проверены хеши, монотонность и уникальность соответствий, выбранные trained IDs и допустимость финального пути. Это не заменяет независимую валидацию алгоритма. Ранее запрещённые unit tests не повторялись.</p>
<p>Код фиксирован перед исполнением: <code>{esc(result['source_commit'])}</code>. Показаны все28 наблюдений, включая оба оставшихся отказа. Все предыдущие результаты сохранены отдельно.</p>
<h3>Полные сравнения</h3>'''+''.join(blocks)+'</section>'


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
