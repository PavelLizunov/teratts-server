"""Present every conditional boundary diagnostic without promoting it to truth."""
import argparse
import html
import json
from pathlib import Path
import statistics

from mms_pair import digest, save


def observation(root):
    base=root.parent/'routing-repair';mp=base/'manifest-round17.json';cfg=json.loads(mp.read_text());folder=Path(cfg['output'])
    summary=json.loads((folder/'summary.json').read_text());sup=json.loads((folder/'supervisor.json').read_text())
    controls=json.loads((folder/'controls.json').read_text())
    if summary['status']!='success' or sup['exit_code']!=0 or sup['stop_reason']:raise ValueError('Incomplete boundary diagnosis')
    rows=[];score_errors=[];partition_errors=[]
    for item in cfg['recordings']:
        path=folder/(item['id']+'.json');value=json.loads(path.read_text());score_errors.append(value['viterbi_receipt_score_error']);partition_errors.append(value['partition_error'])
        if not value['viterbi_trace_exact']:raise ValueError('Trace disagreement')
        for p,row in enumerate(value['phrases']):
            end=row['selected_last'];next_first=value['phrases'][p+1]['selected_first'] if p+1<len(value['phrases']) else len(row['frame_evidence'])
            plateau=0
            for f in row['frame_evidence'][end+1:next_first]:
                if f['top_token']!=1024:break
                plateau+=1
            record={k:v for k,v in row.items() if k not in ('start_mass','end_mass','occupancy','frame_evidence')}
            record.update(id=item['id'],audio_sha256=value['audio_sha256'],result_sha256=digest(path),
                          auxiliary_text=value['auxiliary_text'],existing_final_text=value['final_text'],
                          selected_start_s=max(0,row['selected_first']*.08-.04),selected_end_s=(row['selected_last']*.08+.04),
                          start_90_width_s=(row['start_summary']['q95_frame']-row['start_summary']['q05_frame'])*.08,
                          end_90_width_s=(row['end_summary']['q95_frame']-row['end_summary']['q05_frame'])*.08,
                          trailing_blank_top_frames=plateau,
                          equal_spelling_different_ids=row['target_text']==row['greedy_text'] and row['target_ids']!=row['greedy_token_ids'])
            rows.append(record)
    stats={'records':len(cfg['recordings']),'phrases':len(rows),'viterbi_trace_matches':len(cfg['recordings']),
           'maximum_viterbi_score_error':max(score_errors),'maximum_partition_error':max(partition_errors),
           'minimum_frame_intervals':[r['id']+':'+str(r['phrase']) for r in rows if r['selected_frames']==r['minimum_ctc_frames']],
           'selected_span_mass_median':statistics.median(r['selected_span_conditional_mass'] for r in rows),
           'selected_span_mass_min':min(r['selected_span_conditional_mass'] for r in rows),
           'selected_span_mass_max':max(r['selected_span_conditional_mass'] for r in rows),
           'trailing_blank_ambiguity_phrases':sum(r['trailing_blank_top_frames']>0 for r in rows),
           'acoustic_target_below_greedy':sum(r['target_minus_greedy_acoustic']<0 for r in rows),
           'biased_target_below_greedy':[r['id']+':'+str(r['phrase']) for r in rows if r['target_minus_greedy_isolated_biased']<0],
           'same_spelling_different_ids':[r['id']+':'+str(r['phrase']) for r in rows if r['equal_spelling_different_ids']],
           'graph_controls':len(controls['graph_controls']),'ctc_controls':len(controls['ctc_controls']),
           'maximum_control_error':max([r['max_absolute_error'] for r in controls['graph_controls']]+[r['absolute_error'] for r in controls['ctc_controls']]),
           'worker_s':summary['elapsed_s'],'supervised_s':sup['elapsed_s'],'highwater_rss_mib':summary['peak_rss_mib'],
           'sampled_rss_mib':max(s['rss_mib'] for s in sup['samples']),
           'minimum_available_mib':min(s['available_mib'] for s in sup['samples']),
           'max_swap_growth_mib':max(s['swap_growth_mib'] for s in sup['samples']),
           'new_transcripts':0,'new_model_calls':0,'human_gold_records':0}
    result={'statistics':stats,'rows':rows,'source_commit':cfg['source_commit'],'manifest_sha256':digest(mp)}
    save(base/'round17-observation.json',result);return result


def section(root):
    base=root.parent/'routing-repair';value=json.loads((base/'round17-observation.json').read_text());s=value['statistics'];esc=lambda v:html.escape(str(v))
    table=[];scores=[];details=[]
    for r in value['rows']:
        label=r['id']+' / '+str(r['phrase']);a,b=r['start_summary'],r['end_summary']
        table.append('<tr><td>'+label+'</td><td>'+esc(r['target_text'])+'</td><td>'+f"{r['selected_start_s']:.2f}–{r['selected_end_s']:.2f}"+'</td><td>'+str(r['selected_frames'])+' / '+str(r['minimum_ctc_frames'])+'</td><td>'+f"{a['q05_frame']*.08:.2f}–{a['q95_frame']*.08:.2f}"+'</td><td>'+f"{b['q05_frame']*.08:.2f}–{b['q95_frame']*.08:.2f}"+'</td><td>'+f"{100*r['selected_span_conditional_mass']:.2f}%"+'</td><td>'+str(r['trailing_blank_top_frames'])+'</td></tr>')
        scores.append('<tr><td>'+label+'</td><td>'+esc(r['target_text'])+'</td><td>'+esc(r['greedy_text'])+'</td>'+''.join('<td>'+format(r[k],'.3f')+'</td>' for k in ('target_minus_greedy_acoustic','target_context_credit','greedy_context_credit','target_minus_greedy_isolated_biased'))+'</tr>')
        record=json.loads((base/'round17-boundary-diagnostic'/(r['id']+'.json')).read_text())['phrases'][r['phrase']]
        details.append('<details><summary>'+label+' · все кадры и источник</summary><p><b>Qwen — не gold:</b> '+esc(r['auxiliary_text'])+'<br><b>Сохранённый final раунда16, не новый вывод:</b> '+esc(r['existing_final_text'])+'</p>')
        details.append('<p>Канонические IDs '+esc(r['target_ids'])+'; greedy IDs '+esc(r['greedy_token_ids'])+'. Акустическая log-mass target '+esc(r['target_ctc_log_mass'])+' / greedy '+esc(r['greedy_ctc_log_mass'])+'. Равное написание при разных IDs: '+esc(r['equal_spelling_different_ids'])+'.</p>')
        details.append('<p>Мода начала/конца '+str(a['mode_frame'])+' / '+str(b['mode_frame'])+'; энтропия '+format(a['entropy_nats'],'.3f')+' / '+format(b['entropy_nats'],'.3f')+' nat. Ожидаемое число phrase-кадров за выбранным интервалом '+format(r['expected_occupancy_outside_selected'],'.3f')+' — характеристика условного графа, не длительность реально пропущенной речи.</p>')
        details.append('<div class="scroll"><table><thead><tr><th>Кадр / центр, с</th><th>Выбран</th><th>Top1</th><th>Blank logp</th><th>Target IDs logp</th><th>Масса начала</th><th>Масса конца</th><th>Occupancy</th></tr></thead><tbody>')
        for i,f in enumerate(record['frame_evidence']):
            details.append('<tr><td>'+str(i)+' / '+format(f['center_s'],'.2f')+'</td><td>'+('да' if f['in_selected'] else '—')+'</td><td>'+esc(f['top_piece'])+'</td><td>'+format(f['blank_logp'],'.3f')+'</td><td>'+esc(', '.join(k+':'+format(v,'.3f') for k,v in f['target_label_logp'].items()))+'</td><td>'+format(record['start_mass'][i],'.5f')+'</td><td>'+format(record['end_mass'][i],'.5f')+'</td><td>'+format(record['occupancy'][i],'.5f')+'</td></tr>')
        details.append('</tbody></table></div></details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 17 · ПРИЧИНЫ ГРАНИЦ, БЕЗ НОВОЙ РАСШИФРОВКИ</p>
<h2>Граница неоднозначна, но её расширение не является доказанным исправлением.</h2>
<p>Все {s['phrases']} фраз на {s['records']} записях разобраны без сдвига интервалов, изменения waveform и новых модельных вызовов. Восстановленный лучший путь совпал с сохранённым во всех {s['viterbi_trace_matches']} записях; максимальная ошибка его оценки {s['maximum_viterbi_score_error']:.3g}. Forward/backward суммы согласованы с ошибкой не более {s['maximum_partition_error']:.3g}.</p>
<p><b>c009 / GitHub:</b> выбранные три EN-кадра42–44 — ровно минимальная длина канонической последовательности. На них log-mass target ниже greedy «it h» на15.084, а разница с учётом прежней премии остаётся−2.584. Это конкретная локальная акустическая конкуренция, не программный запрет имени. Она не доказывает правильность границ или результат полного смешанного RNNT-поиска.</p>
<p><b>c022 / лишнее «гид»:</b> условная масса начала концентрируется на кадре59(97.3%), но это свойство английского принудительного графа, не независимая метка языка. Русские эмиссии здесь не локализованы. Поэтому причина дублирования русского фрагмента этим экспериментом не доказана; начало вручную не переносили.</p>
<p><b>Неоднозначность blank:</b> в {s['trailing_blank_ambiguity_phrases']}/{s['phrases']} интервалах после выбранного конца идут кадры с blank как top1. Присоединение такого хвоста к последнему blank-состоянию фразы может иметь ту же лучшую оценку, что отдача кадров wildcard-промежутку. Условная масса границы размазывается и без новой произнесённой части слова. Низкая масса ровно выбранного интервала сама по себе не означает неправильный интервал.</p>
<p><b>Дополнительная найденная зависимость:</b> в c005 слово GPT одинаково записывается двумя наборами trained IDs, но канонический получает премию10, а greedy-вариант —0. Нынешний контекстный автомат сопоставляет токены, не все способы набрать то же написание. Это основание для отдельного механического исправления инвариантности токенизации, а не разрешение усилить имя или переписать вывод. Такой новый режим в этом раунде не запускался.</p>
<h3>Все11интервалов: условная масса, не доверительный интервал времени</h3>
<p>Выбранные границы — прежние полуинтервалы с краями±40мс. Диапазоны5–95% относятся к центрам80мс кадров в условном графе. Они не стали новыми маршрутами. «Кадров / минимум» показывает длину против ограничения CTC, а не физическую длительность слова. Масса выбранного span рассчитана совместно, не произведением маргинальных вероятностей.</p>
<div class="scroll"><table><thead><tr><th>ID / фраза</th><th>Target</th><th>Выбран, с</th><th>Кадров / минимум</th><th>Начало5–95%, с</th><th>Конец5–95%, с</th><th>Масса span</th><th>Blank-top хвост, кадров</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<p>Медиана массы выбранного span {100*s['selected_span_mass_median']:.2f}%, диапазон {100*s['selected_span_mass_min']:.2f}–{100*s['selected_span_mass_max']:.2f}%. Минимальная длина без запаса: {esc(s['minimum_frame_intervals'])}. Порогов принятия/отклонения нет; граф принудительно содержит заданные Qwen-фразы, даже если они ошибочны.</p>
<h3>Те же кадры: фиксированная последовательность CTC против greedy</h3><p>Δ acoustic и Δ biased — логарифмические разницы; отрицательное значение означает проигрыш target этому конкретному greedy-кандидату. Credit приведён за одну полную подсказку, включая границы. Это не вероятность правильного слова, не сравнение всех написаний и не точное воспроизведение смешанного поиска.</p>
<div class="scroll"><table><thead><tr><th>ID</th><th>Target</th><th>Greedy</th><th>Δ acoustic</th><th>Credit target</th><th>Credit greedy</th><th>Δ biased</th></tr></thead><tbody>{''.join(scores)}</tbody></table></div>
<p>Канонический target ниже greedy по акустической массе в {s['acoustic_target_below_greedy']}/{s['phrases']}. Даже после текущей премии проигрывает: {esc(s['biased_target_below_greedy'])}. Это не предложение подобрать премию до победы. Равное написание с разными IDs: {esc(s['same_spelling_different_ids'])}.</p>
<h3>Метод и границы доказательств</h3><p>Суммируются полные пути прежнего ordered phrase graph: label/blank получают logp−максимум кадра, wildcard gap получает0. Полученное распределение условно на канонические фразы; число путей и wildcard max влияют на него. Это не нормированная вероятность человеческой речи, не LID и не стандартный полный CTC posterior. Отдельно стандартный CTC суммирует все raw-пути к одной заданной последовательности IDs на неизменённых выбранных кадрах.</p>
<p>Численные проверки до корпуса: {s['graph_controls']} маленьких графа с полным перебором допустимых state paths, {s['ctc_controls']} fixed-token CTC случаев с81raw-путём каждый, включая повторы/пустой вывод. Максимальная абсолютная ошибка {s['maximum_control_error']:.3g}. Это не независимая внешняя реализация и не gold accuracy.</p>
<p>Worker {s['worker_s']:.3f} с, supervised {s['supervised_s']:.3f} с; high-water RSS {s['highwater_rss_mib']:.2f} MiB, sampled {s['sampled_rss_mib']:.2f} MiB; минимум доступно {s['minimum_available_mib']:.2f} MiB, swap growth {s['max_swap_growth_mib']:.3f} MiB. Host NumPy-only, не Deck или полная ASR-цепочка. Агентский лимит1536MiB/резерв2048MiB — не выделенная память.</p>
<p>Новых транскриптов0, human gold0. Production/словарь/WAV/маршруты неизменны. Источник <code>{esc(value['source_commit'])}</code>. Следующий метод должен отдельно решать токенизационную зависимость подсказок или получать независимые границы; диагностические квантили не объявлены решением.</p>
<h3>Все исходные кадры для каждой фразы</h3>{''.join(details)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
