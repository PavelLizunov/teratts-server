//! Optional adapter to an operator-installed speech-front binary; no private code is linked.
use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use serde::Deserialize;

pub const MAX_EXPANDED_CHARS: usize = 12_000;
const MAX_JSON_BYTES: usize = 256 * 1024;
const DEADLINE: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextMode {
    #[default]
    Compatible,
    RussianOnly,
}

impl TextMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Compatible => "compatible",
            Self::RussianOnly => "russian_only",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConversionError {
    Configuration,
    InvalidText,
    Failed,
    InvalidOutput,
    Timeout,
}

impl std::fmt::Display for ConversionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::Configuration => "russian_only configuration is invalid",
            Self::InvalidText => "russian_only text is invalid or exceeds the expanded limit",
            Self::Failed => "russian_only converter failed",
            Self::InvalidOutput => "russian_only converter returned invalid output",
            Self::Timeout => "russian_only conversion deadline exceeded",
        })
    }
}
impl std::error::Error for ConversionError {}

type Result<T> = std::result::Result<T, ConversionError>;

pub struct Config {
    pub default_mode: TextMode,
    pub converter: Option<Converter>,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        Self::configured(
            std::env::var_os("TERATTS_TEXT_MODE"),
            std::env::var_os("TERATTS_SPEECH_FRONT_BIN"),
            std::env::var_os("TERATTS_CMUDICT_PATH"),
        )
    }

    fn configured(
        mode: Option<OsString>,
        binary: Option<OsString>,
        db: Option<OsString>,
    ) -> Result<Self> {
        let default_mode = match mode.as_deref().and_then(|s| s.to_str()) {
            None if mode.is_none() => TextMode::Compatible,
            Some("compatible") => TextMode::Compatible,
            Some("russian_only") => TextMode::RussianOnly,
            _ => return Err(ConversionError::Configuration),
        };
        let converter = match (binary, db) {
            (None, None) if default_mode == TextMode::Compatible => None,
            (Some(binary), Some(db)) => {
                let converter = Converter::new(binary.into(), db.into())?;
                if converter.convert("тест")?.text != "тест" {
                    return Err(ConversionError::InvalidOutput);
                }
                Some(converter)
            }
            _ => return Err(ConversionError::Configuration),
        };
        Ok(Self {
            default_mode,
            converter,
        })
    }
}

pub struct Converter {
    binary: PathBuf,
    db: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Conversion {
    pub text: String,
    pub readings: Vec<Reading>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reading {
    pub written: String,
    pub text: String,
    pub source: String,
    pub warnings: Vec<String>,
}

fn regular_absolute(path: &Path) -> bool {
    path.is_absolute() && std::fs::metadata(path).is_ok_and(|m| m.is_file())
}

impl Converter {
    pub(crate) fn new(binary: PathBuf, db: PathBuf) -> Result<Self> {
        if !regular_absolute(&binary) || !regular_absolute(&db) {
            return Err(ConversionError::Configuration);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if std::fs::metadata(&binary)
                .map_err(|_| ConversionError::Configuration)?
                .permissions()
                .mode()
                & 0o111
                == 0
            {
                return Err(ConversionError::Configuration);
            }
        }
        Ok(Self { binary, db })
    }

    pub fn convert(&self, text: &str) -> Result<Conversion> {
        self.convert_with_deadline(text, DEADLINE)
    }

    fn convert_with_deadline(&self, text: &str, deadline: Duration) -> Result<Conversion> {
        validate_input(text)?;
        // Paths are trusted local operator configuration, never request parameters.
        // ponytail: kill only this process; binaries spawning descendants are unsupported.
        let started = Instant::now();
        let mut child = Command::new(&self.binary)
            .arg("russian-only")
            .arg("--cmudict")
            .arg(&self.db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| ConversionError::Failed)?;
        let (Some(mut stdin), Some(stdout)) = (child.stdin.take(), child.stdout.take()) else {
            let _ = child.kill();
            let _ = child.wait();
            return Err(ConversionError::Failed);
        };
        enum Event {
            Written(std::io::Result<()>),
            Output(Result<Vec<u8>>),
        }
        let (tx, rx) = mpsc::channel();
        let writer_tx = tx.clone();
        let input = text.as_bytes().to_vec();
        let writer = match std::thread::Builder::new()
            .name("russian-only-stdin".into())
            .spawn(move || {
                let result = stdin.write_all(&input);
                drop(stdin);
                let _ = writer_tx.send(Event::Written(result));
            }) {
            Ok(thread) => thread,
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(ConversionError::Failed);
            }
        };
        let reader = match std::thread::Builder::new()
            .name("russian-only-stdout".into())
            .spawn(move || {
                let mut bytes = Vec::new();
                let result = stdout
                    .take((MAX_JSON_BYTES + 1) as u64)
                    .read_to_end(&mut bytes)
                    .map_err(|_| ConversionError::Failed)
                    .and({
                        if bytes.len() > MAX_JSON_BYTES {
                            Err(ConversionError::InvalidOutput)
                        } else {
                            Ok(bytes)
                        }
                    });
                let _ = tx.send(Event::Output(result));
            }) {
            Ok(thread) => thread,
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = writer.join();
                return Err(ConversionError::Failed);
            }
        };
        let mut written = false;
        let mut output = None;
        let mut exited = false;
        let result = (|| loop {
            if started.elapsed() >= deadline {
                return Err(ConversionError::Timeout);
            }
            while let Ok(event) = rx.try_recv() {
                match event {
                    Event::Written(result) => {
                        result.map_err(|_| ConversionError::Failed)?;
                        written = true;
                    }
                    Event::Output(result) => output = Some(result?),
                }
            }
            if !exited {
                if let Some(status) = child.try_wait().map_err(|_| ConversionError::Failed)? {
                    if !status.success() {
                        return Err(ConversionError::Failed);
                    }
                    exited = true;
                }
            }
            if exited && written {
                if let Some(bytes) = output.take() {
                    return decode(&bytes);
                }
            }
            std::thread::sleep(Duration::from_millis(5));
        })();
        if result.is_err() {
            let _ = child.kill();
        }
        let waited = child.wait();
        // Always join both workers after kill/reap; no detached pipe workers.
        let written = writer.join();
        let read = reader.join();
        if waited.is_err() || written.is_err() || read.is_err() {
            return Err(ConversionError::Failed);
        }
        result
    }
}

/// Bounded input-only substitutions, after markup flattening and before the lexicon.
/// Do not apply this to converter output: its text and trace must pass unchanged.
pub fn normalize_symbols(text: &str) -> Result<String> {
    if text.chars().count() > MAX_EXPANDED_CHARS {
        return Err(ConversionError::InvalidText);
    }
    let mut output = String::with_capacity(text.len());
    let mut count = 0;
    for (index, c) in text.char_indices() {
        let replacement = match c {
            '→' | '⇒' => " переход к ",
            '←' | '⇐' => " стрелка влево ",
            '↔' | '⇔' => " связано с ",
            '↑' => " стрелка вверх ",
            '↓' => " стрелка вниз ",
            '≈' => " примерно равно ",
            '≤' => " меньше или равно ",
            '≥' => " больше или равно ",
            '≠' => " не равно ",
            '×' => " умножить на ",
            '÷' => " разделить на ",
            '±' => " плюс минус ",
            // Keep a numeric sign attached for existing negative amounts/units.
            '−' if text[index + c.len_utf8()..].starts_with(|c: char| c.is_ascii_digit())
                && !text[..index].ends_with(char::is_alphanumeric) =>
            {
                "-"
            }
            '−' => " минус ",
            // ASCII hyphens and '+' remain untouched for approved forms and stress.
            '—' | '–' => "-",
            '[' | '{' => "(",
            ']' | '}' => ")",
            '“' | '”' | '„' => "\"",
            '‘' | '’' => "'",
            '\n' | '\t' | '\u{00a0}' => " ",
            // Exact decorative/list separators only, never an emoji/Unicode range.
            '⏵' | '✅' | '•' | '‣' | '▪' | '●' | '◦' | '·' | '│' | '─' => " ",
            _ => {
                output.push(c);
                count += 1;
                if count > MAX_EXPANDED_CHARS {
                    return Err(ConversionError::InvalidText);
                }
                continue;
            }
        };
        count += replacement.chars().count();
        if count > MAX_EXPANDED_CHARS {
            return Err(ConversionError::InvalidText);
        }
        output.push_str(replacement);
    }
    validate_input(&output)?;
    Ok(output)
}

pub fn validate_input(text: &str) -> Result<()> {
    if text.trim().is_empty()
        || text.chars().count() > MAX_EXPANDED_CHARS
        || !text
            .chars()
            .all(|c| plain_char(c) || c.is_ascii_alphabetic() || matches!(c, '<' | '>'))
    {
        Err(ConversionError::InvalidText)
    } else {
        Ok(())
    }
}

// speech-front's ordinary plaintext grammar; ASCII Latin and comparison angles
// are permitted only on input. No broader alphabet/emoji acceptance is inferred.
fn plain_char(c: char) -> bool {
    matches!(c, 'А'..='я' | 'Ё' | 'ё' | '0'..='9'
        | ' ' | '\n' | '\t' | '\r' | '\u{00a0}' | '\u{0301}')
        || ".,:;!?-—–…()[]{}«»“”„’\"'/\\_+#@%=&~$*|^".contains(c)
}

fn valid_plaintext(text: &str) -> bool {
    !text.trim().is_empty()
        && text.chars().count() <= MAX_EXPANDED_CHARS
        && text.chars().all(plain_char)
}

fn decode(bytes: &[u8]) -> Result<Conversion> {
    if bytes.len() > MAX_JSON_BYTES {
        return Err(ConversionError::InvalidOutput);
    }
    let value: Conversion =
        serde_json::from_slice(bytes).map_err(|_| ConversionError::InvalidOutput)?;
    if !valid_plaintext(&value.text)
        || value.readings.iter().any(|r| {
            r.written.trim().is_empty()
                || r.source.trim().is_empty()
                || !valid_plaintext(&r.text)
                || r.warnings.iter().any(|w| w.trim().is_empty())
        })
        || value.warnings.iter().any(|w| w.trim().is_empty())
    {
        return Err(ConversionError::InvalidOutput);
    }
    Ok(value)
}

/// Strict non-nested language markup becomes plain text with word boundaries.
/// Unlike the compatible path, English spans participate in approved lexicon matching.
pub fn flatten_tags(text: &str) -> Result<String> {
    if !text.contains('<') {
        return Ok(text.to_owned());
    }
    let mut output = String::with_capacity(text.len());
    let mut tags = String::new();
    let mut cursor = 0;
    let mut inside = false;
    let mut boundary = false;
    let append = |output: &mut String, gap: &str, boundary: &mut bool| {
        if gap.is_empty() {
            return;
        }
        if *boundary
            && !output.is_empty()
            && !output.ends_with(char::is_whitespace)
            && !gap.starts_with(char::is_whitespace)
        {
            output.push(' ');
        }
        output.push_str(gap);
        *boundary = false;
    };
    while let Some(relative) = text[cursor..].find('<') {
        let start = cursor + relative;
        append(&mut output, &text[cursor..start], &mut boundary);
        let tag = ["<ru>", "</ru>", "<en>", "</en>"]
            .into_iter()
            .find(|tag| text[start..].starts_with(tag));
        let Some(tag) = tag else {
            // Comparison symbols remain text, but tag-like unknown markup fails closed.
            if text[start + 1..]
                .trim_start()
                .starts_with(|c: char| c.is_alphabetic() || "/!?".contains(c))
            {
                return Err(ConversionError::InvalidText);
            }
            append(&mut output, "<", &mut boundary);
            cursor = start + 1;
            continue;
        };
        let closing = tag.starts_with("</");
        if inside == !closing {
            return Err(ConversionError::InvalidText);
        }
        inside = !closing;
        tags.push_str(tag);
        boundary = true;
        cursor = start + tag.len();
    }
    append(&mut output, &text[cursor..], &mut boundary);
    if !tags.is_empty() {
        crate::textnorm::validate_language_tags(&tags).map_err(|_| ConversionError::InvalidText)?;
    }
    Ok(output)
}

/// Preserve arithmetic intent before number spelling makes '+' resemble Russian stress.
pub(crate) fn protect_numeric_plus(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut output = String::with_capacity(text.len());
    for (i, &c) in chars.iter().enumerate() {
        let before = i.checked_sub(1).and_then(|j| chars.get(j)).copied();
        let after = chars.get(i + 1).copied();
        let russian = |c| matches!(c, 'А'..='я' | 'Ё' | 'ё');
        let math = before.is_some_and(|c| c.is_ascii_digit())
            || after.is_some_and(|c| c.is_ascii_digit())
            || (before.is_some_and(char::is_whitespace) && after.is_some_and(char::is_whitespace));
        if c == '+' && math && !before.is_some_and(russian) && !after.is_some_and(russian) {
            output.push_str(" плюс ");
        } else {
            output.push(c);
        }
    }
    output
}

#[cfg(all(test, unix))]
pub(crate) mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    pub(crate) fn fixture(body: &str) -> (tempfile::TempDir, Converter) {
        let dir = tempfile::tempdir().unwrap();
        let binary = dir.path().join("converter");
        let db = dir.path().join("dictionary.db");
        std::fs::write(&binary, format!("#!/bin/sh\n{body}\n")).unwrap();
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::write(&db, b"fixture").unwrap();
        let converter = Converter::new(binary, db).unwrap();
        (dir, converter)
    }

    #[test]
    fn configuration_requires_both_paths_and_probes_before_models() {
        assert!(Config::configured(None, None, None)
            .unwrap()
            .converter
            .is_none());
        assert!(Config::configured(Some("russian_only".into()), None, None).is_err());
        assert!(Config::configured(Some("bad".into()), None, None).is_err());
        assert!(Config::configured(None, Some("relative".into()), None).is_err());
        let (_dir, converter) = fixture(
            "read -r input; printf '%s' '{\"text\":\"тест\",\"readings\":[],\"warnings\":[]}'",
        );
        for mode in ["compatible", "russian_only"] {
            assert!(Config::configured(
                Some(mode.into()),
                Some(converter.binary.clone().into()),
                Some(converter.db.clone().into())
            )
            .unwrap()
            .converter
            .is_some());
        }
        assert!(Converter::new(PathBuf::from("relative"), converter.db.clone()).is_err());
        assert!(Converter::new(converter.binary.clone(), _dir.path().into()).is_err());
        std::fs::set_permissions(&converter.binary, std::fs::Permissions::from_mode(0o600))
            .unwrap();
        assert!(Converter::new(converter.binary.clone(), converter.db.clone()).is_err());
        let (_dir, invalid) = fixture("printf invalid");
        assert!(Config::configured(
            Some("russian_only".into()),
            Some(invalid.binary.into()),
            Some(invalid.db.into())
        )
        .is_err());
    }

    #[test]
    fn bounded_child_protocol_and_failure_cases() {
        let (_dir, converter) = fixture("[ \"$1\" = russian-only ] && [ \"$2\" = --cmudict ] || exit 1; read -r input; printf '%s' '{\"text\":\"тест\",\"readings\":[],\"warnings\":[]}'");
        assert_eq!(converter.convert("тест").unwrap().text, "тест");
        assert!(converter
            .convert(&"а".repeat(MAX_EXPANDED_CHARS + 1))
            .is_err());
        for body in [
            "printf bad",
            "exit 1",
            "printf '%s' '{\"text\":\"Latin\",\"readings\":[],\"warnings\":[]}'",
            "printf '%s' '{\"text\":\"тест\"}'",
        ] {
            let (_dir, converter) = fixture(body);
            assert!(converter.convert("тест").is_err());
        }
        // Shell builtins only: no descendant can inherit the pipe on timeout.
        let (_dir, converter) = fixture("while :; do :; done");
        let start = Instant::now();
        assert_eq!(
            converter
                .convert_with_deadline(&"а".repeat(MAX_EXPANDED_CHARS), Duration::from_millis(50))
                .unwrap_err(),
            ConversionError::Timeout
        );
        assert!(start.elapsed() < Duration::from_secs(2));
        let (_dir, converter) = fixture("while :; do printf '%1024s' x; done");
        assert_eq!(
            converter.convert("тест").unwrap_err(),
            ConversionError::InvalidOutput
        );
    }

    #[test]
    fn rejects_bad_json_and_unsupported_plaintext() {
        for text in ["", "abc", "тест <ru>", "тест😀", "тестé", "тест\u{0000}"] {
            let bytes =
                serde_json::to_vec(&serde_json::json!({"text":text,"readings":[],"warnings":[]}))
                    .unwrap();
            assert!(decode(&bytes).is_err());
        }
        assert!(decode(&vec![b' '; MAX_JSON_BYTES + 1]).is_err());
        let bytes = serde_json::to_vec(&serde_json::json!({"text":"а".repeat(MAX_EXPANDED_CHARS+1),"readings":[],"warnings":[]})).unwrap();
        assert!(decode(&bytes).is_err());
    }

    #[test]
    fn input_allowlist_and_symbol_bounds_do_not_relax_output_validation() {
        let ordinary = "АяЁё09 \n\t\r\u{00a0}\u{0301}.,:;!?-—–…()[]{}«»“”„’\"'/\\_+#@%=&~$*|^";
        assert!(validate_input(&format!("{ordinary}AZaz<> ")).is_ok());
        for raw in [
            "тест😀",
            "тестé",
            "тестΩ",
            "тесті",
            "тест中",
            "тест\u{200b}",
            "тест\0",
        ] {
            let (_dir, converter) = fixture("exit 1");
            assert_eq!(
                converter.convert(raw).unwrap_err(),
                ConversionError::InvalidText
            );
        }
        let exact = "а".repeat(MAX_EXPANDED_CHARS - " меньше или равно ".chars().count()) + "≤";
        assert_eq!(
            normalize_symbols(&exact).unwrap().chars().count(),
            MAX_EXPANDED_CHARS
        );
        assert_eq!(
            normalize_symbols(&(exact + "а")).unwrap_err(),
            ConversionError::InvalidText
        );
        assert_eq!(
            normalize_symbols("⏵✅•│─").unwrap_err(),
            ConversionError::InvalidText
        );
        for text in [
            "тест→",
            "тест⏵",
            "тест≤",
            "тест😀",
            "Latin",
            "<ru>тест</ru>",
        ] {
            let bytes =
                serde_json::to_vec(&serde_json::json!({"text":text,"readings":[],"warnings":[]}))
                    .unwrap();
            assert_eq!(decode(&bytes).unwrap_err(), ConversionError::InvalidOutput);
            let bytes = serde_json::to_vec(&serde_json::json!({"text":"тест","readings":[{"written":"API","text":text,"source":"structural","warnings":[]}],"warnings":[]})).unwrap();
            assert_eq!(decode(&bytes).unwrap_err(), ConversionError::InvalidOutput);
        }
        let bytes =
            br#"{"text":"\u0442\u0435\u0441\u0442","readings":[],"warnings":[],"extra":true}"#;
        assert_eq!(decode(bytes).unwrap_err(), ConversionError::InvalidOutput);
    }

    #[test]
    fn protects_arithmetic_plus_without_changing_stress_or_cpp() {
        for (input, expected) in [
            ("42+7", "42 плюс 7"),
            ("42 +7", "42  плюс 7"),
            ("2+2=4", "2 плюс 2=4"),
            ("а + б", "а  плюс  б"),
            ("C++", "C++"),
            ("молок+о", "молок+о"),
            ("+ёж", "+ёж"),
        ] {
            assert_eq!(protect_numeric_plus(input), expected);
            assert_eq!(flatten_tags(input).unwrap(), input);
        }
        assert_eq!(flatten_tags("<en>42+7</en>").unwrap(), "42+7");
    }

    #[test]
    fn flatten_preserves_all_spans_and_rejects_bad_markup() {
        assert_eq!(
            flatten_tags("а<en>Widget</en>и<ru>тест</ru>!").unwrap(),
            "а Widget и тест !"
        );
        assert_eq!(flatten_tags("1<2>0").unwrap(), "1<2>0");
        assert_eq!(flatten_tags("1 < 2 > 0").unwrap(), "1 < 2 > 0");
        assert_eq!(flatten_tags(" <ru>тест</ru>  !").unwrap(), " тест  !");
        for text in [
            "<en>x",
            "<de>x</de>",
            "<ru>x</en>",
            "<ru><en>x</en></ru>",
            "<RU>x</RU>",
        ] {
            assert!(flatten_tags(text).is_err(), "{text}");
        }
    }

    #[test]
    #[ignore = "requires operator-installed speech-front binary and CMUDICT database"]
    fn installed_converter_cross_project() {
        let binary = std::env::var_os("SPEECH_FRONT_TEST_BIN").unwrap();
        let db = std::env::var_os("SPEECH_FRONT_TEST_CMUDICT").unwrap();
        let converter = Converter::new(binary.into(), db.into()).unwrap();
        assert_eq!(converter.convert("тест").unwrap().text, "тест");
        let output = converter.convert("Hello мир").unwrap();
        assert!(valid_plaintext(&output.text));
        assert!(output.text.contains("мир"));
        assert!(!output.readings.is_empty());
        for input in [
            "<en>Hello</en> мир",
            "тест<ru>ёж</ru><en>API</en>",
            "1<2>0",
            "1 < 2 > 0",
            " <ru>тест</ru>  !",
        ] {
            let direct = converter.convert(input).unwrap();
            let flattened = converter.convert(&flatten_tags(input).unwrap()).unwrap();
            assert_eq!(
                direct.text, flattened.text,
                "tag/comparison protocol parity"
            );
        }
    }
}
