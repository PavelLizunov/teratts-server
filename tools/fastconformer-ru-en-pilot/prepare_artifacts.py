"""Verify original AggregateTokenizer order against every exported class ID."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import sentencepiece as spm
import yaml


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(original, export, output):
    original, export, output = map(Path, (original, export, output))
    config_path = original / 'model_config.yaml'
    config = yaml.safe_load(config_path.read_text())
    if config['tokenizer']['type'] != 'agg':
        raise ValueError('Original checkpoint is not an aggregate tokenizer')
    exported = {}
    for line in (export / 'tokens.txt').read_text().splitlines():
        piece, idx = line.rsplit(' ', 1)
        if int(idx) in exported:
            raise ValueError('Duplicate numerical class ID')
        exported[int(idx)] = piece
    if len(exported) != len(config['joint']['vocabulary']) + 1:
        raise ValueError('Export vocabulary size differs from original')
    if any(exported[i] != p for i, p in enumerate(config['joint']['vocabulary'])):
        raise ValueError('Export class order differs from original checkpoint')
    if exported[len(exported) - 1] != '<blk>':
        raise ValueError('Blank is not last')
    if output.exists():
        raise FileExistsError('Refuse to replace prepared artifact bundle')
    output.mkdir(mode=0o700, parents=True)
    offsets, models, vocab, hashes = {}, {}, [], {}
    for lang, settings in config['tokenizer']['langs'].items():
        reference = settings['model_path']
        if not reference.startswith('nemo:') or Path(reference[5:]).name != reference[5:]:
            raise ValueError('Unexpected original artifact reference')
        path = original / reference[5:]
        sp = spm.SentencePieceProcessor(model_file=str(path))
        pieces = [sp.id_to_piece(i) for i in range(sp.get_piece_size())]
        offsets[lang] = {'offset': len(vocab), 'size': len(pieces), 'unk_id': sp.unk_id()}
        if any(exported[len(vocab) + i] != p for i, p in enumerate(pieces)):
            raise ValueError('Tokenizer/export disagreement for ' + lang)
        vocab.extend(pieces)
        if lang in ('ru', 'en'):
            destination = output / (lang + '.model')
            shutil.copyfile(path, destination)
            models[lang] = destination.name
            hashes[destination.name] = sha256(destination)
    if vocab != config['joint']['vocabulary']:
        raise ValueError('Original tokenizers do not reconstruct joint vocabulary')
    for path in export.iterdir():
        if path.name.endswith('.onnx') or path.name == 'tokens.txt':
            destination = output / path.name
            shutil.copyfile(path, destination)
            hashes[path.name] = sha256(destination)
    allowed = sorted(i for lang in ('ru', 'en') for i in range(
        offsets[lang]['offset'], offsets[lang]['offset'] + offsets[lang]['size']))
    receipt = {'languages': offsets, 'allowed_languages': ['ru', 'en'],
               'allowed_token_ids': allowed, 'blank_id': len(vocab),
               'tokenizer_models': models, 'config_sha256': sha256(config_path),
               'files_sha256': hashes, 'preprocessor': config['preprocessor'],
               'decoder': config['decoder']['prednet'],
               'joint_vocabulary_verified': True,
               'limitation': 'Allowed language-branch IDs do not guarantee semantic language identity'}
    (output / 'artifacts.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({'languages': offsets, 'blank_id': len(vocab),
                      'all_original_and_export_ids_match': True}, indent=2))
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--original', required=True)
    p.add_argument('--export', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    prepare(a.original, a.export, a.output)
