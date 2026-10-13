"""Compare two English-only heads without treating English-on-Russian as truth."""
import argparse
import html
import json
from pathlib import Path
import statistics

from boundary_mass import greedy_ids
from interval_context_report import contains
from mms_pair import digest, save


def observation(root):
    import numpy as np
    base=root.parent/'routing-repair';mp=base/'manifest-round19.json';cfg=json.loads(mp.read_text());folder=Path(cfg['results_directory'])
    prior_cfg=json.loads((base/'manifest-round14-final.json').read_text());prior_items={r['id']:r for r in prior_cfg['recordings']}
    old_prepared_path=Path(prior_cfg['english_model'])/'prepared.json';old_prepared=json.loads(old_prepared_path.read_text())
    new_prepared_path=Path(cfg['model'])/'prepared.json';new_prepared=json.loads(new_prepared_path.read_text())
    if digest(new_prepared_path)!=cfg['prepared_sha256']:raise ValueError('Changed prepared model')
    vocab_old={int(k):v for k,v in old_prepared['vocab'].items()};vocab_new={int(k):v for k,v in new_prepared['vocab'].items()}
    old_results={r['id']:r for r in json.loads((base/'round14-observation.json').read_text())['rows']}
    scoped={r['id']:r for r in json.loads((base/'round18-observation.json').read_text())['rows']}
    def decode(ids,vocab):return ''.join(vocab[t] for t in ids).replace('▁',' ').strip()
    rows=[];intervals=[];samples=[];supervised=0.
    for item in cfg['recordings']:
        clip=item['id'];path=folder/(clip+'.json');new=json.loads(path.read_text());sup=json.loads((folder/(clip+'-supervisor.json')).read_text())
        if sup['exit_code']!=0 or sup['stop_reason'] or new['status']!='success':raise ValueError('Incomplete acoustic cell')
        if new['audio_sha256']!=item['sha256'] or new['prepared_sha256']!=cfg['prepared_sha256']:raise ValueError('Changed audio/mapping')
        old_item=prior_items[clip];old=json.loads(Path(old_item['eng']).read_text());old_array=Path(old_item['eng']).with_suffix('.npz');new_array=path.with_suffix('.npz')
        if digest(old_item['eng'])!=old_item['hashes']['eng'] or digest(old_array)!=old['retained_array_sha256'] or digest(new_array)!=new['retained_logits_sha256']:raise ValueError('Changed retained arrays')
        if old['prepared_sha256']!=digest(old_prepared_path):raise ValueError('Changed old mapping')
        with np.load(old_array) as f:old_lp=f['values']
        with np.load(new_array) as f:new_lp=f['log_probs']
        if old_lp.shape!=new_lp.shape or new['native_stride_s']!=.08 or new['nominal_origin_s']!=0.:raise ValueError('Different native frame clock')
        old_ids=greedy_ids(old_lp,1024);new_ids=greedy_ids(new_lp,1024)
        if new_ids!=new['token_ids']:raise ValueError('Saved greedy differs from array')
        old_text=decode(old_ids,vocab_old);new_text=decode(new_ids,vocab_new)
        if new_text!=new['raw_text']:raise ValueError('Saved raw text mismatch')
        row={'id':clip,'audio_sha256':item['sha256'],'duration_s':item['duration_s'],
             'old_english_greedy':old_text,'new_english_greedy':new_text,'new_token_ids':new_ids,
             'archived_raw_not_gold':old_results[clip]['archived_raw_not_gold'],
             'auxiliary_not_gold':old_results[clip]['new_auxiliary_text'],
             'unchanged_mixed_output':scoped[clip]['spelling_context_text'] if clip in scoped else old_results[clip]['new_text'],
             'native_frames':len(new_lp),'whole_audio_samples':new['input_samples'],
             'unknown_tokens':new_ids.count(0),'forward_s':new['forward_s'],'cold_worker_s':new['elapsed_s'],
             'supervised_s':sup['elapsed_s'],'peak_rss_mib':new['peak_rss_bytes']/1048576,
             'normalization_error':new['normalization_error'],'array_sha256':new['retained_logits_sha256'],'result_sha256':digest(path)}
        if clip in scoped:
            prior=json.loads((base/'round18-spelling-context'/(clip+'.json')).read_text())
            for span,target in zip(prior['alignment']['english_phrase_intervals'],scoped[clip]['context_phrases']):
                a,b=span['first_en_frame'],span['last_en_frame'];oi=greedy_ids(old_lp[a:b+1],1024);ni=greedy_ids(new_lp[a:b+1],1024)
                ot,nt=decode(oi,vocab_old),decode(ni,vocab_new)
                intervals.append({'id':clip,'phrase':span['phrase'],'target_from_auxiliary':target,'first_en_frame':a,'last_en_frame':b,
                                  'start_s':span['start_s'],'end_s':span['end_s'],'old_interval_greedy':ot,'new_interval_greedy':nt,
                                  'old_token_ids':oi,'new_token_ids':ni,'old_whole_contains':contains(old_text,target),'new_whole_contains':contains(new_text,target),
                                  'old_interval_contains':contains(ot,target),'new_interval_contains':contains(nt,target),
                                  'new_blank_argmax_frames':int((new_lp[a:b+1].argmax(axis=1)==1024).sum()),
                                  'window_only_saved_frames_not_waveform_crop':True})
        rows.append(row);samples.extend(sup['samples']);supervised+=sup['elapsed_s']
    stats={'records':len(rows),'new_english_encoder_calls':len(rows),'audio_s':sum(r['duration_s'] for r in rows),
           'matching_native_clocks':len(rows),'english_phrase_intervals':len(intervals),
           'old_interval_target_matches':sum(r['old_interval_contains'] for r in intervals),'new_interval_target_matches':sum(r['new_interval_contains'] for r in intervals),
           'old_whole_target_matches':sum(r['old_whole_contains'] for r in intervals),'new_whole_target_matches':sum(r['new_whole_contains'] for r in intervals),
           'gained_interval_targets':[r['id']+':'+str(r['phrase']) for r in intervals if r['new_interval_contains'] and not r['old_interval_contains']],
           'lost_interval_targets':[r['id']+':'+str(r['phrase']) for r in intervals if r['old_interval_contains'] and not r['new_interval_contains']],
           'unknown_tokens':sum(r['unknown_tokens'] for r in rows),'forward_sum_s':sum(r['forward_s'] for r in rows),
           'forward_median_s':statistics.median(r['forward_s'] for r in rows),'cold_worker_sum_s':sum(r['cold_worker_s'] for r in rows),
           'cold_worker_median_s':statistics.median(r['cold_worker_s'] for r in rows),'supervised_sum_s':supervised,
           'max_highwater_rss_mib':max(r['peak_rss_mib'] for r in rows),'max_sampled_rss_mib':max(s['rss_bytes'] for s in samples)/1048576,
           'minimum_available_mib':min(s['available_bytes'] for s in samples)/1048576,
           'max_swap_growth_mib':max(s['swap_growth_bytes'] for s in samples)/1048576,
           'max_normalization_error':max(r['normalization_error'] for r in rows),
           'new_russian_or_auxiliary_calls':0,'new_mixed_decodes':0,'human_gold_records':0}
    value={'statistics':stats,'rows':rows,'intervals':intervals,'source_commit':cfg['source_commit'],'manifest_sha256':digest(mp),
           'model_sha256':new_prepared['export_sha256'],'original_sha256':new_prepared['original_sha256'],'prepared_sha256':cfg['prepared_sha256'],
           'direct_or_transpose_matches':len(new_prepared['direct_or_transpose_parameter_matches']),
           'folded_matches':len(new_prepared['folded_parameters']),'full_operator_equivalence':new_prepared['full_operator_equivalence']}
    save(base/'round19-observation.json',value);return value


def section(root):
    value=json.loads((root.parent/'routing-repair/round19-observation.json').read_text());s=value['statistics'];esc=lambda x:html.escape(str(x));table=[];details=[]
    for r in value['intervals']:
        table.append('<tr><td>'+r['id']+' / '+str(r['phrase'])+'</td><td>'+esc(r['target_from_auxiliary'])+'</td><td>'+format(r['start_s'],'.2f')+'–'+format(r['end_s'],'.2f')+'</td><td>'+esc(r['old_interval_greedy'])+'</td><td>'+esc(r['new_interval_greedy'])+'</td><td>'+esc(r['old_interval_contains'])+' → '+esc(r['new_interval_contains'])+'</td></tr>')
    for r in value['rows']:
        details.append('<details><summary>'+r['id']+' · '+format(r['duration_s'],'.3f')+'с исходного аудио</summary>')
        for name,key in [('Прежний English-only greedy','old_english_greedy'),('Новый110M English-only greedy','new_english_greedy'),('Сохранённый смешанный вывод, не новый результат','unchanged_mixed_output'),('Qwen, не gold','auxiliary_not_gold'),('Архивный raw, не gold','archived_raw_not_gold')]:details.append('<p><b>'+name+':</b> '+esc(r[key])+'</p>')
        details.append('<p>Forward '+format(r['forward_s'],'.3f')+'с; cold worker '+format(r['cold_worker_s'],'.3f')+'с; high-water '+format(r['peak_rss_mib'],'.2f')+'MiB. Native frames '+str(r['native_frames'])+'; original samples '+str(r['whole_audio_samples'])+'; unknownIDs '+str(r['unknown_tokens'])+'.</p></details>')
    return f'''<section class="verdict"><p class="eyebrow">РАУНД 19 · ДРУГАЯ АНГЛИЙСКАЯ АКУСТИКА</p>
<h2>Компактная модель запущена; восстановления нужных имён пока нет.</h2>
<p><b>Итог: не рекомендовать замену английской головы по этим результатам.</b> В прежних интервалах остаётся GPT в c005, но точные Gemini и clear исчезают. GitHub в c009/c015/c022 и ChatGPT(Pro) в c027/c028 не появились ни в полном greedy, ни в старых интервалах. GSI в c018 и раздельное D S H в c002 не объявляются правильным восстановлением имён или языка.</p>
<p>Есть важное ограничение сравнения: clear в c020 присутствует в whole-recording выводе новой модели, хотя его нет на единственном старом EN-кадре. Это наблюдаемая несовместимость прежнего жёсткого участка с новой эмиссией, не доказательство отсутствия слова в новой акустике. Совпадение размера массивов не означает одинаковую локализацию токенов. Следующий смешанный эксперимент потребует честно заново вывести границы из новой модели, а не вручную расширять удобные места.</p>
<p>Выполнены {s['new_english_encoder_calls']} новых English-only forward на всех {s['records']} целых оригиналах, суммарно{s['audio_s']:.3f}с аудио. Нет подсказок, текстового редактирования, нарезки, дополнения тишиной или новых RU/Qwen-вызовов. Сохранены все исходные1025классов nativeCTC и tokenIDs; регистр/пунктуация не исправлялись. Смешанных новых декодирований0.</p>
<p>В прежних {s['english_phrase_intervals']} EN-интервалах буквальное casefold-совпадение с Qwen-фразой: старая акустика{s['old_interval_target_matches']}/{s['english_phrase_intervals']}, новая{s['new_interval_target_matches']}/{s['english_phrase_intervals']}. Совпадение где-либо в wholeEnglishgreedy: {s['old_whole_target_matches']}/{s['english_phrase_intervals']} → {s['new_whole_target_matches']}/{s['english_phrase_intervals']}. Появились интервальные совпадения {esc(s['gained_interval_targets'])}; исчезли {esc(s['lost_interval_targets'])}. Это модельное согласие, не human accuracy, WER или доказательство правильного языка. Границы выбраны старой моделью и могут неблагоприятно ограничивать новую.</p>
<h3>Все11старых интервалов, без ручного сдвига</h3><p>Просмотрены только соответствующие сохранённые80мсCTCкадры после полного waveform-forward. Это не распознавание аудиофрагментов. Одинаковые IDs у разных моделей не означают одинаковые обученные токены; каждый вывод читается своим vocabulary.</p><div class="scroll"><table><thead><tr><th>ID</th><th>Qwen-фраза, не gold</th><th>Прежний интервал, с</th><th>CTC0.6B int8</th><th>CTC110M F32</th><th>Совпадение</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<h3>Почему выбран этот кандидат</h3><p><a href="https://huggingface.co/nvidia/parakeet-tdt_ctc-110m">NVIDIA modelcard</a> заявляет английское обучение на36Kчасов, примерно114Mгибридныхпараметров,1024BPE и8xFastConformer. Опубликованные WER относятся кTDT, не доказаны для экспортированной CTC-ветви. <a href="https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-ctc/nemo/english.html">Sherpaдокументация</a> связывает экспорт с оригиналом. Это отдельный checkpoint, не уже проверенныйCTC0.6B или productionTDTv3.</p>
<p>Originalrev431a349f3051ab85c22b9b7a2741b5fe77065665; F32exportrev3af92f152d32c836acabf38f4c993bc96b80eb2d. Использованы оригинальные storedHann/melбуферы и существующий NeMofrontend; spectralcentering не означает добавление waveformтишины. До аудио проверены tokenizer/CTChead, все параметры экспорта: {value['direct_or_transpose_matches']} прямых/транспонированных соответствий, {value['folded_matches']} foldedпараметров. Полная операторная эквивалентность не заявлена. ЛицензияCC-BY-4.0.</p>
<p>Все{s['matching_native_clocks']}/{s['records']} размеры nativeмассивов и80мсclock/origin0 совпали со старыми. Максимальная ошибка нормализации logprobs {s['max_normalization_error']:.3g}; unknownID0 в greedy {s['unknown_tokens']}. Полные массивы сохранены до маскирования specials. Это позволяет позже проверить смешанный поиск без повторного энкодерного прохода, но ещё не является готовой интеграцией.</p>
<h3>Ресурсы: хост, холодные отдельные процессы</h3><p>Сумма model-forward {s['forward_sum_s']:.3f}с, медиана{s['forward_median_s']:.3f}с; суммаcoldworker {s['cold_worker_sum_s']:.3f}с, медиана{s['cold_worker_median_s']:.3f}с; суммаsupervised {s['supervised_sum_s']:.3f}с. High-water RSS{s['max_highwater_rss_mib']:.2f}MiB/sample{s['max_sampled_rss_mib']:.2f}MiB; минимумдоступно{s['minimum_available_mib']:.2f}MiB, swapgrowth{s['max_swap_growth_mib']:.3f}MiB. Лимит4096MiB/резерв2048MiB — агентская граница, не выделенная память. Это не Deck, не RU+EN+Qwenцепочка, не сравнение скорости с прежними Deckизмерениями.</p>
<p>Сменаcheckpoint совпадает со сменой int8→F32, поэтому различия не приписываются одной архитектуре. Новаямодель только английская: её wholeoutput на русской речи ожидаемо может быть бессмысленным, это не полная транскрипция. Нет человеческогоgold или самостоятельногоLID; production/gateway/словарь не тронуты. Источник <code>{esc(value['source_commit'])}</code>.</p>
<h3>Все28whole-recordingвыходов и сохранённые сравнения</h3>{''.join(details)}</section>'''


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    print(json.dumps(observation(a.root)['statistics'],ensure_ascii=False,indent=2))
