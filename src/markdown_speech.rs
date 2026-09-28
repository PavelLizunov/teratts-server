use std::fmt;
use pulldown_cmark::{Event, Options, Parser, Tag, TagEnd};
use serde::{Deserialize, Serialize};

pub const MAX_INPUT_BYTES: usize = 64 * 1024;    // 64 KiB
pub const MAX_OUTPUT_BYTES: usize = 128 * 1024;  // 128 KiB

/// Stable revision identifying the Markdown preparation rules, parser, and options.
pub const PREPARATION_REVISION: &str = "prep-v1-cmark-0.13.4";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum InputFormat {
    #[default]
    Plain,
    Markdown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SpeechPrefixLanguage {
    #[default]
    Ru,
    En,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PreparationError {
    InputTooLarge { size: usize, limit: usize },
    OutputTooLarge { size: usize, limit: usize },
    UnsupportedHtmlBlock(String),
}

impl fmt::Display for PreparationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InputTooLarge { size, limit } => {
                write!(f, "input text exceeds limit: {size} bytes > {limit} bytes")
            }
            Self::OutputTooLarge { size, limit } => {
                write!(f, "output text exceeds limit: {size} bytes > {limit} bytes")
            }
            Self::UnsupportedHtmlBlock(tag) => {
                write!(f, "unsupported HTML block: {tag}")
            }
        }
    }
}

impl std::error::Error for PreparationError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PrepareOutcome {
    pub text: String,
    pub output_format: &'static str,
    pub preparation_revision: String,
    pub warnings: Vec<String>,
}

struct OutputSink {
    buffer: String,
    max_bytes: usize,
}

impl OutputSink {
    fn new(max_bytes: usize) -> Self {
        Self {
            buffer: String::with_capacity(1024),
            max_bytes,
        }
    }

    fn push_str(&mut self, s: &str) -> Result<(), PreparationError> {
        if self.buffer.len() + s.len() > self.max_bytes {
            return Err(PreparationError::OutputTooLarge {
                size: self.buffer.len() + s.len(),
                limit: self.max_bytes,
            });
        }
        self.buffer.push_str(s);
        Ok(())
    }

    fn push(&mut self, c: char) -> Result<(), PreparationError> {
        if self.buffer.len() + c.len_utf8() > self.max_bytes {
            return Err(PreparationError::OutputTooLarge {
                size: self.buffer.len() + c.len_utf8(),
                limit: self.max_bytes,
            });
        }
        self.buffer.push(c);
        Ok(())
    }

    fn ensure_space(&mut self) -> Result<(), PreparationError> {
        if !self.buffer.is_empty()
            && !self.buffer.ends_with(' ')
            && !self.buffer.ends_with('\n')
            && !self.buffer.ends_with("<ru>")
            && !self.buffer.ends_with("<en>")
        {
            self.push(' ')?;
        }
        Ok(())
    }

    fn push_word_or_punct(&mut self, text: &str) -> Result<(), PreparationError> {
        let first_char = text.chars().next();
        if let Some(c) = first_char {
            if c == '.' || c == ',' || c == '!' || c == '?' || c == ':' || c == ';' || c == '…' {
                while self.buffer.ends_with(' ') {
                    self.buffer.pop();
                }
                self.push_str(text)?;
                return Ok(());
            }
        }
        self.ensure_space()?;
        self.push_str(text)?;
        Ok(())
    }

    fn ensure_sentence_end(&mut self) -> Result<(), PreparationError> {
        let trimmed = self.buffer.trim_end();
        if trimmed.is_empty() {
            return Ok(());
        }
        if !trimmed.ends_with(['.', '!', '?', '…', ':', ';']) {
            while self.buffer.ends_with(' ') {
                self.buffer.pop();
            }
            self.push('.')?;
            self.push(' ')?;
        } else {
            self.ensure_space()?;
        }
        Ok(())
    }
}

/// Transform comparisons and syntax brackets in code.
/// - `x < 0` => `x меньше 0`
/// - `x > 0` => `x больше 0`
/// - `array[i]` => `array i`
/// - `<en>val</en>` in code => `en val` (literal tags, not control tags)
/// - preserves paths like `/var/lib/hermes` and numbers like `-5`.
fn clean_code_text(text: &str) -> String {
    let s = text
        .replace("<en>", " en ")
        .replace("</en>", " en ")
        .replace("<ru>", " ru ")
        .replace("</ru>", " ru ")
        .replace("<=", " меньше или равно ")
        .replace(">=", " больше или равно ")
        .replace('<', " меньше ")
        .replace('>', " больше ");

    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '{' | '}' | '[' | ']' | '(' | ')' | ';' | '"' | '_' => out.push(' '),
            other => out.push(other),
        }
    }
    collapse_whitespace(&out)
}

fn clean_prose_text(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 16);
    let mut chars = text.chars().peekable();

    while let Some(c) = chars.next() {
        match c {
            '<' => {
                if chars.peek() == Some(&'=') {
                    chars.next();
                    out.push_str(" меньше или равно ");
                } else if chars.peek() == Some(&' ') || chars.peek().is_none() {
                    out.push_str(" меньше ");
                } else {
                    // Could be `<ru>` or `<en>` which is handled by Html/InlineHtml event in pulldown,
                    // but if it arrives as text, preserve or convert
                    out.push_str(" меньше ");
                }
            }
            '>' => {
                if chars.peek() == Some(&'=') {
                    chars.next();
                    out.push_str(" больше или равно ");
                } else {
                    out.push_str(" больше ");
                }
            }
            '_' => {
                out.push(' ');
            }
            '→' | '⇒' | '←' | '⇐' | '↔' | '⇔' => {
                out.push_str(", ");
            }
            '×' => {
                out.push_str(", ");
            }
            other => {
                out.push(other);
            }
        }
    }
    collapse_whitespace(&out)
}

fn collapse_whitespace(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let mut prev_space = false;
    for c in s.chars() {
        if c.is_whitespace() {
            if !prev_space {
                result.push(' ');
                prev_space = true;
            }
        } else {
            result.push(c);
            prev_space = false;
        }
    }
    result
}

/// Balance and sanitize <ru> / <en> language tags in linear text.
fn balance_language_tags(text: &str) -> String {
    let tag_regex = [("<ru>", "</ru>"), ("<en>", "</en>")];
    let mut result = text.to_string();

    // Ensure tags are lowercase
    result = result.replace("<RU>", "<ru>").replace("</RU>", "</ru>")
                   .replace("<EN>", "<en>").replace("</EN>", "</en>");

    // Check balance
    for (open, close) in tag_regex {
        let open_count = result.matches(open).count();
        let close_count = result.matches(close).count();
        if open_count > close_count {
            for _ in 0..(open_count - close_count) {
                result.push_str(close);
            }
        } else if close_count > open_count {
            // Remove unmatched trailing close tags
            for _ in 0..(close_count - open_count) {
                if let Some(pos) = result.rfind(close) {
                    result.replace_range(pos..pos + close.len(), "");
                }
            }
        }
    }
    result
}

pub fn prepare_markdown_to_speech(
    raw: &str,
    lang: SpeechPrefixLanguage,
    max_output_bytes: usize,
) -> Result<PrepareOutcome, PreparationError> {
    if raw.len() > MAX_INPUT_BYTES {
        return Err(PreparationError::InputTooLarge {
            size: raw.len(),
            limit: MAX_INPUT_BYTES,
        });
    }

    let effective_max_output = max_output_bytes.min(MAX_OUTPUT_BYTES);
    let mut sink = OutputSink::new(effective_max_output);
    let mut warnings = Vec::new();

    let options = Options::ENABLE_TABLES | Options::ENABLE_TASKLISTS;
    let parser = Parser::new_ext(raw, options);

    let mut in_code_block = false;
    let mut table_cells: Vec<String> = Vec::new();
    let mut current_cell = String::new();
    let mut in_table_cell = false;

    for event in parser {
        match event {
            Event::Start(tag) => match tag {
                Tag::Paragraph => {
                    sink.ensure_space()?;
                }
                Tag::Heading { .. } => {
                    sink.ensure_space()?;
                }
                Tag::BlockQuote(_) => {
                    sink.ensure_space()?;
                }
                Tag::CodeBlock(..) => {
                    in_code_block = true;
                    sink.ensure_space()?;
                }
                Tag::List(..) => {
                    sink.ensure_space()?;
                }
                Tag::Item => {
                    sink.ensure_space()?;
                }
                Tag::Table(..) => {
                    sink.ensure_space()?;
                }
                Tag::TableHead | Tag::TableRow => {
                    table_cells.clear();
                }
                Tag::TableCell => {
                    in_table_cell = true;
                    current_cell.clear();
                }
                Tag::Link { .. } => {
                    // Skip url, only inner text will be collected
                }
                Tag::Image { .. } => {
                    // Alt text is processed in child events, image url is skipped
                }
                _ => {}
            },
            Event::End(tag_end) => match tag_end {
                TagEnd::Paragraph => {
                    sink.ensure_sentence_end()?;
                }
                TagEnd::Heading(..) => {
                    sink.ensure_sentence_end()?;
                }
                TagEnd::BlockQuote(_) => {
                    sink.ensure_sentence_end()?;
                }
                TagEnd::CodeBlock => {
                    in_code_block = false;
                    sink.ensure_sentence_end()?;
                }
                TagEnd::Item => {
                    sink.ensure_sentence_end()?;
                }
                TagEnd::TableCell => {
                    in_table_cell = false;
                    let trimmed = current_cell.trim();
                    table_cells.push(trimmed.to_string());
                }
                TagEnd::TableHead | TagEnd::TableRow => {
                    // Line up cells as "cell1, cell2."
                    let non_empty: Vec<&str> = table_cells
                        .iter()
                        .map(|s| s.trim())
                        .filter(|s| !s.is_empty())
                        .collect();
                    if !non_empty.is_empty() {
                        let row_text = non_empty.join(", ");
                        sink.push_str(&row_text)?;
                        sink.ensure_sentence_end()?;
                    }
                    table_cells.clear();
                }
                TagEnd::Table => {
                    sink.ensure_space()?;
                }
                TagEnd::Link => {}
                TagEnd::Image => {}
                _ => {}
            },
            Event::Text(cow_str) => {
                let text = if in_code_block {
                    clean_code_text(&cow_str)
                } else {
                    clean_prose_text(&cow_str)
                };

                if in_table_cell {
                    current_cell.push_str(&text);
                } else if !text.is_empty() {
                    sink.push_word_or_punct(&text)?;
                }
            }
            Event::Code(cow_str) => {
                let cleaned = clean_code_text(&cow_str);
                if in_table_cell {
                    current_cell.push_str(&cleaned);
                } else if !cleaned.is_empty() {
                    sink.push_word_or_punct(&cleaned)?;
                }
            }
            Event::Html(raw_html) => {
                let trimmed = raw_html.trim();
                let lower = trimmed.to_lowercase();
                if lower == "<ru>" || lower == "<en>" {
                    sink.ensure_space()?;
                    sink.push_str(&lower)?;
                } else if lower == "</ru>" || lower == "</en>" {
                    while sink.buffer.ends_with(' ') {
                        sink.buffer.pop();
                    }
                    sink.push_str(&lower)?;
                    sink.push(' ')?;
                } else {
                    return Err(PreparationError::UnsupportedHtmlBlock(trimmed.to_string()));
                }
            }
            Event::InlineHtml(raw_html) => {
                let trimmed = raw_html.trim();
                let lower = trimmed.to_lowercase();
                if lower == "<ru>" || lower == "<en>" {
                    sink.ensure_space()?;
                    sink.push_str(&lower)?;
                } else if lower == "</ru>" || lower == "</en>" {
                    while sink.buffer.ends_with(' ') {
                        sink.buffer.pop();
                    }
                    sink.push_str(&lower)?;
                    sink.push(' ')?;
                } else {
                    // Non-language inline HTML (like <b>, </b>, <span>):
                    // Strip the tag boundary itself without dropping enclosed text.
                    warnings.push(format!("stripped_inline_html: {}", trimmed));
                }
            }
            Event::TaskListMarker(checked) => {
                let prefix = match (lang, checked) {
                    (SpeechPrefixLanguage::Ru, true) => "Выполнено: ",
                    (SpeechPrefixLanguage::Ru, false) => "В планах: ",
                    (SpeechPrefixLanguage::En, true) => "Completed: ",
                    (SpeechPrefixLanguage::En, false) => "To do: ",
                };
                sink.ensure_space()?;
                sink.push_str(prefix)?;
            }
            Event::SoftBreak | Event::HardBreak => {
                sink.ensure_space()?;
            }
            _ => {}
        }
    }

    let final_raw = sink.buffer.trim();
    let balanced = balance_language_tags(final_raw);
    let final_clean = collapse_whitespace(&balanced);

    if final_clean.is_empty() {
        warnings.push("no_speakable_content".to_string());
    }

    Ok(PrepareOutcome {
        text: final_clean,
        output_format: "plain",
        preparation_revision: PREPARATION_REVISION.to_string(),
        warnings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heading_and_paragraphs_form_sentences() {
        let md = "# Заголовок статьи\n\nПервый параграф текста.\n\nВторой параграф без точки";
        let res = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(
            res.text,
            "Заголовок статьи. Первый параграф текста. Второй параграф без точки."
        );
    }

    #[test]
    fn links_and_images_keep_text() {
        let md = "Посетите [наш сайт](https://example.com/docs) и посмотрите ![логотип системы](https://example.com/img.png).";
        let res = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(
            res.text,
            "Посетите наш сайт и посмотрите логотип системы."
        );
    }

    #[test]
    fn tables_support_standard_and_empty_cells() {
        // Standard table
        let md1 = "| Параметр | Значение |\n|---|---|\n| порт | 8088 |";
        let res1 = prepare_markdown_to_speech(md1, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res1.text, "Параметр, Значение. порт, 8088.");

        // Empty second cell: | A |   |
        let md2 = "| A |   |\n|---|---|\n| x | y |";
        let res2 = prepare_markdown_to_speech(md2, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res2.text, "A. x, y.");

        // Empty first cell: |   | B |
        let md3 = "|   | B |\n|---|---|\n| x | y |";
        let res3 = prepare_markdown_to_speech(md3, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res3.text, "B. x, y.");
    }

    #[test]
    fn code_syntax_and_special_constructs() {
        // Comparison operators in inline code
        let md1 = "`x < 0` и `x > 0` и `x <= 10` и `x >= 5`";
        let res1 = prepare_markdown_to_speech(md1, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(
            res1.text,
            "x меньше 0 и x больше 0 и x меньше или равно 10 и x больше или равно 5."
        );

        // Arrays, brackets and numbers
        let md2 = "Элемент `array[i]` равен -5 или 5.";
        let res2 = prepare_markdown_to_speech(md2, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res2.text, "Элемент array i равен -5 или 5.");

        // File paths preserved
        let md3 = "Конфигурация лежит в `/var/lib/hermes/config.toml`.";
        let res3 = prepare_markdown_to_speech(md3, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res3.text, "Конфигурация лежит в /var/lib/hermes/config.toml.");

        // Literal tags in code block
        let md4 = "```rust\nlet val = \"<en>test</en>\";\n```";
        let res4 = prepare_markdown_to_speech(md4, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert!(res4.text.contains("let val = en test en"));
        assert!(!res4.text.contains("<en>"));
    }

    #[test]
    fn narrative_language_tags_preserved() {
        let md = "Обычный текст <ru>русский фрагмент</ru> и снова текст.";
        let res = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(
            res.text,
            "Обычный текст <ru>русский фрагмент</ru> и снова текст."
        );
    }

    #[test]
    fn task_lists_prefix_by_language() {
        let md = "- [x] Сделать бэкап\n- [ ] Проверить диск";

        let res_ru = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res_ru.text, "Выполнено: Сделать бэкап. В планах: Проверить диск.");

        let res_en = prepare_markdown_to_speech(md, SpeechPrefixLanguage::En, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res_en.text, "Completed: Сделать бэкап. To do: Проверить диск.");
    }

    #[test]
    fn inline_html_preserves_inner_text() {
        let md = "Это <b>важный</b> текст со <i>стилем</i>.";
        let res = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res.text, "Это важный текст со стилем.");
        assert!(res.warnings.iter().any(|w| w.contains("stripped_inline_html")));
    }

    #[test]
    fn unsupported_block_html_fails_fast() {
        let md = "<div class=\"warning\">\nНекоторый контент\n</div>";
        let err = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap_err();
        assert!(matches!(err, PreparationError::UnsupportedHtmlBlock(..)));
    }

    #[test]
    fn input_too_large_fails() {
        let large_input = "a".repeat(MAX_INPUT_BYTES + 1);
        let err = prepare_markdown_to_speech(&large_input, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap_err();
        assert!(matches!(err, PreparationError::InputTooLarge { .. }));
    }

    #[test]
    fn output_too_large_fails_fast() {
        let md = "Очень длинный текст для проверки превышения лимита вывода.";
        let err = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, 20).unwrap_err();
        assert!(matches!(err, PreparationError::OutputTooLarge { .. }));
    }

    #[test]
    fn empty_content_returns_warning() {
        let md = "   \n\n  ";
        let res = prepare_markdown_to_speech(md, SpeechPrefixLanguage::Ru, MAX_OUTPUT_BYTES).unwrap();
        assert_eq!(res.text, "");
        assert!(res.warnings.contains(&"no_speakable_content".to_string()));
    }
}
