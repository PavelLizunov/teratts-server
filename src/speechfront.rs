use std::collections::{BTreeMap, HashSet};
use std::error::Error;
use std::fs;
use std::io;
use std::ops::Range;
use std::path::Path;

use chislo::{
    Gender, USD, decimal_to_words_precision, decline, int_to_words, int_to_words_gender,
    money_from_str, percent, percent_decimal_precision, time_to_words, year_to_words,
};
use serde::Deserialize;
use unicode_normalization::UnicodeNormalization;

#[derive(Deserialize)]
struct LexiconFile {
    schema_version: u32,
    entry: Vec<LexiconEntry>,
}

#[derive(Deserialize)]
struct LexiconEntry {
    written: String,
    language: String,
    spoken: String,
    #[serde(rename = "match")]
    match_kind: String,
    #[serde(default)]
    sources: Vec<String>,
    #[serde(default)]
    engines: BTreeMap<String, String>,
}

pub struct Normalizer {
    entries: Vec<LexiconEntry>,
}

impl Normalizer {
    #[allow(dead_code)]
    pub fn from_path(path: &Path) -> Result<Self, Box<dyn Error>> {
        let source = fs::read_to_string(path)?;
        Self::from_toml(&source)
            .map_err(|message| io::Error::new(io::ErrorKind::InvalidData, message).into())
    }

    /// Normalizer over the vendored approved lexicon (compile-time embedded).
    pub fn builtin() -> Result<Self, String> {
        Self::from_toml(include_str!("lexicon.toml"))
    }

    pub fn from_toml(source: &str) -> Result<Self, String> {
        let mut lexicon: LexiconFile = toml::from_str(source).map_err(|error| error.to_string())?;
        if lexicon.schema_version != 1 {
            return Err(format!(
                "unsupported lexicon schema version: {}",
                lexicon.schema_version
            ));
        }

        let mut written = HashSet::new();
        for entry in &lexicon.entry {
            if entry.written.trim().is_empty() || entry.spoken.trim().is_empty() {
                return Err("written and spoken must not be empty".to_string());
            }
            if entry.written != entry.written.trim() || entry.spoken != entry.spoken.trim() {
                return Err(format!(
                    "{}: written and spoken must not have outer whitespace",
                    entry.written
                ));
            }
            if entry.language.trim().is_empty() {
                return Err(format!("{}: language must not be empty", entry.written));
            }
            if !matches!(entry.match_kind.as_str(), "word" | "phrase") {
                return Err(format!("{}: match must be word or phrase", entry.written));
            }
            let has_whitespace = entry.written.chars().any(char::is_whitespace);
            if (entry.match_kind == "phrase") != has_whitespace {
                return Err(format!(
                    "{}: phrase must contain whitespace and word must not",
                    entry.written
                ));
            }
            if entry.sources.iter().any(|source| source.trim().is_empty()) {
                return Err(format!("{}: source must not be empty", entry.written));
            }
            if entry
                .engines
                .iter()
                .any(|(engine, spoken)| engine.trim().is_empty() || spoken.trim().is_empty())
            {
                return Err(format!("{}: invalid engine override", entry.written));
            }
            if !written.insert(entry.written.to_lowercase()) {
                return Err(format!("duplicate written form: {}", entry.written));
            }
        }

        // ponytail: 162 entries are tiny; use a sorted scan until profiling
        // justifies a matcher dependency.
        lexicon.entry.sort_by(|left, right| {
            right
                .written
                .chars()
                .count()
                .cmp(&left.written.chars().count())
        });
        Ok(Self {
            entries: lexicon.entry,
        })
    }

    #[allow(dead_code)]
    pub fn entry_count(&self) -> usize {
        self.entries.len()
    }

    pub fn normalize(&self, text: &str) -> String {
        let text: String = text.nfc().collect();
        let mut output = String::with_capacity(text.len());
        let mut gap_start = 0;
        let mut position = 0;

        while position < text.len() {
            if let Some((end, entry)) = self.longest_match(&text, position) {
                output.push_str(&normalize_segment(&text[gap_start..position]));
                output.push_str(&entry.spoken);
                position = end;
                gap_start = end;
                if let Some(suffix) = text[end..].strip_prefix('-') {
                    if let Some((used, parts)) = dotted_parts(suffix, 1) {
                        if !next_is_identifier(&text, end + 1 + used) {
                            if let Some(spoken) = speak_version_parts(&parts) {
                                output.push(' ');
                                output.push_str(&spoken);
                                position = end + 1 + used;
                                gap_start = position;
                            }
                        }
                    }
                }
            } else {
                position += text[position..].chars().next().map_or(1, char::len_utf8);
            }
        }
        output.push_str(&normalize_segment(&text[gap_start..]));
        clean_spacing(&output)
    }

    #[allow(dead_code)]
    pub(crate) fn approved_ranges(&self, text: &str) -> Vec<Range<usize>> {
        let mut ranges = Vec::new();
        let mut position = 0;
        while position < text.len() {
            if let Some((end, _)) = self.longest_match(text, position) {
                ranges.push(position..end);
                position = end;
            } else {
                position += text[position..].chars().next().map_or(1, char::len_utf8);
            }
        }
        ranges
    }

    fn longest_match<'a>(
        &'a self,
        text: &str,
        position: usize,
    ) -> Option<(usize, &'a LexiconEntry)> {
        self.entries.iter().find_map(|entry| {
            let end = end_after_chars(text, position, entry.written.chars().count())?;
            let candidate = &text[position..end];
            (candidate.to_lowercase() == entry.written.to_lowercase()
                && boundaries_match(text, position, end, &entry.written))
            .then_some((end, entry))
        })
    }
}

fn end_after_chars(text: &str, start: usize, count: usize) -> Option<usize> {
    let mut end = start;
    let mut chars = text[start..].chars();
    for _ in 0..count {
        end += chars.next()?.len_utf8();
    }
    Some(end)
}

fn boundaries_match(text: &str, start: usize, end: usize, written: &str) -> bool {
    let first = written.chars().next();
    let last = written.chars().next_back();
    let previous = text[..start].chars().next_back();
    let next = text[end..].chars().next();
    (!first.is_some_and(is_identifier_char) || !previous.is_some_and(is_identifier_char))
        && (!last.is_some_and(is_identifier_char) || !next.is_some_and(is_identifier_char))
}

fn normalize_segment(text: &str) -> String {
    let mut output = String::with_capacity(text.len());
    let mut position = 0;
    while position < text.len() {
        if let Some((used, spoken)) = parse_at(text, position) {
            output.push_str(&spoken);
            position += used;
        } else {
            let character = text[position..].chars().next().unwrap_or_default();
            output.push(character);
            position += character.len_utf8();
        }
    }
    output
}

fn parse_at(text: &str, position: usize) -> Option<(usize, String)> {
    parse_currency(text, position)
        .or_else(|| parse_version(text, position))
        .or_else(|| parse_text_date(text, position))
        .or_else(|| parse_numeric_date(text, position))
        .or_else(|| parse_time(text, position))
        .or_else(|| parse_number(text, position))
}

fn parse_currency(text: &str, position: usize) -> Option<(usize, String)> {
    let rest = &text[position..];
    if !rest.starts_with('$') || previous_is_identifier(text, position) {
        return None;
    }
    let spaces = ascii_spaces(&rest[1..]);
    let number_start = 1 + spaces;
    let number_text = &rest[number_start..];
    let (number_len, value, decimal) =
        if let Some((used, compact)) = comma_grouped_integer(number_text) {
            (used, compact, false)
        } else {
            let (used, decimal) = ascii_number(number_text)?;
            (used, number_text[..used].to_string(), decimal)
        };
    let end = position + number_start + number_len;
    if next_is_identifier(text, end) {
        return None;
    }
    let spoken = if decimal {
        money_from_str(&normalize_decimal(&value), &USD).ok()?
    } else {
        let value = parse_i64(&value)?;
        format!(
            "{} {}",
            int_to_words(value),
            decline(value, "доллар", "доллара", "долларов")
        )
    };
    Some((number_start + number_len, spoken))
}

fn parse_version(text: &str, position: usize) -> Option<(usize, String)> {
    let rest = &text[position..];
    if !matches!(rest.chars().next(), Some('v' | 'V')) || previous_is_identifier(text, position) {
        return None;
    }
    let (used, parts) = dotted_parts(&rest[1..], 2)?;
    let end = position + 1 + used;
    if next_is_identifier(text, end) {
        return None;
    }
    Some((1 + used, format!("вэ {}", speak_version_parts(&parts)?)))
}

fn parse_text_date(text: &str, position: usize) -> Option<(usize, String)> {
    if previous_is_identifier(text, position) {
        return None;
    }
    let rest = &text[position..];
    let day_len = ascii_digits(rest);
    if !(1..=2).contains(&day_len) {
        return None;
    }
    let day = rest[..day_len].parse::<u32>().ok()?;
    let spaces = ascii_spaces(&rest[day_len..]);
    if spaces == 0 {
        return None;
    }
    let month_start = day_len + spaces;
    let (month, month_written) = month_at(&rest[month_start..])?;
    let after_month = month_start + month_written.len();
    let spaces = ascii_spaces(&rest[after_month..]);
    if spaces == 0 {
        return None;
    }
    let year_start = after_month + spaces;
    let year_len = ascii_digits(&rest[year_start..]);
    if year_len != 4 {
        return None;
    }
    let year = rest[year_start..year_start + year_len]
        .parse::<u32>()
        .ok()?;
    let mut used = year_start + year_len;
    let suffix_len = optional_year_suffix(&rest[used..]);
    used += suffix_len;
    let terminal_period = suffix_len > 0
        && rest[..used].ends_with("г.")
        && rest[used..]
            .trim_start()
            .chars()
            .next()
            .is_none_or(char::is_uppercase);
    if next_is_identifier(text, position + used) {
        return None;
    }
    if !valid_date(year, month, day) {
        return Some((used, rest[..used].to_string()));
    }
    let mut spoken = spoken_date(day, month_written, year);
    if terminal_period {
        spoken.push('.');
    }
    Some((used, spoken))
}

fn parse_numeric_date(text: &str, position: usize) -> Option<(usize, String)> {
    if previous_is_identifier(text, position) {
        return None;
    }
    let rest = &text[position..];
    let day_len = ascii_digits(rest);
    if !(1..=2).contains(&day_len) {
        return None;
    }
    let separator = rest[day_len..].chars().next()?;
    if !matches!(separator, '.' | '/') {
        return None;
    }
    let month_start = day_len + separator.len_utf8();
    let month_len = ascii_digits(&rest[month_start..]);
    if !(1..=2).contains(&month_len) {
        return None;
    }
    let second_separator = rest[month_start + month_len..].chars().next()?;
    if second_separator != separator {
        return None;
    }
    let year_start = month_start + month_len + separator.len_utf8();
    let year_len = ascii_digits(&rest[year_start..]);
    if year_len != 4 {
        return None;
    }
    let day = rest[..day_len].parse::<u32>().ok()?;
    let month = rest[month_start..month_start + month_len]
        .parse::<u32>()
        .ok()?;
    let year = rest[year_start..year_start + year_len]
        .parse::<u32>()
        .ok()?;
    let used = year_start + year_len;
    if next_is_identifier(text, position + used) {
        return None;
    }
    if !valid_date(year, month, day) {
        return Some((used, rest[..used].to_string()));
    }
    Some((used, spoken_date(day, month_name(month)?, year)))
}

fn parse_time(text: &str, position: usize) -> Option<(usize, String)> {
    if previous_is_identifier(text, position) {
        return None;
    }
    let rest = &text[position..];
    let hour_len = ascii_digits(rest);
    if !(1..=2).contains(&hour_len) || !rest[hour_len..].starts_with(':') {
        return None;
    }
    let minute_start = hour_len + 1;
    let minute_len = ascii_digits(&rest[minute_start..]);
    if minute_len != 2 {
        return None;
    }
    let hour = rest[..hour_len].parse::<u32>().ok()?;
    let minute = rest[minute_start..minute_start + minute_len]
        .parse::<u32>()
        .ok()?;
    let used = minute_start + minute_len;
    if next_is_identifier(text, position + used) {
        return None;
    }
    Some((
        used,
        time_to_words(hour, minute).unwrap_or_else(|_| rest[..used].to_string()),
    ))
}

fn parse_number(text: &str, position: usize) -> Option<(usize, String)> {
    if previous_is_identifier(text, position) || attached_to_identifier(text, position) {
        return None;
    }
    let rest = &text[position..];

    if let Some((used, spoken, right)) = parse_range(rest) {
        if !next_is_identifier(text, position + used) {
            let spaces = ascii_spaces(&rest[used..]);
            let suffix_start = used + spaces;
            if rest[suffix_start..].starts_with('%') {
                let unit = decline(right, "процент", "процента", "процентов");
                return Some((suffix_start + 1, format!("{spoken} {unit}")));
            }
            return Some((used, spoken));
        }
    }

    if let Some((number_len, value)) = spaced_grouped_integer(rest) {
        if next_is_identifier(text, position + number_len) {
            return None;
        }
        let spaces = ascii_spaces(&rest[number_len..]);
        let suffix_start = number_len + spaces;
        if rest[suffix_start..].starts_with('%') {
            return Some((suffix_start + 1, percent(parse_i64(&value)?)));
        }
        if let Some((suffix_len, spoken)) = number_with_suffix(&value, &rest[suffix_start..]) {
            return Some((suffix_start + suffix_len, spoken));
        }
        return Some((number_len, int_to_words(parse_i64(&value)?)));
    }

    let sign_len = rest
        .chars()
        .next()
        .filter(|character| matches!(character, '-' | '−'))
        .map_or(0, char::len_utf8);
    let digits_len = ascii_digits(&rest[sign_len..]);
    if digits_len == 0 {
        return None;
    }
    if sign_len == 0 {
        if let Some((used, parts)) = dotted_parts(rest, 3) {
            if !next_is_identifier(text, position + used) {
                return Some((used, speak_version_parts(&parts)?));
            }
        }
    }

    let (number_len, decimal) = ascii_number(rest)?;
    let number_end = position + number_len;
    if next_is_identifier(text, number_end) {
        return None;
    }
    let value = &rest[..number_len];
    let spaces = ascii_spaces(&rest[number_len..]);
    let suffix_start = number_len + spaces;

    if rest[suffix_start..].starts_with('%') {
        let spoken = if decimal {
            let precision = fractional_digits(value) as u32;
            percent_decimal_precision(&normalize_decimal(value), precision).ok()?
        } else {
            percent(parse_i64(value)?)
        };
        return Some((suffix_start + 1, spoken));
    }

    if !decimal {
        if let Some((suffix_len, spoken)) = number_with_suffix(value, &rest[suffix_start..]) {
            return Some((suffix_start + suffix_len, spoken));
        }
    }

    let spoken = if decimal {
        let precision = fractional_digits(value) as u32;
        decimal_to_words_precision(&normalize_decimal(value), precision).ok()?
    } else {
        int_to_words(parse_i64(value)?)
    };
    Some((number_len, spoken))
}

fn parse_range(rest: &str) -> Option<(usize, String, i64)> {
    let (left_end, left) = signed_integer_prefix(rest)?;
    let separator = rest[left_end..].chars().next()?;
    if !matches!(separator, '-' | '−' | '–' | '—') {
        return None;
    }
    let right_start = left_end + separator.len_utf8();
    let (right_len, right) = signed_integer_prefix(&rest[right_start..])?;
    Some((
        right_start + right_len,
        format!("{} — {}", int_to_words(left), int_to_words(right)),
        right,
    ))
}

fn number_with_suffix(value: &str, suffix: &str) -> Option<(usize, String)> {
    let value = parse_i64(value)?;
    let variants = [
        (
            "км/ч",
            Gender::Masculine,
            ["километр", "километра", "километров"],
            " в час",
        ),
        (
            "км",
            Gender::Masculine,
            ["километр", "километра", "километров"],
            "",
        ),
        (
            "кг",
            Gender::Masculine,
            ["килограмм", "килограмма", "килограммов"],
            "",
        ),
        ("тыс.", Gender::Feminine, ["тысяча", "тысячи", "тысяч"], ""),
        ("тыс", Gender::Feminine, ["тысяча", "тысячи", "тысяч"], ""),
        (
            "млн",
            Gender::Masculine,
            ["миллион", "миллиона", "миллионов"],
            "",
        ),
        (
            "млрд",
            Gender::Masculine,
            ["миллиард", "миллиарда", "миллиардов"],
            "",
        ),
    ];
    variants.iter().find_map(|(written, gender, forms, tail)| {
        starts_with_word_case_insensitive(suffix, written).then(|| {
            let number = int_to_words_gender(value, *gender);
            let unit = decline(value, forms[0], forms[1], forms[2]);
            (written.len(), format!("{number} {unit}{tail}"))
        })
    })
}

fn dotted_parts(text: &str, minimum: usize) -> Option<(usize, Vec<&str>)> {
    let mut used = 0;
    let mut parts = Vec::new();
    loop {
        let length = ascii_digits(&text[used..]);
        if length == 0 {
            break;
        }
        parts.push(&text[used..used + length]);
        used += length;
        if !text[used..].starts_with('.') || ascii_digits(&text[used + 1..]) == 0 {
            break;
        }
        used += 1;
    }
    if parts.len() < minimum {
        None
    } else {
        Some((used, parts))
    }
}

fn speak_version_parts(parts: &[&str]) -> Option<String> {
    parts
        .iter()
        .map(|part| {
            if part.len() > 1 && part.starts_with('0') {
                part.bytes()
                    .map(|digit| {
                        digit
                            .checked_sub(b'0')
                            .map(|digit| int_to_words(i64::from(digit)))
                    })
                    .collect::<Option<Vec<_>>>()
                    .map(|words| words.join(" "))
            } else {
                part.parse::<i64>().ok().map(int_to_words)
            }
        })
        .collect::<Option<Vec<_>>>()
        .map(|words| words.join(" точка "))
}

fn spoken_date(day: u32, month: &str, year: u32) -> String {
    format!(
        "{} {month} {} года",
        DAY_GENITIVE[(day - 1) as usize],
        year_to_words(u64::from(year))
    )
}

fn month_at(text: &str) -> Option<(u32, &'static str)> {
    MONTHS.iter().enumerate().find_map(|(index, month)| {
        starts_with_word_case_insensitive(text, month).then_some(((index + 1) as u32, *month))
    })
}

fn month_name(month: u32) -> Option<&'static str> {
    MONTHS.get((month.checked_sub(1)?) as usize).copied()
}

fn valid_date(year: u32, month: u32, day: u32) -> bool {
    if year == 0 || !(1..=12).contains(&month) || day == 0 {
        return false;
    }
    let leap = year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400));
    let maximum = match month {
        2 if leap => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    };
    day <= maximum
}

fn optional_year_suffix(text: &str) -> usize {
    let spaces = ascii_spaces(text);
    let rest = &text[spaces..];
    for suffix in ["года", "год", "г."] {
        if starts_with_word_case_insensitive(rest, suffix) {
            return spaces + suffix.len();
        }
    }
    0
}

fn signed_integer_prefix(text: &str) -> Option<(usize, i64)> {
    let sign_len = text
        .chars()
        .next()
        .filter(|character| matches!(character, '-' | '−'))
        .map_or(0, char::len_utf8);
    let digits_len = ascii_digits(&text[sign_len..]);
    if digits_len == 0 {
        return None;
    }
    let used = sign_len + digits_len;
    Some((used, parse_i64(&text[..used])?))
}

fn spaced_grouped_integer(text: &str) -> Option<(usize, String)> {
    let sign_len = text
        .chars()
        .next()
        .filter(|character| matches!(character, '-' | '−'))
        .map_or(0, char::len_utf8);
    let first_len = ascii_digits(&text[sign_len..]);
    if !(1..=3).contains(&first_len) {
        return None;
    }
    let mut used = sign_len + first_len;
    let mut compact = normalize_minus(&text[..used]);
    let mut groups = 0;
    while text[used..].starts_with(' ') {
        let group_start = used + 1;
        let group_len = ascii_digits(&text[group_start..]);
        if group_len != 3 {
            break;
        }
        compact.push_str(&text[group_start..group_start + group_len]);
        used = group_start + group_len;
        groups += 1;
    }
    (groups > 0).then_some((used, compact))
}

fn comma_grouped_integer(text: &str) -> Option<(usize, String)> {
    let sign_len = text
        .chars()
        .next()
        .filter(|character| matches!(character, '-' | '−'))
        .map_or(0, char::len_utf8);
    let first_len = ascii_digits(&text[sign_len..]);
    if !(1..=3).contains(&first_len) {
        return None;
    }
    let mut used = sign_len + first_len;
    let mut compact = normalize_minus(&text[..used]);
    let mut groups = 0;
    while text[used..].starts_with(',') {
        let group_start = used + 1;
        let group_len = ascii_digits(&text[group_start..]);
        if group_len != 3 {
            break;
        }
        compact.push_str(&text[group_start..group_start + group_len]);
        used = group_start + group_len;
        groups += 1;
    }
    (groups > 0).then_some((used, compact))
}

fn ascii_number(text: &str) -> Option<(usize, bool)> {
    let sign_len = text
        .chars()
        .next()
        .filter(|character| matches!(character, '-' | '−'))
        .map_or(0, char::len_utf8);
    let integer_len = ascii_digits(&text[sign_len..]);
    if integer_len == 0 {
        return None;
    }
    let mut used = sign_len + integer_len;
    let Some(separator) = text[used..].chars().next() else {
        return Some((used, false));
    };
    if !matches!(separator, '.' | ',') {
        return Some((used, false));
    }
    let fraction_start = used + separator.len_utf8();
    let fraction_len = ascii_digits(&text[fraction_start..]);
    if fraction_len == 0 {
        return Some((used, false));
    }
    used = fraction_start + fraction_len;
    Some((used, true))
}

fn fractional_digits(value: &str) -> usize {
    value
        .find(['.', ','])
        .map_or(0, |separator| value.len() - separator - 1)
}

fn parse_i64(value: &str) -> Option<i64> {
    normalize_minus(value).parse().ok()
}

fn normalize_minus(value: &str) -> String {
    value.replace('−', "-")
}

fn normalize_decimal(value: &str) -> String {
    normalize_minus(value).replace(',', ".")
}

fn ascii_digits(text: &str) -> usize {
    text.bytes().take_while(u8::is_ascii_digit).count()
}

fn ascii_spaces(text: &str) -> usize {
    text.bytes().take_while(u8::is_ascii_whitespace).count()
}

fn previous_is_identifier(text: &str, position: usize) -> bool {
    text[..position]
        .chars()
        .next_back()
        .is_some_and(is_identifier_char)
}

fn next_is_identifier(text: &str, position: usize) -> bool {
    text[position..]
        .chars()
        .next()
        .is_some_and(is_identifier_char)
}

fn attached_to_identifier(text: &str, position: usize) -> bool {
    text[..position]
        .chars()
        .rev()
        .take_while(|character| {
            is_identifier_char(*character) || matches!(character, '-' | '.' | '/' | '+')
        })
        .any(|character| character.is_alphabetic() || character == '_')
}

fn is_identifier_char(character: char) -> bool {
    character.is_alphanumeric() || character == '_'
}

fn starts_with_word_case_insensitive(text: &str, prefix: &str) -> bool {
    let Some(end) = end_after_chars(text, 0, prefix.chars().count()) else {
        return false;
    };
    text[..end].to_lowercase() == prefix.to_lowercase()
        && !text[end..].chars().next().is_some_and(is_identifier_char)
}

fn clean_spacing(text: &str) -> String {
    let mut output = String::with_capacity(text.len());
    let mut pending_space = false;
    for character in text.chars() {
        if character.is_whitespace() {
            pending_space = !output.is_empty();
            continue;
        }
        if pending_space && !matches!(character, '.' | ',' | ';' | ':' | '!' | '?') {
            output.push(' ');
        }
        pending_space = false;
        output.push(character);
    }
    output
}

const MONTHS: [&str; 12] = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
];

const DAY_GENITIVE: [&str; 31] = [
    "первого",
    "второго",
    "третьего",
    "четвёртого",
    "пятого",
    "шестого",
    "седьмого",
    "восьмого",
    "девятого",
    "десятого",
    "одиннадцатого",
    "двенадцатого",
    "тринадцатого",
    "четырнадцатого",
    "пятнадцатого",
    "шестнадцатого",
    "семнадцатого",
    "восемнадцатого",
    "девятнадцатого",
    "двадцатого",
    "двадцать первого",
    "двадцать второго",
    "двадцать третьего",
    "двадцать четвёртого",
    "двадцать пятого",
    "двадцать шестого",
    "двадцать седьмого",
    "двадцать восьмого",
    "двадцать девятого",
    "тридцатого",
    "тридцать первого",
];

#[cfg(test)]
#[allow(clippy::panic, clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::Normalizer;

    const FIXTURE: &str = r#"
schema_version = 1

[[entry]]
written = "GPT-4.1"
language = "ru-RU"
spoken = "длинное"
match = "word"

[[entry]]
written = "GPT-4"
language = "ru-RU"
spoken = "короткое"
match = "word"
"#;

    fn normalizer() -> Normalizer {
        Normalizer::from_toml(FIXTURE).unwrap_or_else(|error| panic!("{error}"))
    }

    #[test]
    fn longest_lexicon_match_is_protected_from_numbers() {
        assert_eq!(
            normalizer().normalize("GPT-4.1 и GPT-4 выросли на 15%."),
            "длинное и короткое выросли на пятнадцать процентов."
        );
    }

    #[test]
    fn approved_term_numeric_suffix_is_not_a_negative_number() {
        let normalizer = Normalizer::from_toml(
            r#"schema_version = 1

[[entry]]
written = "GPT"
language = "ru-RU"
spoken = "джи пи ти"
match = "word"
"#,
        )
        .unwrap_or_else(|error| panic!("{error}"));
        assert_eq!(
            normalizer.normalize("GPT-4.1, GPT-4 и GPT -4"),
            "джи пи ти четыре точка один, джи пи ти четыре и джи пи ти минус четыре"
        );
    }

    #[test]
    fn normalizes_core_number_forms() {
        let normalizer = normalizer();
        assert_eq!(
            normalizer.normalize("Релиз 6 августа 2026 года в 14:30."),
            "Релиз шестого августа две тысячи двадцать шестого года в четырнадцать часов тридцать минут."
        );
        assert_eq!(
            normalizer.normalize("Версия v1.34, диапазон 3–5, точность 3,5%."),
            "Версия вэ один точка тридцать четыре, диапазон три — пять, точность три целых пять десятых процента."
        );
        assert_eq!(
            normalizer.normalize("Цена $5, скорость 90 км/ч."),
            "Цена пять долларов, скорость девяносто километров в час."
        );
        assert_eq!(
            normalizer.normalize("Дата 12.08.2026, версия v1.02.300."),
            "Дата двенадцатого августа две тысячи двадцать шестого года, версия вэ один точка ноль два точка триста."
        );
        assert_eq!(
            normalizer.normalize("Диапазон 10–15%, релиз 6 августа 2026 г. Затем."),
            "Диапазон десять — пятнадцать процентов, релиз шестого августа две тысячи двадцать шестого года. Затем."
        );
        assert_eq!(
            normalizer.normalize("Рост 1–2%, релиз 6 августа 2026 г. состоялся."),
            "Рост один — два процента, релиз шестого августа две тысячи двадцать шестого года состоялся."
        );
    }

    #[test]
    fn handles_grouping_ranges_and_unit_case() {
        let normalizer = normalizer();
        assert_eq!(
            normalizer.normalize("Путь -5–3, затем 1 000 км и 90 КМ/Ч."),
            "Путь минус пять — три, затем одна тысяча километров и девяносто километров в час."
        );
        assert_eq!(
            normalizer.normalize("Цена $1,000."),
            "Цена одна тысяча долларов."
        );
    }

    #[test]
    fn preserves_invalid_date_and_time_tokens() {
        assert_eq!(
            normalizer().normalize("31.02.2026 и 25:70"),
            "31.02.2026 и 25:70"
        );
    }

    #[test]
    fn preserves_unknown_identifiers() {
        assert_eq!(
            normalizer().normalize("Win11 x86_64 UnseenTool GPT-5.6"),
            "Win11 x86_64 UnseenTool GPT-5.6"
        );
    }

    #[test]
    fn cleans_unicode_and_whitespace() {
        assert_eq!(
            normalizer().normalize("маи\u{306}\n\n  5%"),
            "май пять процентов"
        );
    }

    #[test]
    fn production_lexicon_keeps_horizon_migration_baseline() {
        let lexicon = include_str!("lexicon.toml");
        let normalizer = Normalizer::from_toml(lexicon).unwrap_or_else(|error| panic!("{error}"));
        assert!(normalizer.entry_count() >= 162);
        assert_eq!(
            normalizer.normalize("Релиз вышел 6 августа 2026 года"),
            "Релиз вышел шестого августа две тысячи двадцать шестого года"
        );
    }
}
