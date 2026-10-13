"""Private comparison of frozen GigaAM outputs, without embedded corpus text."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import html
import json
from pathlib import Path
import re
import statistics

from mms_pair import save, digest

HINTS = ('chatgpt', 'chatgpt pro', 'dsh', 'oracle')
NAMES = ('greedy', 'no_context', 'context')
LABELS = {'greedy': 'Обычный greedy', 'no_context': 'Beam без подсказок', 'context': 'Beam с подсказками'}


def words(text):
    return re.findall(r'\w+', text.lower().replace('ё', 'е'))


def names(text):
    # Count literal occurrences only, never whether that name was actually spoken.
    return {name: len(re.findall(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text.lower())) for name in HINTS}


def report(root, result_name):
    root = Path(root)
    directory = root / result_name
    manifest = json.loads((root / ('manifest-' + result_name.removeprefix('results-') + '.json')).read_text())
    old = json.loads((root.parent / 'collected-evaluation/comparison-final.json').read_text())
    references = {r['id']: r for r in old['records']}
    runtime = json.loads((directory / 'runtime.json').read_text())
    supervisor = json.loads((directory / 'supervisor.json').read_text())
    rows = []
    for clip in manifest['recordings']:
        path = directory / (clip['id'] + '.json')
        r = json.loads(path.read_text()) if path.exists() else {'id': clip['id'], 'status': 'unknown' if (directory / (clip['id'] + '-started.json')).exists() else 'untouched'}
        reference = references[r['id']]
        row = {'id': r['id'], 'status': r['status'], 'duration_s': clip['duration_s'],
               'stratum': clip['stratum'], 'sha256': clip['sha256'],
               'production_raw': reference['raw_text'], 'production_final': reference['final_text'],
               'previous_candidate': reference.get('candidate_text', ''),
               'previous_status': reference['pipeline_status'], 'error': r.get('error'), 'texts': {},
               'result_sha256': digest(path) if path.exists() else None}
        if r['status'] == 'success':
            row['texts'] = {'greedy': r['greedy']['raw_text'], **{n: r['variants'][n]['hypotheses'][0]['raw_text'] for n in NAMES[1:]}}
            row['latin_spans_not_language_gold'] = {n: re.findall(r"[a-zA-Z]+(?:'[a-zA-Z]+)?", t) for n, t in row['texts'].items()}
            row['literal_hint_occurrences_not_accuracy'] = {n: names(t) for n, t in row['texts'].items()}
            row['timing_s'] = {'acoustic': r['acoustic_s'], **{n: r['variants'][n]['decode_s'] for n in NAMES[1:]}, 'whole_clip': r['elapsed_s']}
            row['context_changed_text'] = words(row['texts']['no_context']) != words(row['texts']['context'])
            row['primary_agreement_not_wer'] = {n: SequenceMatcher(None, words(reference['raw_text']), words(t), autojunk=False).ratio() for n, t in row['texts'].items()}
        rows.append(row)
    good = [r for r in rows if r['status'] == 'success']
    stats = {'selected': len(rows), 'successful': len(good), 'statuses': dict(Counter(r['status'] for r in rows)),
             'audio_s': sum(r['duration_s'] for r in good), 'human_gold': 0,
             'context_changed_records': sum(r['context_changed_text'] for r in good),
             'literal_hint_record_counts': {n: {h: sum(r['literal_hint_occurrences_not_accuracy'][n][h] > 0 for r in good) for h in HINTS} for n in NAMES},
             'latin_containing_record_counts': {n: sum(bool(r['latin_spans_not_language_gold'][n]) for r in good) for n in NAMES},
             'supervised_run_wall_s': supervisor['elapsed_s'], 'load_and_verify_s': runtime['load_and_verify_s'],
             'peak_rss_mib': supervisor['peak_rss_bytes'] / 1048576,
             'minimum_available_mib': min(s['available_bytes'] for s in supervisor['samples']) / 1048576,
             'maximum_swap_growth_mib': max(0, max(s['swap_growth_bytes'] for s in supervisor['samples'])) / 1048576,
             'supervisor_stop_reason': supervisor['stop_reason'], 'host': runtime['host'],
             'temperature_sensors_available': any(s['temperatures_millic'] for s in supervisor['samples'])}
    if good:
        stats['median_timing_s'] = {n: statistics.median(r['timing_s'][n] for r in good) for n in ('acoustic', 'no_context', 'context', 'whole_clip')}
        stats['aggregate_timing_s'] = {n: sum(r['timing_s'][n] for r in good) for n in ('acoustic', 'no_context', 'context', 'whole_clip')}
        stats['context_pipeline_rtf_without_load'] = (stats['aggregate_timing_s']['acoustic'] + stats['aggregate_timing_s']['context']) / stats['audio_s']
    mass_path = root / 'native-latin-mass.json'
    if mass_path.exists():
        mass = json.loads(mass_path.read_text())
        stats['native_latin_mass'] = {
            'median_percent_of_nonblank_mass': 100 * statistics.median(r['latin_mass_fraction_nonblank'] for r in mass),
            'maximum_percent_of_nonblank_mass': 100 * max(r['latin_mass_fraction_nonblank'] for r in mass),
            'frames_latin_mass_exceeds_other_letters': sum(r['latin_exceeds_cyrillic_frames'] for r in mass),
            'native_frames': sum(r['native_frames'] for r in mass),
            'not_calibrated_language_probability': True,
        }
    save(root / 'giga-comparison-final.json', {'stats': stats, 'rows': rows, 'runtime': runtime, 'fresh_holdout': False, 'training': False})
    esc = lambda t: html.escape(str(t))
    parts = ['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GigaAM — английские вставки</title><style>body{margin:0;background:#f7f6f2;color:#202220;font:18px/1.55 Georgia,serif}main{max-width:1080px;margin:auto;padding:28px 20px 60px}h1{line-height:1.2}h2{margin-top:1.8em}table{width:100%;border-collapse:collapse;font-size:16px}td,th{padding:9px;border-bottom:1px solid #aeb4b0;text-align:left;vertical-align:top}.note{background:#e5ece7;padding:16px}blockquote{margin:8px 0 16px;padding:10px 15px;background:white;border-left:3px solid #245c45;overflow-wrap:anywhere}details{border-top:1px solid #bcc2bd;margin-top:18px;padding-top:14px}summary{cursor:pointer;font-weight:bold}small{color:#555}a{color:#245c45}.scroll{overflow:auto}@media(max-width:600px){table{font-size:13px}td,th{padding:5px}}</style><main><header><p>Повторное использование исследованной выборки · без Whisper · без обучения весов</p><h1>GigaAM: помогает ли контекст английским словам?</h1>',
             f'<p class="note"><strong>{stats["successful"]} из {stats["selected"]} записей прошли все три способа декодирования.</strong> Подсказки изменили текст в {stats["context_changed_records"]} случаях. Это число изменений, не число исправлений.</p></header>',
             '<section class="note"><h2>Наблюдаемый вывод</h2><p>В этом фиксированном прогоне все три способа выдали только кириллицу. Четыре подсказки не изменили ни одного лучшего beam-ответа. Отдельная GigaAM механически устойчивее прежней сложной связки на этой выборке, но задачу английского написания технических имён не решила. Русская речь в ряде примеров выглядит связнее; без проверенного аудиоэталона это не численная победа по точности.</p><p>Нативные вероятности дают сильное предпочтение кириллице. По сохранённым кадрам медианная доля массы латинских символов среди небланковых выходов около0,0014%; максимум по записи около0,0157%. Это не вероятность английского языка, но показывает, почему один мягкий бонус не вытянул латинский путь. Не установлено, сколько такого поведения исправит дообучение.</p><p><strong>Практический следующий шаг — проверять дообучение акустической модели на смешанных фразах, а не считать подсказки обучением английскому. Простая замена транслитераций словарём не отвечает исходному требованию.</strong> Увеличение бонусов и обучение на этой же проверочной выборке не выполнялись.</p></section>',
             '<h2>Что можно «научить»</h2><p>У русской GigaAM-v3 RNNT, использованной раньше, в обученной голове нет латиницы. Подсказка не создаёт отсутствующие выходные классы. Здесь проверена другая модель — GigaAM Multilingual Large CTC: английский уже входит в обучение, латиница есть в нативном словаре. Контекст помогает выбирать среди уже обученных выходов, но не учит произношению и не гарантирует распознавание неизвестных имён.</p>',
             '<p>Открыт весь исходный словарь: 70 символов и blank. Никакой маски алфавита или обещания жёстко отделённых RU/EN-голов. Английские и другие языки делят выходные символы. Латинские фрагменты ниже — наблюдение написания, а не доказанный язык речи.</p>',
             '<h2>Сравнение одной акустики</h2><p>Каждый неизменённый WAV прошёл полную модель один раз. Из сохранённых вероятностей получены нативный greedy, beam32 без контекста и такой же beam32 с бонусом 2,5 на символ подсказки. Четыре прежние подсказки: ChatGPT, ChatGPT Pro, DSH, Oracle. Незавершённый бонус возвращается, перекрывающиеся подсказки не получают двойного кредита. Поиск приближённый: top32 акустических символа на кадр плюс символы подсказок; совпадение подсказки не ограничено целым словом. Настройки зафиксированы до ответов и не перебирались.</p>',
             '<p>Волна не разрезалась и не дополнялась тишиной. Нет вспомогательного Whisper, LLM-переписывания, словарных замен или обучения. Production не переключался. Все 29 сохранённых записей общей длительностью 194,713 секунды использованы повторно; это уже не слепая контрольная выборка. Человеческого эталона нет.</p>',
             '<h2>Буквальные появления имён — не точность</h2><p>Количество записей, содержащих точное написание. Рост может означать как восстановленное имя, так и навязанную подсказку. Строка ChatGPT включает случаи ChatGPT Pro; строки не складываются.</p><div class="scroll"><table><tr><th>Имя</th>' + ''.join('<th>'+LABELS[n]+'</th>' for n in NAMES) + '</tr>']
    for hint in HINTS:
        parts.append('<tr><th>'+esc(hint)+'</th>'+''.join('<td>'+str(stats['literal_hint_record_counts'][n][hint])+'</td>' for n in NAMES)+'</tr>')
    parts.append('<tr><th>Любая латиница</th>'+''.join('<td>'+str(stats['latin_containing_record_counts'][n])+'</td>' for n in NAMES)+'</tr></table></div>')
    parts += ['<h2>Время и память — другой хост, не Steam Deck</h2>',
              f'<p>Хост {esc(stats["host"])}, CPU FP32, два потока; исходные веса и frontend загружены строго, пропущенных или лишних ключей нет. Проверка и загрузка: {stats["load_and_verify_s"]:.2f} с. Полный прогон с обоими beam-вариантами: {stats["supervised_run_wall_s"]:.2f} с.</p>']
    if good:
        med = stats['median_timing_s']
        parts += [f'<p>Медиана акустического прохода: {med["acoustic"]:.2f} с. Медиана отдельного beam-декодирования: {med["no_context"]:.2f} с без контекста и {med["context"]:.2f} с с контекстом. Суммарные измеренные акустика + контекстный поиск / длительность аудио: {stats["context_pipeline_rtf_without_load"]:.2f}×; загрузка и второй вариант в это отношение не входят. Это не задержка production-сервиса.</p>']
    parts += [f'<p>Пик процесса: {stats["peak_rss_mib"]:.1f} MiB при лимите 6144 MiB; минимально доступно {stats["minimum_available_mib"]:.1f} MiB при резерве 2048 MiB. Максимальный наблюдавшийся рост swap {stats["maximum_swap_growth_mib"]:.1f} MiB. Температурные датчики: {"доступны" if stats["temperature_sensors_available"] else "недоступны внутри этого хоста"}. Остановка защиты: {esc(stats["supervisor_stop_reason"])}.</p>',
              '<p>На Deck перед прогоном было доступно 3434,5 MiB; после резерва остаётся 1386,5 MiB. Один файл весов занимает около 2233 MiB, поэтому исходная FP32-модель не запускалась там рядом с production. Из этого не следует невозможность другой квантизации; она в данном тесте не проверялась.</p>',
              '<h2>Все записи: без отбора удачных</h2><p>Старый raw-текст модели — только материал для сравнения. Чтобы не повторить обучение на ошибках, ни один из этих текстов автоматически не считается правильной разметкой.</p>']
    for r in rows:
        parts.append(f'<details><summary>{esc(r["id"])} · {r["duration_s"]:.3f} с · {esc(r["status"])}'+(' · контекст изменил текст' if r.get('context_changed_text') else '')+'</summary>')
        for label, text in [('Сохранённый production raw', r['production_raw']), *[(LABELS[n], r['texts'].get(n, '')) for n in NAMES], ('Прежняя связка с Whisper', r['previous_candidate'])]:
            parts.append('<p><strong>'+esc(label)+'</strong></p><blockquote>'+esc(text or 'Нет итогового текста')+'</blockquote>')
        if r.get('error'): parts.append('<p>Ошибка: '+esc(r['error'])+'</p>')
        if 'timing_s' in r:
            parts.append('<small>Акустика '+f'{r["timing_s"]["acoustic"]:.3f}'+' с; beam без/с контекстом '+f'{r["timing_s"]["no_context"]:.3f}/{r["timing_s"]["context"]:.3f}'+' с. Латиница с контекстом: '+esc(', '.join(r['latin_spans_not_language_gold']['context']) or 'нет')+'</small>')
        parts.append('</details>')
    parts += ['<h2>Настоящее дообучение: технически возможно</h2><p><a href="https://github.com/salute-developers/GigaAM/tree/main/train_utils">Официальные инструменты</a> поддерживают дообучение CTC/RNNT и создание новой символьной головы поверх SSL-энкодера. Есть заморозка энкодера и отдельные train/validation manifests.</p>',
              '<ol><li>Для улучшения уже обученного английского — дообучать Multilingual на проверенных смешанных RU/EN фразах, добавив обычные русские и английские примеры против деградации.</li><li>Для исходного строгого требования «только обученная RU/EN-голова» — отдельная RU/EN CTC-голова с реальным обучением на двух языках. Простое удаление чужих символов этого свойства не создаёт. С нуля обучать голову на 29 фразах недостаточно для обоснованного результата.</li><li>Имена и произношения в контрольной части должны отличаться от обучающих. Оценивать и точность английских вставок, и ложные вставки в русской речи, и сохранение русских слов, а не только появление знакомых подсказок.</li></ol>',
              '<p>В текущем собранном архиве нет подтверждённых человеческих эталонов. Его можно использовать для подготовки разметки, но не объявить все старые ASR-ответы правильными. Обучение весов и расход GPU в этом прогоне не запускались; требуемый объём разметки и достижимое качество не измерены.</p>',
              '<h2>Воспроизводимость и границы</h2><p>Модель ai-sage/GigaAM-Multilingual, revision '+esc(runtime['revision'])+'; источник эксперимента '+esc(runtime['source_commit'])+'. Сохраняются оригинальные WAV-хеши, исходные численные вероятности, token IDs, баллы и ресурсы. Две подготовительные ошибки до обработки аудио устранены: недостающий import soundfile и несовместимость frontend с meta-инициализацией. После исправления каждый WAV обработан один раз; ошибочные подготовительные receipts сохранены.</p><p>Это исследование возможностей GigaAM, а не доказательство общего решения переключения языков или готовности к замене production.</p></main></html>']
    with (root / 'giga-results-final.html').open('x') as f:
        f.write('\n'.join(parts))
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root')
    p.add_argument('--results', default='results-v3')
    a = p.parse_args()
    report(a.root, a.results)
