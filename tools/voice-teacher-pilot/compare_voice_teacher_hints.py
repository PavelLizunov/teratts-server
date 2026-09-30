"""Compare paired blind/hinted transcripts. No accuracy or human-gold claims."""
from collections import Counter
import json
from pathlib import Path

from run_voice_teacher_pilot import normalize


def terms_in(text, terms):
    words = normalize(text)
    found = []
    for term in terms:
        target = normalize(term)
        if target and any(words[i:i + len(target)] == target for i in range(len(words) - len(target) + 1)):
            found.append(term)
    return found


def paired_summary(blind_directory, hinted_directory):
    pairs = []
    categories = Counter()
    blind_categories = Counter()
    transitions = Counter()
    changes = 0
    vocabulary_added = Counter()
    vocabulary_removed = Counter()
    usage = Counter()
    for path in sorted(Path(hinted_directory).glob("*.json")):
        hinted = json.loads(path.read_text())
        if hinted.get("status") != "completed":
            continue
        blind_path = Path(blind_directory) / path.name
        blind = json.loads(blind_path.read_text())
        if blind.get("status") != "completed":
            raise ValueError("Blind result incomplete")
        if (blind["sample_id"], blind["audio_sha256"]) != (hinted["sample_id"], hinted["audio_sha256"]):
            raise ValueError("Unpaired audio")
        if hinted.get("teacher_saw_primary_text") or hinted.get("teacher_saw_blind_transcript"):
            raise ValueError("Contaminated hinted input")
        before, after = blind["teacher"]["transcript"], hinted["teacher"]["transcript"]
        changed = normalize(before) != normalize(after)
        changes += changed
        terms = hinted.get("vocabulary_hints", [])
        added = sorted(set(terms_in(after, terms)) - set(terms_in(before, terms)))
        removed = sorted(set(terms_in(before, terms)) - set(terms_in(after, terms)))
        vocabulary_added.update(added)
        vocabulary_removed.update(removed)
        old_category = blind["comparison"]["category"]
        category = hinted["comparison"]["category"]
        blind_categories[old_category] += 1
        categories[category] += 1
        transitions[f"{old_category} -> {category}"] += 1
        for key in ["promptTokenCount", "candidatesTokenCount", "totalTokenCount"]:
            usage[key] += hinted.get("usage", {}).get(key, 0)
        pairs.append({"sample_id": hinted["sample_id"], "normalized_text_changed": changed,
                      "vocabulary_added": added, "vocabulary_removed": removed,
                      "blind_category": old_category, "hinted_category": category})
    return {"paired_records": len(pairs), "normalized_text_changes": changes,
            "blind_categories": dict(blind_categories), "hinted_categories": dict(categories),
            "category_transitions": dict(transitions),
            "vocabulary_added": dict(vocabulary_added), "vocabulary_removed": dict(vocabulary_removed),
            "hinted_usage": dict(usage), "pairs": pairs,
            "human_gold": False, "accuracy_measured": False, "training_started": False,
            "caution": "Changes include model nondeterminism; vocabulary occurrences are not human-verified."}


if __name__ == "__main__":
    import argparse
    from run_voice_teacher_pilot import save_private
    parser = argparse.ArgumentParser()
    parser.add_argument("blind", type=Path)
    parser.add_argument("hinted", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    summary = paired_summary(args.blind, args.hinted)
    save_private(args.output, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "pairs"}, ensure_ascii=False))
