"""Private collected-speech comparison; disagreement is not human-gold WER."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import html
import json
from pathlib import Path
import re
import statistics

from mms_pair import save


def tokens(text):return re.findall(r'\w+',text.casefold().replace('ё','е'))


def comparison(a,b):
    a,b=tokens(a),tokens(b);ratio=SequenceMatcher(None,a,b,autojunk=False).ratio()
    return {'normalized_equal':a==b,'token_agreement_ratio':ratio,'category':'same' if a==b else 'small_difference' if ratio>=.85 else 'substantial_difference','reference_is_human_gold':False}


def report(root):
    root=Path(root);selection=json.loads((root/'selection.json').read_text());prepared=json.loads((root/'prepared-corpus.json').read_text());records={r['id']:r for r in selection['records']};collected={};samples=[];all_stages=[]
    for directory in sorted(root.glob('results-v*')):
        for path in directory.glob('c*/c*-pipeline.json'):
            clip=path.name.split('-')[0]
            if clip in collected:raise ValueError('Duplicate consumed clip results')
            pipe=json.loads(path.read_text());row=dict(records[clip],pipeline_status=pipe['status'],wall_s=pipe['elapsed_s'],failure=None)
            parent=path.parent;aux=parent/(clip+'-aux.json');final=parent/(clip+'-final.json')
            a=json.loads(aux.read_text()) if aux.exists() else {};f=json.loads(final.read_text()) if final.exists() else {}
            row['auxiliary_text']=(a.get('hypotheses') or [{}])[0].get('raw_text','');row['candidate_text']='';row['stage_metrics']={}
            for stage in ('aux','eng','rus','final'):
                p=parent/(clip+'-'+stage+'.json');q=parent/(clip+'-'+stage+'-supervisor.json')
                if p.exists():
                    value=json.loads(p.read_text())
                    if value.get('status')!='success':row['failure']=value.get('error','stage failed')
                else:value={}
                if q.exists():
                    s=json.loads(q.read_text());samples.extend(s['samples'])
                    metric={'wall_s':s['elapsed_s'],'peak_rss_mib':max(s['peak_rss_bytes'],value.get('peak_rss_bytes',0))/1048576,'exit_code':s['exit_code'],'stop_reason':s.get('stop_reason')}
                    row['stage_metrics'][stage]=metric;all_stages.append(dict(metric,stage=stage))
                    if s.get('stop_reason'):row['failure']='guard: '+s['stop_reason']
            if f.get('status')=='success':
                h=f['search']['hypotheses'][0];row.update(candidate_text=h['postprocessed_text'],raw_piece_text=h['raw_piece_text'],token_ids=h['token_ids'],formatting_spaces=h['formatting_only_inserted_space_before_token_indices'])
                row['versus_primary']=comparison(row['raw_text'],row['candidate_text']);row['versus_auxiliary']=comparison(row['auxiliary_text'],row['candidate_text'])
                align=json.loads((parent/(clip+'-alignment.json')).read_text());row['native_rows']=align['native_rows'];row['english_intervals']=align['english_phrase_intervals']
            row['result_directory']=str(parent);collected[clip]=row
    failures={e['id']:e['error'] for e in prepared['preparation_errors']}
    rows=[]
    for clip,r in records.items():
        rows.append(collected.get(clip,dict(r,pipeline_status='source_missing' if clip in failures else 'untouched',failure=failures.get(clip),candidate_text='',auxiliary_text='',stage_metrics={})))
    complete=[r for r in rows if r['pipeline_status']=='success'];attempted=[r for r in rows if r['pipeline_status'] in ('success','failed')]
    stats={'selected':len(rows),'prepared':len(prepared['recordings']),'attempted':len(attempted),'success':len(complete),'failed':sum(r['pipeline_status']=='failed' for r in rows),'source_missing':len(failures),'untouched':sum(r['pipeline_status']=='untouched' for r in rows),'audio_seconds_attempted':sum(r['audio_duration_s'] for r in attempted),'audio_seconds_success':sum(r['audio_duration_s'] for r in complete),'inference_wall_sum_s':sum(r['wall_s'] for r in attempted),'human_gold_records':0,
           'primary_agreement':dict(Counter(r['versus_primary']['category'] for r in complete)),
           'auxiliary_agreement_not_independent':dict(Counter(r['versus_auxiliary']['category'] for r in complete)),
           'strata':{s:{'selected':sum(r['stratum']==s for r in rows),'success':sum(r['stratum']==s for r in complete),'failed':sum(r['stratum']==s and r['pipeline_status']=='failed' for r in rows)} for s in ('latin','technical_proxy','other_russian')}}
    if complete:
        times=[r['wall_s'] for r in complete];ratios=[r['wall_s']/r['audio_duration_s'] for r in complete]
        stats.update(median_full_wall_s=statistics.median(times),minimum_full_wall_s=min(times),maximum_full_wall_s=max(times),median_individual_rtf=statistics.median(ratios),aggregate_rtf=sum(times)/sum(r['audio_duration_s'] for r in complete))
    if samples:stats.update(peak_stage_rss_mib=max(s['peak_rss_mib'] for s in all_stages),minimum_available_mib=min(s['available_bytes'] for s in samples)/1048576,maximum_swap_growth_mib=max(s['swap_growth_bytes'] for s in samples)/1048576,maximum_temperature_c=max(v for s in samples for v in s['temperatures_millic'].values())/1000)
    save(root/'comparison-final.json',{'statistics':stats,'selection':{k:v for k,v in selection.items() if k!='records'},'records':rows,'not_accuracy_or_wer':True})
    esc=lambda x:html.escape(str(x))
    parts=['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RU/EN — проверка на собранной речи</title><style>body{margin:0;background:#f7f6f2;color:#202220;font:18px/1.55 Georgia,serif}main{max-width:1100px;margin:auto;padding:30px 22px 64px}h1{line-height:1.2}h2{margin-top:2em;font-size:1.35em}table{width:100%;border-collapse:collapse;font-size:16px}th,td{padding:10px;border-bottom:1px solid #b7bbb4;text-align:left;vertical-align:top}th,.note{background:#e8ece6}.note{padding:16px}blockquote{background:white;border-left:3px solid #185348;margin:10px 0;padding:12px 16px;overflow-wrap:anywhere}details{margin:18px 0;border-top:1px solid #adb2aa;padding-top:12px}summary{cursor:pointer;font-weight:bold}small{color:#555}code{overflow-wrap:anywhere}.scroll{overflow-x:auto}a{color:#185348}.bar{height:16px;background:#185348}.track{background:#dedfd9;max-width:700px;margin-bottom:8px}p{margin:.8em 0}@media(max-width:600px){main{padding:20px 14px}table{font-size:14px}td,th{padding:6px}}</style><main>',
           '<header><p>Собранная пользовательская речь · Steam Deck · одна замороженная конфигурация</p><h1>Проверка за пределами двух отладочных записей</h1>',
           f'<p class="note"><strong>{stats["success"]} из {stats["attempted"]} запущенных записей получили итоговый текст.</strong> Неудач: {stats["failed"]}. Ещё {stats["source_missing"]} выбранный исходник исчез при ротации до копирования; не запущено: {stats["untouched"]}. Это механическая успешность, не точность распознавания.</p></header>',
           '<section class="note"><h2>Вывод: для замены production не подходит</h2><p>Удача на двух отладочных фразах не перенеслась на эту выборку. Ограничение обученными RU/EN-головами работает численно, но само по себе не обеспечивает правильную маршрутизацию языка. Повторяющиеся английские названия во вспомогательном Whisper могут захватить русскую часть записи и заставить английскую голову декодировать её.</p><p>Четыре записи остановились из-за невозможного выравнивания повторяющейся вспомогательной фразы; три — на неподдержанном вспомогательном слове (zašli, «ещё», 3D); одна — по лимиту RSS на этапе Whisper. Эти восемь случаев включены в результат, не заменены удачными повторами.</p><p>Среди формально завершённых есть явные признаки нестабильности: в c026 сохранённый русский текст сопоставляется с новым английским фрагментом, а вспомогательная гипотеза состоит из повторов названия. В c009 русская фраза с техническим именем превратилась в смешанную латиницу. Полные тексты показаны только в частных карточках ниже. Это примеры расхождений, не человеческая разметка аудио.</p><p>Положительные примеры тоже сохранены: c018 выводит DSH внутри русской фразы, c028 — ChatGPT, c005 — Gemini и GPT, хотя Gemini не добавлялся в подсказки. Обычная русская фраза c030 совпала со старым raw-текстом после нормализации.</p><p><strong>Следующий предмет исправления — надёжность вспомогательной языковой разметки и обработка её неподдержанных слов, а не увеличение бонуса имён.</strong> В ходе этой проверки исправления по ответам не вносились. Отдельно остаётся задержка: около трёх секунд обработки на секунду аудио.</p></section>',
           '<h2>Что именно проверялось</h2><p>Тот же Parakeet CTC int8 + GigaAM RNNT, state-forward поиск и четыре прежние подсказки: ChatGPT, ChatGPT Pro, DSH, Oracle. Локальный Whisper предлагает английские интервалы; его текст не подставляется в ответ. Обычные токены обеих обученных голов остаются открыты. Параметры не подбирались по результатам этой выборки.</p>',
           '<p>Никаких новых внешних аудиовызовов, обучения, нарезки, добавления тишины, перезапуска или переключения production. Для случая без английской вставки до запуска добавлен прямой маршрут всех русских кадров. Реальные сбои вспомогательной модели остаются сбоями, а не отбрасываются из статистики.</p>',
           '<h2>Выборка и ограничения вывода</h2><p>Инвентаризация: 2772 STT-записи, 2729 уникальных аудиохешей, около 4,2 часа речи. Человеческих эталонов нет. Старые 20 примеров с teacher-расшифровками уже отсутствовали в скользящем архиве. Для первой конечной проверки выбрано 30 новых примеров — по 10 из трёх групп, равномерно по хронологии внутри каждой. Страты определены по старому тексту модели, не по прослушанному языку. Техническая речь намеренно перепредставлена; это не случайная оценка всего архива.</p>',
           '<p>Допущено 2172 уникальных примера длиной 2–30 секунд в исходном PCM16 mono16k. Исключены 547 по длительности, 13 с пустым сохранённым текстом, 31 дубликат, 5 запросов с отключённым словарём и 4 архивные копии двух отладочных WAV. Отобрано 199,491 секунды, скопировано 194,713 секунды. Пропавший исходник не заменялся.</p>',
           '<div class="scroll"><table><tr><th>Группа по старому тексту</th><th>Выбрано</th><th>Итоговый текст</th><th>Сбой</th></tr>']
    labels={'latin':'Латиница','technical_proxy':'Техническое имя в транслитерации','other_russian':'Прочая русская речь'}
    for k,v in stats['strata'].items():parts.append(f'<tr><td>{labels[k]}</td><td>{v["selected"]}</td><td>{v["success"]}</td><td>{v["failed"]}</td></tr>')
    parts+=['</table></div><h2>Расхождения — не оценка правильности</h2><p>Сравнение с сохранённым raw-текстом production после приведения регистра, ё/е и удаления пунктуации. Совпадение не доказывает правильность, расхождение не доказывает ошибку нового варианта. Категория «небольшое» означает token SequenceMatcher ratio ≥0,85, не WER. Сохранённый final-текст показан отдельно: он мог проходить словарь или форматирование.</p>']
    for label,key in [('Совпадение','same'),('Небольшое расхождение','small_difference'),('Существенное расхождение','substantial_difference')]:
        n=stats['primary_agreement'].get(key,0);width=100*n/max(1,stats['success']);parts.append(f'<p>{label}: {n} / {stats["success"]}</p><div class="track"><div class="bar" style="width:{width:.2f}%"></div></div>')
    parts+=['<p>Whisper ниже — часть самой цепочки, а не независимый судья. Его расхождения полезны для диагностики маршрута, но не для объявления победителя.</p><h2>Полная задержка и ресурсы</h2>']
    if complete:parts.append(f'<p>Медиана успешного полного процесса: <strong>{stats["median_full_wall_s"]:.2f} с</strong>; диапазон {stats["minimum_full_wall_s"]:.2f}–{stats["maximum_full_wall_s"]:.2f} с. Суммарное время успешных процессов / суммарная длительность их аудио: <strong>{stats["aggregate_rtf"]:.2f}×</strong>. Это холодная последовательная цепочка, включая проверку файлов, загрузку трёх моделей и сохранение, не работа уже загруженного сервиса.</p>')
    if samples:parts.append(f'<p>Пик одного этапа: {stats["peak_stage_rss_mib"]:.2f} MiB; минимально доступно {stats["minimum_available_mib"]:.2f} MiB при резерве 2048 MiB. Максимальный наблюдавшийся рост swap: {stats["maximum_swap_growth_mib"]:.3f} MiB; температура до {stats["maximum_temperature_c"]:.1f} °C. Пики последовательных моделей не складываются. Лимит процесса 1100 MiB, до 600 секунд на запись; перед стартом следующей допускается до 120 секунд ожидания памяти. Паузы не считаются временем распознавания.</p>')
    parts+=['<h2>Все выбранные примеры</h2><p>Показан полный набор, включая ошибки и пропавший исходник. Названия групп — прокси по сохранённому тексту. Ниже частные пользовательские расшифровки, не публичный датасет.</p>']
    for r in rows:
        ratio=r.get('versus_primary',{}).get('token_agreement_ratio');status=r['pipeline_status'];parts.append(f'<details><summary>{esc(r["id"])} · {esc(labels[r["stratum"]])} · {r["audio_duration_s"]:.3f} с · {esc(status)}'+(f' · полная цепочка {r["wall_s"]:.2f} с' if 'wall_s' in r else '')+'</summary>')
        for label,value in [('Сохранённый raw-текст',r.get('raw_text','')),('Сохранённый final-текст',r.get('final_text','')),('Новый итоговый текст',r.get('candidate_text','')),('Вспомогательный Whisper — не эталон',r.get('auxiliary_text',''))]:parts.append(f'<p><strong>{label}</strong></p><blockquote>{esc(value) if value else "Нет текста"}</blockquote>')
        if r.get('failure'):parts.append(f'<p><strong>Ошибка:</strong> {esc(r["failure"])}</p>')
        if ratio is not None:parts.append(f'<p>Token agreement с raw: {ratio:.3f}; EN-кадров: {r["native_rows"]["eng"]}. Текст не исправлялся вручную.</p>')
        parts.append(f'<small>Исходный backend: {esc(r["backend"])} · SHA256 {esc(r["audio_sha256"])}</small></details>')
    parts+=['<h2>Воспроизводимость</h2><p>Начальная версия: 5d4caa0. Возобновление только нетронутых записей после паузы памяти: b56715c; изменения касались ожидания перед стартом, не модели, маршрута или поиска. Неудачные/неизвестные попытки не повторялись. Все исходные WAV, metadata, manifest hashes, ответы этапов и ресурсные выборки сохранены приватно.</p><p>Один замороженный метод и малая стратифицированная выборка не доказывают общую точность RU/EN, отсутствие выдумок или преимущество над production. Без прослушивания и человеческого эталона нельзя честно вывести WER или процент правильных названий.</p></main></html>']
    with (root/'corpus-results-final.html').open('x') as f:f.write('\n'.join(parts))
    print(json.dumps(stats,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();report(a.root)
