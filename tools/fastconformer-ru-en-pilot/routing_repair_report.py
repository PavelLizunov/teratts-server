"""Private result section: timing dependency repair, not accuracy recovery."""
import html
import json
from collections import Counter


def section(root):
    base=root.parent/'routing-repair';manifest=json.loads((base/'manifest.json').read_text());folder=base/'round11-results'
    rows=[json.loads((folder/(r['id']+'.json')).read_text()) for r in manifest['recordings']];supervisor=json.loads((folder/'supervisor-summary.json').read_text())
    counts=Counter(r['status'] for r in rows)
    def esc(v):return html.escape(str(v))
    cells=[]
    for row in rows:
        text=row.get('search',{}).get('hypotheses',[{}])[0].get('postprocessed_text','—')
        cells.append('<tr><td>'+esc(row['id'])+'</td><td>'+esc(row['status'])+'</td><td>'+esc(row.get('selected_events_identical','—'))+'</td><td>'+esc(row.get('decode_s','—'))+'</td><td>'+esc(text)+'</td><td>'+esc(row.get('error',''))+'</td></tr>')
    new=next(r for r in rows if r['status']=='new_constrained_output')
    return '<section class="verdict"><p class="eyebrow">РАУНД 11 · ИСПРАВЛЕНИЕ ВРЕМЕННОЙ ПОДСКАЗКИ</p><h2>Один отказ устранён без повторного распознавания аудио.</h2>'+f'''<p>В прежней цепочке все слова вспомогательной расшифровки проходили токенизацию RU/EN, хотя следующий этап использует только английские фразы. Русская буква, отсутствующая в русской голове, могла остановить обработку ещё до декодирования. Теперь русские вспомогательные слова обозначают только промежуток между английскими фразами и не подаются в русскую голову.</p>
<p><b>Новая извлечённая временная подсказка не является фильтром финального алфавита.</b> Финальный текст остаётся открытым поиском по настоящим обученным RU/EN головам. Слова из Whisper не копируются в результат, замены «ё→е» нет, неизвестные Latin/смешанные слова и невозможные повторы не скрываются.</p>
<p>Из 28 записей с полными сохранёнными выходами голов: <b>{counts['reused_unchanged']} прежних успешных маршрутов совпали точно</b>, их декодер не запускался снова; <b>{counts['new_constrained_output']} запись получила новый результат</b>; {counts['unalignable_auxiliary']} остались с невозможной последовательностью английских фраз; {counts['unsupported_auxiliary']} — с неподдерживаемым вспомогательным словом. Ещё одна из первоначальных 29 попыток не имеет полного набора выходов после прежнего RSS-отказа и исключена без повторного акустического прогона.</p>
<p>Механическая доступность результата с этим дополнением: 22 из 29 прежних попыток вместо 21. <b>Исходный результат эксперимента 21/29 не переписывается.</b> Получение строки не означает верное распознавание.</p>
<h3>Восстановленная запись</h3><p><b>Вспомогательный текст, не эталон:</b> {esc(new['auxiliary_raw_text'])}</p><p><b>Новый вывод обученных голов:</b> {esc(new['search']['hypotheses'][0]['postprocessed_text'])}</p>
<p>Технические имена и конец фразы по-прежнему расходятся с вспомогательным текстом. Без human gold невозможно назвать расхождения точностью или WER. Устранена ненужная зависимость, но проблема смешанной речи не решена.</p>
<h3>Стоимость и границы проверки</h3><p>Весь проход по сохранённым данным: {supervisor['elapsed_s']:.3f} с. Единственный новый финальный decode: {new['decode_s']:.3f} с. Максимальный sampled RSS {max(s['rss_bytes'] for r in supervisor['rows'] for s in r['samples'])/1048576:.2f} MiB; минимум доступной памяти {min(s['available_bytes'] for r in supervisor['rows'] for s in r['samples'])/1048576:.2f} MiB. Это локальный CPU с сохранёнными Deck-активациями, не новый замер Deck или полного ASR.</p>
<p>Пять focused unit-test методов написаны, но платформа заблокировала запуск до выполнения. Они не объявляются пройденными. Сам разрешённый retained-data прогон завершился exit0; проверка точного совпадения 21 старого маршрута выполнена внутри него. Опциональная интеграция <code>auxiliary_timing_mode=english-only</code> добавлена в экспериментальный pipeline, но отдельно на аудио не прогонялась; старые манифесты сохраняют legacy-поведение. Production не изменён.</p>
<p>Манифест создан до коммита и содержит родительский source_commit; точные хеши исполнявшихся исходников сохранены в source_files, фактический код прогона — 957b46b. Старые неудачи и данные сохранены.</p>
<h3>Все 28 наблюдений</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Статус</th><th>Прежний маршрут совпал</th><th>Новый decode, с</th><th>Итоговая строка / сохранённый результат</th><th>Причина отказа</th></tr></thead><tbody>'''+''.join(cells)+'</tbody></table></div></section>'
