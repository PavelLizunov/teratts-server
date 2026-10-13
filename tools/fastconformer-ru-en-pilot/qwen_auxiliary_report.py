"""Private comparison of auxiliary generators with unchanged trained final heads."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re
import statistics

from corroborated_report import english_words, text
from corpus_report import comparison
from mms_pair import digest, save


def observation(root):
    base=root.parent/'routing-repair';auxfolder=base/'round14-qwen-aux';finalfolder=base/'round14-final'
    auxcfg=json.loads((base/'manifest-round14-aux.json').read_text())
    finalcfg=json.loads((base/'manifest-round14-final.json').read_text())
    auxsummary=json.loads((auxfolder/'summary.json').read_text());finalsummary=json.loads((finalfolder/'supervisor-summary.json').read_text())
    if auxsummary['status']!='completed' or finalsummary['status']!='completed':raise ValueError('Incomplete independent auxiliary experiment')
    originals={r['id']:r for r in json.loads((root.parent/'collected-evaluation/comparison-final.json').read_text())['records']}
    final_ids={r['id'] for r in finalcfg['recordings']};rows=[];auxsamples=[];finalsamples=[]
    for item in auxcfg['recordings']:
        clip=item['id'];ap=auxfolder/(clip+'.json');aux=json.loads(ap.read_text())
        old=json.loads((base/'round11-results'/(clip+'.json')).read_text())
        final=json.loads((finalfolder/(clip+'.json')).read_text()) if clip in final_ids else {'status':'auxiliary_failed','new_decoder_run':False}
        previous,current=text(old),text(final);auxtext=(aux.get('hypotheses') or [{}])[0].get('raw_text','')
        en_words=[w for w in final.get('auxiliary_words',[]) if w['role']=='english_timing']
        en_frames=final.get('alignment',{}).get('native_rows',{}).get('eng')
        before=Counter(english_words(previous));after=Counter(english_words(current))
        row={'id':clip,'audio_sha256':item['sha256'],'duration_s':item['duration_s'],
             'archived_raw_not_gold':originals[clip]['raw_text'],'old_status':old['status'],'old_text':previous,
             'old_auxiliary_text':old.get('auxiliary_raw_text',''),'new_auxiliary_status':aux['status'],
             'new_auxiliary_text':auxtext,'new_status':final['status'],'new_text':current,
             'old_english_frames':old.get('alignment',{}).get('native_rows',{}).get('eng'),
             'new_english_frames':en_frames,'auxiliary_english_words':len(en_words),
             'all_russian_no_aux_english':en_frames==0,'new_decode':final['new_decoder_run'],
             'new_auxiliary_call':aux['new_model_call'],'auxiliary_s':aux['elapsed_s'],'decode_s':final.get('decode_s'),
             'changed_text':bool(previous and current and previous!=current),
             'lost_prior_english_words':list((before-after).elements()),'added_english_words':list((after-before).elements()),
             'error':final.get('error') or aux.get('error'),'auxiliary_sha256':digest(ap),
             'final_sha256':digest(finalfolder/(clip+'.json')) if clip in final_ids else None,
             'reused_result':final.get('reused_result'),'reused_result_sha256':final.get('reused_final_sha256')}
        if previous:row['old_vs_archived_not_accuracy']=comparison(previous,row['archived_raw_not_gold'])
        if current:
            row['new_vs_archived_not_accuracy']=comparison(current,row['archived_raw_not_gold'])
            row['auxiliary_vs_final_not_accuracy']=comparison(auxtext,current)
        rows.append(row);auxsamples.extend(aux.get('samples',[]))
    for r in finalsummary['rows']:finalsamples.extend(r['samples'])
    pairs=[r for r in rows if r['old_text'] and r['new_text']]
    newdec=[r['decode_s'] for r in rows if r['new_decode']]
    stats={'records':len(rows),'audio_seconds':sum(r['duration_s'] for r in rows),
           'auxiliary_status_counts':dict(Counter(r['new_auxiliary_status'] for r in rows)),
           'final_status_counts':dict(Counter(r['new_status'] for r in rows)),
           'new_model_calls':sum(r['new_auxiliary_call'] for r in rows),'new_final_decodes':len(newdec),
           'prior_outputs':sum(bool(r['old_text']) for r in rows),'outputs':sum(bool(r['new_text']) for r in rows),
           'recovered_prior_failures':[r['id'] for r in rows if r['new_text'] and not r['old_text']],
           'lost_prior_outputs':[r['id'] for r in rows if r['old_text'] and not r['new_text']],
           'paired_outputs':len(pairs),'changed_text_pairs':sum(r['changed_text'] for r in pairs),
           'prior_english_records':sum(bool(r['old_english_frames']) for r in rows),
           'new_english_records':sum(bool(r['new_english_frames']) for r in rows),
           'all_russian_no_aux_english_records':[r['id'] for r in rows if r['all_russian_no_aux_english']],
           'lost_prior_english_records':[r['id'] for r in pairs if r['lost_prior_english_words']],
           'added_english_records':[r['id'] for r in pairs if r['added_english_words']],
           'old_agreement_not_accuracy':dict(Counter(r['old_vs_archived_not_accuracy']['category'] for r in pairs)),
           'new_agreement_not_accuracy':dict(Counter(r['new_vs_archived_not_accuracy']['category'] for r in pairs)),
           'auxiliary_vs_final_not_accuracy':dict(Counter(r['auxiliary_vs_final_not_accuracy']['category'] for r in rows if r['new_text'])),
           'auxiliary_batch_wall_s':auxsummary['elapsed_s'],'auxiliary_median_cold_s':statistics.median(r['auxiliary_s'] for r in rows),
           'final_batch_wall_s':finalsummary['elapsed_s'],'new_decode_sum_s':sum(newdec),
           'new_decode_median_s':statistics.median(newdec) if newdec else None,
           'auxiliary_sampled_rss_mib':max(s['rss_mib'] for s in auxsamples),
           'final_sampled_rss_mib':max(s['rss_bytes'] for s in finalsamples)/1048576,
           'minimum_available_mib':min([s['available_mib'] for s in auxsamples]+[s['available_bytes']/1048576 for s in finalsamples]),
           'maximum_swap_growth_mib':max([s['swap_growth_mib'] for s in auxsamples]+[s['swap_growth_bytes']/1048576 for s in finalsamples]),
           'model_tensor_parameters':auxcfg['model_tensor_parameters'],'human_gold_records':0,'trained_head_encoder_passes':0,
           'runtime':'host native Qwen BF16 plus saved Deck EN/RU activations, not full cold-chain/Deck timing'}
    value={'statistics':stats,'rows':rows,'auxiliary_manifest_sha256':digest(base/'manifest-round14-aux.json'),
           'final_manifest_sha256':digest(base/'manifest-round14-final.json'),'source_commit':auxcfg['source_commit']}
    save(base/'round14-observation.json',value);return value


def section(root):
    value=json.loads((root.parent/'routing-repair/round14-observation.json').read_text());s=value['statistics']
    esc=lambda x:html.escape(str(x));details=[]
    for r in value['rows']:
        details.append('<details><summary>'+esc(r['id'])+' · '+esc(r['new_status'])+'</summary>')
        for label,key in [('Raw production — не эталон','archived_raw_not_gold'),('Прежняя подсказка Whisper','old_auxiliary_text'),('Новая подсказка Qwen — не итоговый вывод','new_auxiliary_text'),('Прежний финальный trained-head вывод','old_text'),('Новый финальный trained-head вывод','new_text')]:
            details.append('<p><b>'+esc(label)+'</b><br>'+esc(r[key] or 'Нет строки')+'</p>')
        details.append('<p>Английских кадров до / после: '+esc(r['old_english_frames'])+' / '+esc(r['new_english_frames'])+'. Новое финальное декодирование: '+esc(r['new_decode'])+'. Qwen '+format(r['auxiliary_s'],'.3f')+' с; final decode '+esc(r['decode_s'])+' с.</p>')
        if r['all_russian_no_aux_english']:details.append('<p><b>Qwen не предложил английских слов: весь маршрут русский. Это не доказательство отсутствия английской речи.</b></p>')
        if r['lost_prior_english_words']:details.append('<p>Прежние английские слова, которых теперь нет: '+esc(', '.join(r['lost_prior_english_words']))+'. Прежний вывод не gold.</p>')
        if r['added_english_words']:details.append('<p>Новые английские слова относительно прежнего вывода: '+esc(', '.join(r['added_english_words']))+'. Добавление не доказывает точность.</p>')
        if r['error']:details.append('<p>Отказ: '+esc(r['error'])+'</p>')
        details.append('</details>')
    featured=[]
    for clip in ('c027','c009','c022','c002'):
        row=next(r for r in value['rows'] if r['id']==clip)
        featured.append('<tr><td>'+clip+'</td><td>'+esc(row['old_text'] or 'Прежний отказ')+'</td><td>'+esc(row['new_auxiliary_text'])+'</td><td>'+esc(row['new_text'])+'</td></tr>')
    selected_examples='<div class="scroll"><table><thead><tr><th>ID</th><th>Прежний final</th><th>Новая Qwen-подсказка</th><th>Новый final</th></tr></thead><tbody>'+''.join(featured)+'</tbody></table></div>'
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 14 · ДРУГОЙ ИСТОЧНИК ВРЕМЕННОЙ ПОДСКАЗКИ</p>
<h2>Qwen предлагает интервалы; итоговые слова всё ещё выбирают RU/EN-головы.</h2>
<p>Qwen3-ASR-0.6B заменяет только Whisper в роли вспомогательного распознавателя. Веса исходные BF16; фактическое число параметров по заголовку тензоров {s['model_tensor_parameters']:,} — меньше1B, но больше номинального имени0.6B. Язык auto, нет hints/past-text, нарезки, добавления тишины или обучения. Каждая из28 исходных записей передана целиком. Qwen сам мультиязычный и не выдаётся за модель с жёстким RU/EN-ограничением.</p>
<p>Только представимые английские фразы Qwen направляются в прежний алгоритм выравнивания на сохранённых Parakeet CTC-вероятностях. Финальные слова выдаёт прежний открытый decoder с обученными английской и русской головами, native Russian closure и фиксированным контекстом2.5. Ни русский текст Qwen, ни его английские слова не копируются в итоговую строку. Строгий top1-фильтр раунда12 не используется.</p>
<p>Полных акустических наборов: {s['records']}, суммарно {s['audio_seconds']:.3f} с. Новых Qwen-вызовов {s['new_model_calls']}; статусы: {esc(s['auxiliary_status_counts'])}. Финальные статусы: {esc(s['final_status_counts'])}. Готовых строк {s['outputs']} против прежних {s['prior_outputs']}; восстановленные прежние отказы: {esc(s['recovered_prior_failures'])}; потерянные прежние выходы: {esc(s['lost_prior_outputs'])}.</p>
<p>Новых final decode {s['new_final_decodes']}; остальные удачные результаты взяты из ранее сохранённых <b>точно совпавших маршрутов</b>, включая эксперимент раунда12, с сохранённым хешем источника. {s['changed_text_pairs']} из {s['paired_outputs']} сравнимых строк изменились. EN-кадры есть в {s['new_english_records']} новых маршрутах, раньше — в {s['prior_english_records']} успешных. В {len(s['all_russian_no_aux_english_records'])} записях Qwen не предложил EN, весь маршрут русский; это явно отмечено ниже.</p>
<p>В {len(s['lost_prior_english_records'])} сравнимых записях отсутствуют английские слова прежнего вывода; в {len(s['added_english_records'])} добавились другие. Эти изменения не равны ошибкам или исправлениям без прослушивания и human gold. Новая вспомогательная модель может убрать повторы, но всё ещё ошибаться в написании имени, времени его появления или самом выборе языка.</p>
<h3>Польза и оставшиеся сбои рядом</h3>{selected_examples}<p>В c027 EN-маршрут сократился с47 до11 кадров: вместо английского суррогата русской фразы получилась русская фраза с ChatGPT Pro. В c009 английских кадров44→3: русская часть стала ближе к двум вспомогательным текстам, но GitHub по-прежнему повреждён. Это наблюдаемое различие путей, а не ручная оценка WER.</p><p>В c022 Qwen предложил GitHub, а прежний decoder с общим фиксированным набором hints вывел DSH. Это показывает, что замена источника интервалов не устраняет ошибку выбора имени; причина между acoustic score, search и context ещё не изолирована. В c002 латинская запись русской фразы от Qwen отдала почти всё время английской голове. Нельзя выдавать 28/28 строк за 28 верных двуязычных расшифровок.</p><p><b>Решение: сохранить Qwen-вариант как более надёжную по завершению экспериментальную ветку, но не переключать production.</b> Не объединять вручную лучшие фрагменты двух вариантов и не менять набор hints после просмотра этих примеров.</p>
<h3>Согласие с архивным ASR — не точность</h3><p>На одинаковых {s['paired_outputs']} парах до: {esc(s['old_agreement_not_accuracy'])}; после: {esc(s['new_agreement_not_accuracy'])}. Финальный trained-head вывод против Qwen-подсказки: {esc(s['auxiliary_vs_final_not_accuracy'])}. Это старый SequenceMatcher с диагностической нормализацией, не WER. Человеческих эталонов0; Qwen не назначен эталоном.</p>
<h3>Ресурсы хоста, не Deck и не полный холодный pipeline</h3><p>Qwen-серия {s['auxiliary_batch_wall_s']:.3f} с; медиана отдельного холодного Qwen-запуска {s['auxiliary_median_cold_s']:.3f} с; sampled peak {s['auxiliary_sampled_rss_mib']:.2f} MiB. Final-only серия {s['final_batch_wall_s']:.3f} с; сумма новых decode {s['new_decode_sum_s']:.3f} с; sampled peak {s['final_sampled_rss_mib']:.2f} MiB. Эти этапы выполнялись последовательно; пики памяти не складываются. Доступно минимум {s['minimum_available_mib']:.2f} MiB, рост swap {s['maximum_swap_growth_mib']:.3f} MiB. Лимиты Qwen4096MiB, decoder1536MiB, свободный резерв2048MiB — пределы, не выделенная память.</p>
<p>Новых проходов trained EN/RU-энкодеров0: сохранённые Deck-активации декодированы на хосте. Измерения не содержат полного повторного запуска основной акустической цепочки и не доказывают пригодность по памяти/скорости на Deck. Прежде проверена необходимость task-local BLAS-пути: отсутствующая без окружения libgfortran разрешена до inference. Все модельные активы и WAV проверены хешами, бинарник/нативные источники/библиотеки зафиксированы; совпадений аудио с известными прежними Qwen-прогонами не найдено.</p>
<p>Модель Qwen revision5eb144179a02acc5e5ba31e748d22b0cf3e303b0, native runtime924694251d9e0f18e5d86bbd06aa3ab5f870002d. Использована прежняя native-реализация, не заявляется parity с официальным Transformers. Нативное отражение края для центрированного STFT сохранено; добавленной тишины/нарезки нет. Production, gateway и словарь не изменены. Код прогона <code>{esc(value['source_commit'])}</code>.</p>
<h3>Все28 сравнения</h3>'''+''.join(details)+'</section>'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
