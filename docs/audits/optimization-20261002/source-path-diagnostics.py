"""Small source-derived logic checks. NOT execution of the Rust binary/deployment."""
import json
import pathlib
import re
import subprocess
import tempfile
import os

root=pathlib.Path(__file__).resolve().parents[3]
chunk=(root/'src/chunk.rs').read_text()
cli=(root/'src/main.rs').read_text()
assert 'chunk::chunk_text(&chunk::sanitize(text))' in cli
assert "matches!(ch, '.' | '!' | '?' | '…' | '\\n' | ';')" in chunk
# Port the sentence cut and packing for two below-limit ASCII sentences whose
# combined tagged span exceeds 120 chars. No hard_split branch or model involved.
text='<en>'+'Hello '*10+'.'+' World'*10+'!</en>'
sentences=[];current=''
for char in text:
    current+=char
    if char in '.!?…\n;':
        sentences.append(current);current=''
if current:sentences.append(current)
parts=[];current=''
for sentence in sentences:
    assert len(sentence)<=120
    if len(current)+len(sentence)>120 and current:
        parts.append(current.strip());current=''
    current+=sentence
if current.strip():parts.append(current.strip())
assert len(parts)==2
assert parts[0].startswith('<en>') and '</en>' not in parts[0]
assert parts[1].endswith('</en>') and '<en>' not in parts[1]

# Run precisely the selection pipeline, on disposable synthetic directories only.
rollback=(root/'deploy/linux/rollback.sh').read_text()
assert "sort -nr | awk 'NR == 1 { print $2 }'" in rollback
with tempfile.TemporaryDirectory(prefix='teratts-audit-rollback-selection-') as temp:
    base=pathlib.Path(temp)
    old='a'*40;active='b'*40;new_unactivated='c'*40
    for name,mtime in [(old,10),(active,20),(new_unactivated,30)]:
        directory=base/name;directory.mkdir();os.utime(directory,(mtime,mtime))
    selected=subprocess.check_output(['sh','-c',
        '''find "$1" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -path "$2" -printf '%T@ %f\\n' | sort -nr | awk 'NR == 1 { print $2 }' ''',
        'audit-selection',str(base),str(base/active)],text=True).strip()
    assert selected==new_unactivated
print(json.dumps({'kind':'source-derived/selection-only diagnostics','rust_binary_executed':False,
                  'deployment_executed':False,'cli_tagged_input':text,'raw_cli_sentence_parts':parts,
                  'rollback_selected_new_unactivated_release':selected==new_unactivated,
                  'interpretation':'CLI raw split precedes validated tags; automatic rollback uses modification order, not last activated identity'},indent=2))
