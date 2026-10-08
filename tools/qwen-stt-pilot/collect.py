"""Verify all paired receipts and prepare private readable comparison, not WER."""
import hashlib
import json
from pathlib import Path
from run import atomic_json, validate_record


def collect(root):
    root = Path(root)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    baseline = json.loads((root / 'parakeet-results.json').read_text())
    if baseline['exit_code'] != 0 or baseline['manifest_sha256'] != sha:
        raise ValueError('baseline incomplete or wrong manifest')
    base = {r['id']: r for r in baseline['records']}
    pairs = []
    for row in manifest['records']:
        validate_record(row)
        candidate = json.loads((root / 'qwen-results' / (row['id'] + '.json')).read_text())
        b = base[row['id']]
        if candidate['status'] != 'success' or candidate['exit_code'] != 0 or b['status'] != 'success':
            raise ValueError('unsuccessful pair')
        if candidate['sha256'] != row['sha256'] or b['sha256'] != row['sha256'] or candidate['manifest_sha256'] != sha:
            raise ValueError('pair hash mismatch')
        if candidate['hints'] is not False:
            raise ValueError('candidate hints are prohibited')
        pairs.append(dict(category=row['category'], id=row['id'], seconds=row['seconds'],
                          synthetic=row['synthetic'], audio_sha256=row['sha256'],
                          parakeet_text=b['text'], qwen_text=candidate['text'],
                          parakeet_wall_s=b['elapsed_s'], qwen_wall_s=candidate['elapsed_s'],
                          qwen_peak_rss_bytes=candidate['peak_rss_bytes'],
                          retained_baseline_equals_replay=None if row['synthetic'] else row['metadata']['raw_text'] == b['text'],
                          human_reference=row['human_reference']))
    summary = dict(manifest_sha256=sha, paired_success=len(pairs), speech_seconds=manifest['speech_seconds'],
                   qwen_total_wall_s=sum(r['qwen_wall_s'] for r in pairs),
                   qwen_peak_rss_bytes=max(r['qwen_peak_rss_bytes'] for r in pairs),
                   negative_controls={model: {r['id']: r[model + '_text'] for r in pairs if r['synthetic']}
                                      for model in ['parakeet', 'qwen']},
                   accuracy='No human references; no WER or universal winner',
                   latency='Different hosts/precisions; candidate includes process/model startup, baseline resident GPU model',
                   pairs=pairs)
    atomic_json(root / 'comparison-private.json', summary)
    lines = ['# Личный тест Parakeet и Qwen3-ASR-1.7B', '',
             f"Проверены {len(pairs)} пар: пять записей ({manifest['speech_seconds']:.1f} секунды) и два контроля.",
             'Эталонных ручных расшифровок нет: это сравнение гипотез, а не измерение WER.',
             'Parakeet: Steam Deck Vulkan, резидентная модель. Qwen: отдельный CPU-хост, запуск процесса на каждый WAV.', '']
    for index, row in enumerate(pairs, 1):
        lines.extend([f"## {index}. {row['category']}, {row['seconds']:.1f} с", '',
                      f"[Исходное аудио](<{manifest['records'][index-1]['path']}>)", '',
                      '**Parakeet:** ' + (row['parakeet_text'] or 'Пустой текст.'), '',
                      '**Qwen:** ' + (row['qwen_text'] or 'Пустой текст.'), ''])
    path = root / 'comparison-private.md'
    path.write_text('\n'.join(lines))
    path.chmod(0o600)
    print(json.dumps({k:v for k,v in summary.items() if k!='pairs'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('root')
    collect(p.parse_args().root)
