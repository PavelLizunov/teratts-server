"""One explicitly user-approved STT spelling rule; no fuzzy matching/inference."""
import json
import hashlib
from pathlib import Path
import re

RULE_ID = "github-spelling-v1"
MATCH = re.compile(r"(?<![\w/@.\\+\-])(?:github|гитхап|гитхаб|гит[ \t]+хаб)(?![\w/@\\+\-]|\.[\w])", re.IGNORECASE)
# Don't reinterpret URLs, paths, emails, markdown link destinations or code.
PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|\n|\Z)"
    r"|https?://[^\s<>]+|[\w.+-]+@[\w.-]+"
    r"|(?:[A-Za-z]:[\\/]|(?<!\w)[./~])[\w./\\+@:-]+"
    r"|\b[\w-]+(?:[./\\][\w.-]+)+", re.IGNORECASE)


def normalize_github(text):
    protected = [match.span() for match in PROTECTED.finditer(text)]
    changes = []
    def replace(match):
        if any(start < match.end() and end > match.start() for start, end in protected):
            return match.group()
        if match.group() == "GitHub":
            return match.group()
        changes.append({"rule": RULE_ID, "start": match.start(), "end": match.end(),
                        "before": match.group(), "after": "GitHub"})
        return "GitHub"
    return MATCH.sub(replace, text), changes


def apply_dictionary(text, config_path, requested=True):
    """Return original on config failure; only GitHub may be activated here."""
    if not requested:
        return text, {"status": "request_disabled", "rule": RULE_ID, "changes": []}
    try:
        path = Path(config_path)
        if path.stat().st_size > 4096:
            raise ValueError("Oversized config")
        config_bytes = path.read_bytes()
        config = json.loads(config_bytes)
        if not isinstance(config, dict):
            raise ValueError("Invalid config")
        if config.get("github") is not True:
            return text, {"status": "config_disabled", "rule": RULE_ID, "changes": []}
    except (OSError, ValueError, TypeError):
        return text, {"status": "config_unavailable", "rule": RULE_ID, "changes": []}
    corrected, changes = normalize_github(text)
    return corrected, {"status": "applied" if changes else "unchanged", "rule": RULE_ID,
                       "changes": changes, "config_sha256": hashlib.sha256(config_bytes).hexdigest()}
