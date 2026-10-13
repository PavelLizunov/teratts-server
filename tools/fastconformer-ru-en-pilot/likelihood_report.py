"""Private HTML section for independent candidate-likelihood observations."""
import html
import json
import statistics


def section(root):
    summary=json.loads((root/'likelihood-sequential/summary.json').read_text())
    if summary['status']!='success':raise ValueError('Likelihood run is not complete')
    rows=summary['rows'];controls=[r for r in rows if r['reference'] is not None];real=[r for r in rows if r['reference'] is None]
    corpus=[r for r in real if r['kind']=='collected_asr_no_human_gold']
    match=sum(r['normalized_equal_reference'] is True for r in controls)
    changed=sum(r['normalized_equal_input'] is False for r in corpus)
    ambiguous=sum(r['selected_text'] is None for r in rows)
    def esc(x):return html.escape(str(x))
    def table(headers,data):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in data)+'</tbody></table></div>'
    invariant=json.loads((root/'likelihood-sequential/selection-invariance.json').read_text())
    title='<section class="verdict"><p class="eyebrow">ДОПОЛНЕНИЕ · НЕЗАВИСИМЫЙ ЧИСЛЕННЫЙ ВЫБОР</p><h2>Текст сохраняется лучше. Распознавание ещё не исправлено.</h2>'
    intro=f'<p>Теперь Qwen3 получает исходную расшифровку и один фиксированный кандидат за раз. Ничего не генерирует: измеряется средняя log probability токенов кандидата и конца ответа. Всего <b>35 случаев, 110 уникальных кандидатных путей</b>, плюс 2 численных проверки. Это новый метод, не повтор генерации номера из списка.</p><p>Синтетические контроли: <b>{match}/{len(controls)}</b> совпадений нормализованных слов с эталоном. На корпусе выбранный текст отличается от первого акустического варианта в <b>{changed}/{len(corpus)}</b> случаях. Неоднозначных максимумов: {ambiguous}. Различия не равны исправлениям — человеческого эталона нет.</p>'
    method='<p>Модель, веса Q8_0 и консервативная инструкция прежние. Каждый кандидат вычисляется с пустым KV; порядок лексически канонизирован, одинаковые пути переиспользуют сохранённую оценку. В prompt нет других кандидатов. Перестановка уже оценённых вариантов не меняет их scores; равные максимумы не разрешаются номером пункта. Это свойство построения, не новая серия модельных тестов перестановки.</p><p>Вероятность текста всё ещё не доказывает, что именно он произнесён. Кондиционирование на ошибочном исходном ASR может лишь закрепить его ошибку. Среднее по токенам также имеет смещение по длине; суммы сохранены только для диагностики, иной вариант нормализации не подбирался.</p>'
    runtime=f'<p>Локальный CPU2, полное время {summary["elapsed_s"]:.3f} с; медиана оценки всех кандидатов одного случая {statistics.median(r["evaluation_s"] for r in rows):.3f} с; sampled peak RSS {max(s["rss_bytes"] for s in summary["samples"])/1048576:.1f} MiB; минимум доступной памяти {min(s["available_bytes"] for s in summary["samples"])/1048576:.1f} MiB при резерве 2048 MiB. Это не измерение Steam Deck или общей ASR-цепочки.</p>'
    caveat=f'<p><b>Численная оговорка:</b> предыдущий пакетный метод дважды остановлен до кандидатов: chunk64 и chunk1 дали расхождение 0.0320915, выше фиксированного допуска 0.001. Отключение перепаковки не помогло. Допуск не ослаблялся. Новая реализация использует только chunk1 для всех токенов. Её более узкая проверка причинности прошла: изменение будущего суффикса не изменило оценки {summary["causal_smoke_shared_targets"]} общих токенов (максимальная разница {summary["causal_smoke_max_difference"]}). Это не доказательство равенства другому runtime.</p>'
    control_table=table(['Контроль','Совпадение','Исходный текст','Выбранный текст'],[[r['id'],r['normalized_equal_reference'],r['input'],r['selected_text']] for r in controls])
    changes=table(['ASR-пример','Исходный текст','Выбранный текст','Утраченные защищённые токены','Отрицания до / после'],[[r['id'],r['input'],r['selected_text'],r['protected_missing'],r['negative_tokens_before_after']] for r in real if not r['normalized_equal_input']])
    all_scores=[]
    for r in rows:
        all_scores.append('<details><summary>'+esc(r['id'])+' · '+esc(r['kind'])+'</summary>'+table(['Кандидат','Средний logP ↑','Сумма logP','Число target-токенов','Расчёт, с'],[[c['text'],f"{c['mean_logprob']:.6f}",f"{c['sum_logprob']:.6f}",c['target_tokens'],f"{c['elapsed_s']:.3f}"] for c in sorted(r['candidates'],key=lambda c:c['mean_logprob'],reverse=True)])+'</details>')
    verdict='<p><b>Вывод:</b> численное ранжирование консервативнее генерации номера: 19/20 корпусных текстов и обе исходные записи сохранены. На одной корпусной записи удалён конечный фрагмент; без human gold это не объявляется исправлением. Остаточная ошибка на длинной записи осталась. Ускорение или обучение здесь не проводились; в рабочую цепочку метод не включён.</p><p>Перебраны все '+str(invariant['score_set_permutations'])+' перестановки уже сохранённых score-наборов: победившие тексты одинаковы, дополнительных model calls — 0. Не обнаружено пропусков защищённых Latin/числовых токенов или изменения счётчика отрицаний; это ограниченные индикаторы, не доказательство эквивалентности смысла. До успешного запуска были 4 отдельные синтетические вычислительные пробы в двух неудачных пакетных запусках; они не вычеркнуты из истории.</p>'
    return title+intro+verdict+method+runtime+caveat+'<h3>Все синтетические контроли</h3>'+control_table+'<h3>Изменившиеся реальные тексты</h3>'+changes+'<h3>Полные оценки без отбора удачных примеров</h3>'+''.join(all_scores)+'</section>'
