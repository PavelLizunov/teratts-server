//! Local-only Russian stress annotation, ported from the pinned
//! `/tmp/teratts_ruaccent.py` runtime.
//!
//! Dictionary assets are gzip-compressed JSON maps. Full mode additionally
//! loads the four bundled ONNX graphs and Hugging Face tokenizer files from the
//! supplied root; this module never performs network access.

use std::collections::HashMap;
use std::fs::File;
use std::io::Read;
use std::ops::Range;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use flate2::read::GzDecoder;
use ort::session::{Session, SessionInputValue};
use ort::value::Tensor;
use regex::Regex;
use serde::de::DeserializeOwned;
use tokenizers::{EncodeInput, Encoding, Tokenizer, TruncationParams, TruncationStrategy};

const MODEL_SIZE: &str = "turbo3.1";
const VOWELS: &str = "аеёиоуыэюяАЕЁИОУЫЭЮЯ";
const PUNCTUATION: &str = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";

/// Runtime behavior. Disabled mode loads no assets and returns input unchanged.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuAccentMode {
    Full,
    Dictionary,
    Disabled,
}

/// Local asset root and selected behavior.
#[derive(Debug, Clone)]
pub struct RuAccentConfig {
    pub root: PathBuf,
    pub mode: RuAccentMode,
}

impl RuAccentConfig {
    pub fn new(root: impl Into<PathBuf>, mode: RuAccentMode) -> Self {
        Self {
            root: root.into(),
            mode,
        }
    }
}

/// Local RUAccent runtime. In full mode inference requires `&mut self` because
/// ort 2.0.0-rc.13 deliberately makes `Session::run` exclusive.
#[derive(Debug)]
pub struct RuAccent {
    mode: RuAccentMode,
    accents: HashMap<String, String>,
    omographs: HashMap<String, Vec<String>>,
    yo_words: HashMap<String, String>,
    yo_homographs: HashMap<String, String>,
    normalize: Regex,
    words: Regex,
    dictionary_words: Regex,
    sentences: Regex,
    models: Option<FullModels>,
}

#[derive(Debug)]
struct FullModels {
    accent: CharAccentModel,
    omograph: PairClassifier,
    stress_usage: TokenClassifier,
    yo: TokenClassifier,
}

#[derive(Debug)]
struct CharAccentModel {
    session: Session,
    output: String,
    labels: Vec<String>,
    vocab: HashMap<String, i64>,
    unknown: i64,
    bos: i64,
    eos: i64,
}

#[derive(Debug)]
struct TokenClassifier {
    session: Session,
    output: String,
    labels: Vec<String>,
    tokenizer: Tokenizer,
    continuing_subword_prefix: Option<String>,
    unknown_id: Option<u32>,
}

#[derive(Debug)]
struct PairClassifier {
    session: Session,
    output: String,
    tokenizer: Tokenizer,
    pad_id: u32,
}

#[derive(Debug)]
struct ClassifiedWord {
    entity: String,
}

impl RuAccent {
    /// Load the local asset closure required by `mode`.
    pub fn load(root: impl AsRef<Path>, mode: RuAccentMode) -> Result<Self> {
        Self::new(RuAccentConfig::new(root.as_ref().to_path_buf(), mode))
    }

    /// Load only assets required by the selected mode.
    pub fn new(config: RuAccentConfig) -> Result<Self> {
        let normalize = Regex::new(r#"[^a-zA-Z0-9\sа-яА-ЯёЁ—.,!?:;'(){}\[\]«»„“”\-]"#)?;
        let words = Regex::new(r"\w*(?:\+\w+)*|[^\w\s]+")?;
        let dictionary_words = Regex::new(r"[A-Za-zА-Яа-яЁё]+")?;
        let sentences = Regex::new(r#"[^.!?…]+[.!?…]*[\"»“]*"#)?;
        if config.mode == RuAccentMode::Disabled {
            return Ok(Self {
                mode: config.mode,
                accents: HashMap::new(),
                omographs: HashMap::new(),
                yo_words: HashMap::new(),
                yo_homographs: HashMap::new(),
                normalize,
                words,
                dictionary_words,
                sentences,
                models: None,
            });
        }

        let dictionary = config.root.join("dictionary");
        let mut accents: HashMap<String, String> =
            read_gzip_json(&dictionary.join("accents.json.gz"))?;
        let mut omographs: HashMap<String, Vec<String>> =
            read_gzip_json(&dictionary.join("omographs.json.gz"))?;
        let yo_words: HashMap<String, String> =
            read_gzip_json(&dictionary.join("yo_words.json.gz"))?;
        let yo_homographs: HashMap<String, String> =
            read_gzip_json(&dictionary.join("yo_homographs.json.gz"))?;
        accents.insert("о".into(), "+о".into());
        accents.insert("О".into(), "+О".into());
        omographs.insert("коса".into(), vec!["к+оса".into(), "кос+а".into()]);

        let models = if config.mode == RuAccentMode::Full {
            let nn = config.root.join("nn");
            Some(FullModels {
                accent: CharAccentModel::load(&nn.join("nn_accent"))?,
                omograph: PairClassifier::load(&nn.join("nn_omograph").join(MODEL_SIZE))?,
                stress_usage: TokenClassifier::load(&nn.join("nn_stress_usage_predictor"))?,
                yo: TokenClassifier::load(&nn.join("nn_yo_homograph_resolver"))?,
            })
        } else {
            None
        };

        Ok(Self {
            mode: config.mode,
            accents,
            omographs,
            yo_words,
            yo_homographs,
            normalize,
            words,
            dictionary_words,
            sentences,
            models,
        })
    }

    /// Process contents of balanced `<ru>...</ru>` spans and preserve tags,
    /// English spans, and untagged text byte-for-byte. Nested language tags are
    /// rejected because Tera's language spans are not nestable.
    pub fn process_ru_spans(&mut self, text: &str) -> Result<String> {
        let spans = russian_tag_spans(text)?;
        self.accent_ru_spans(text, &spans)
    }

    /// Accent an untagged Russian text fragment according to the configured mode.
    pub fn accent(&mut self, text: &str) -> Result<String> {
        if self.mode == RuAccentMode::Disabled {
            return Ok(text.to_string());
        }
        let normalized = self.normalize.replace_all(text, "").into_owned();
        if self.mode == RuAccentMode::Dictionary {
            Ok(self.process_dictionary(&normalized))
        } else {
            self.process_full(&normalized)
        }
    }

    /// Accent selected Russian byte spans while preserving all other text.
    ///
    /// Spans must be sorted, non-overlapping UTF-8 boundaries. A span containing
    /// any explicit `+` marker is copied as a whole: manual stress therefore has
    /// precedence over dictionary and neural output for the entire language span.
    pub fn accent_ru_spans(&mut self, text: &str, spans: &[Range<usize>]) -> Result<String> {
        validate_spans(text, spans)?;
        let mut output = String::with_capacity(text.len() + spans.len() * 2);
        let mut cursor = 0;
        for span in spans {
            output.push_str(&text[cursor..span.start]);
            let source = &text[span.clone()];
            if source.contains('+') {
                output.push_str(source);
            } else {
                output.push_str(&self.accent(source)?);
            }
            cursor = span.end;
        }
        output.push_str(&text[cursor..]);
        Ok(output)
    }

    fn process_dictionary(&self, text: &str) -> String {
        self.dictionary_words
            .replace_all(text, |captures: &regex::Captures<'_>| {
                let word = captures.get(0).map_or("", |m| m.as_str());
                let normalized = fix_capital(
                    word,
                    self.yo_words
                        .get(&word.to_lowercase())
                        .map_or(word, String::as_str),
                );
                let lowered = normalized.to_lowercase();
                self.accents
                    .get(&lowered)
                    .map_or(normalized.clone(), |accented| {
                        transfer_markers(&normalized, accented)
                    })
            })
            .into_owned()
    }

    fn process_full(&mut self, text: &str) -> Result<String> {
        let mut output = String::with_capacity(text.len() + 8);
        let ranges: Vec<Range<usize>> = self
            .sentences
            .find_iter(text)
            .map(|m| m.start()..m.end())
            .collect();
        let mut cursor = 0;
        for range in ranges {
            output.push_str(&text[cursor..range.start]);
            output.push_str(&self.process_sentence(&text[range.clone()])?);
            cursor = range.end;
        }
        output.push_str(&text[cursor..]);
        Ok(output)
    }

    fn process_sentence(&mut self, sentence: &str) -> Result<String> {
        let prepared = sentence.replace(" - ", " ~ ");
        let matches: Vec<_> = self
            .words
            .find_iter(&prepared)
            .filter(|m| !m.as_str().is_empty())
            .collect();
        if matches.is_empty() {
            return Ok(sentence.to_string());
        }
        let mut words: Vec<String> = matches.iter().map(|m| m.as_str().to_string()).collect();
        let mut gaps = Vec::with_capacity(words.len() + 1);
        gaps.push(prepared[..matches[0].start()].to_string());
        for pair in matches.windows(2) {
            gaps.push(prepared[pair[0].end()..pair[1].start()].to_string());
        }
        gaps.push(prepared[matches.last().map_or(0, |m| m.end())..].to_string());

        let models = self
            .models
            .as_mut()
            .ok_or_else(|| anyhow!("full RUAccent models are not loaded"))?;
        // Python prepares `~` only for regex token rendering. Both neural token
        // classifiers receive the original sentence and therefore keep the
        // exact offsets/order produced by the reference pipeline.
        let usages = models.stress_usage.classify_words(sentence)?;
        let lowered_sentence = sentence.to_lowercase();
        let yo_predictions = if lowered_sentence.contains('е') {
            models.yo.classify_words(&lowered_sentence)?
        } else {
            Vec::new()
        };

        for (index, word) in words.iter_mut().enumerate() {
            let lowered = word.to_lowercase();
            *word = fix_capital(
                word,
                self.yo_words.get(&lowered).map_or(word, String::as_str),
            );
            if prediction_at(&yo_predictions, index) == Some("YO") {
                *word = fix_capital(
                    word,
                    self.yo_homographs
                        .get(&lowered)
                        .map_or(word, String::as_str),
                );
            }
        }

        for index in 0..words.len() {
            if let Some(variants) = self.omographs.get(&words[index].to_lowercase()) {
                // Exact Python context: copy the regex words, replace the
                // target with a space-padded marker, then join every item with
                // one space. Original punctuation gaps are deliberately absent.
                let mut context = words.clone();
                context[index] = format!(" <w>{}</w> ", words[index]);
                words[index] = models.omograph.choose(&context.join(" "), variants)?;
            }
        }

        for (index, word) in words.iter_mut().enumerate() {
            if word.contains('+') || prediction_at(&usages, index) != Some("STRESS") {
                continue;
            }
            let lowered = word.to_lowercase();
            let accented = self
                .accents
                .get(&lowered)
                .map_or(lowered.as_str(), String::as_str);
            if accented == lowered
                && !lowered.chars().any(|c| PUNCTUATION.contains(c))
                && lowered.chars().filter(|c| VOWELS.contains(*c)).count() > 1
            {
                *word = models.accent.put_accent(word)?;
            } else {
                *word = transfer_markers(word, accented);
            }
        }

        let mut rendered = String::with_capacity(prepared.len() + 8);
        for (gap, word) in gaps.iter().zip(&words) {
            rendered.push_str(gap);
            rendered.push_str(word);
        }
        if let Some(last) = gaps.last() {
            rendered.push_str(last);
        }
        Ok(delete_spaces_before_punctuation(rendered))
    }
}

impl CharAccentModel {
    fn load(path: &Path) -> Result<Self> {
        let session = load_session(path)?;
        let output = sole_output(&session)?;
        let labels = read_labels(&path.join("config.json"))?;
        let vocab_text = std::fs::read_to_string(path.join("vocab.txt"))?;
        let vocab: HashMap<String, i64> = vocab_text
            .lines()
            .enumerate()
            .map(|(index, token)| (token.to_string(), index as i64))
            .collect();
        let id = |token: &str| {
            vocab
                .get(token)
                .copied()
                .ok_or_else(|| anyhow!("{} lacks {token}", path.display()))
        };
        let _ = id("[pad]")?;
        Ok(Self {
            unknown: id("[unk]")?,
            bos: id("[bos]")?,
            eos: id("[eos]")?,
            session,
            output,
            labels,
            vocab,
        })
    }

    fn put_accent(&mut self, word: &str) -> Result<String> {
        let mut ids = Vec::with_capacity(word.chars().count() + 2);
        ids.push(self.bos);
        ids.extend(word.to_lowercase().chars().map(|c| {
            self.vocab
                .get(&c.to_string())
                .copied()
                .unwrap_or(self.unknown)
        }));
        ids.push(self.eos);
        let len = ids.len();
        let inputs = tensor_inputs(&self.session, ids, vec![1; len], vec![0; len])?;
        let outputs = self.session.run(inputs)?;
        let (shape, logits) = output_f32(&outputs, &self.output)?;
        let classes = last_dimension(&shape, logits.len())?;
        let characters: Vec<char> = word.chars().collect();
        let stressed: Vec<usize> = logits
            .chunks_exact(classes)
            .enumerate()
            .filter_map(|(position, row)| {
                let character = position.checked_sub(1)?;
                if character >= characters.len() {
                    return None;
                }
                let (label, probability) = softmax_argmax(row);
                let name = self.labels.get(label).map(String::as_str).unwrap_or("NO");
                (name != "NO" && name != "STRESS_SECONDARY" && probability >= 0.55)
                    .then_some(character)
            })
            .collect();
        let mut rendered = String::with_capacity(word.len() + stressed.len());
        for (index, character) in characters.into_iter().enumerate() {
            if stressed.contains(&index) {
                rendered.push('+');
            }
            rendered.push(character);
        }
        Ok(rendered)
    }
}

impl TokenClassifier {
    fn load(path: &Path) -> Result<Self> {
        let session = load_session(path)?;
        let tokenizer = load_tokenizer(path)?;
        let metadata = tokenizer_metadata(path, &tokenizer)?;
        Ok(Self {
            output: sole_output(&session)?,
            session,
            labels: read_labels(&path.join("config.json"))?,
            tokenizer,
            continuing_subword_prefix: metadata.continuing_subword_prefix,
            unknown_id: metadata.unknown_id,
        })
    }

    fn classify_words(&mut self, text: &str) -> Result<Vec<ClassifiedWord>> {
        let encoding = self
            .tokenizer
            .encode(text, true)
            .map_err(|e| anyhow!("tokenize: {e}"))?;
        let inputs = encoding_inputs(&self.session, &encoding)?;
        let outputs = self.session.run(inputs)?;
        let (shape, logits) = output_f32(&outputs, &self.output)?;
        let classes = last_dimension(&shape, logits.len())?;
        let mut groups: Vec<(usize, usize, Vec<Vec<f32>>)> = Vec::new();
        for (index, row) in logits.chunks_exact(classes).enumerate() {
            if encoding
                .get_special_tokens_mask()
                .get(index)
                .copied()
                .unwrap_or(1)
                != 0
            {
                continue;
            }
            let Some(&(start, end)) = encoding.get_offsets().get(index) else {
                continue;
            };
            if start == end {
                continue;
            }
            let token = encoding.get_tokens().get(index).map_or("", String::as_str);
            let reference = text.get(start..end).unwrap_or("");
            let unknown = encoding.get_ids().get(index).copied() == self.unknown_id;
            let subword = if unknown {
                false
            } else if self
                .continuing_subword_prefix
                .as_deref()
                .is_some_and(|prefix| !prefix.is_empty())
            {
                token.chars().count() != reference.chars().count()
            } else {
                start > 0
                    && text
                        .get(..start)
                        .and_then(|prefix| prefix.chars().next_back())
                        .is_some_and(|character| character != ' ')
            };
            let scores = softmax(row);
            if subword {
                if let Some(group) = groups.last_mut() {
                    group.1 = end;
                    group.2.push(scores);
                    continue;
                }
            }
            groups.push((start, end, vec![scores]));
        }
        groups
            .into_iter()
            .map(|(_, _, scores)| {
                let averaged = average_vectors(&scores)?;
                let label = argmax(&averaged);
                Ok(ClassifiedWord {
                    entity: self.labels.get(label).cloned().unwrap_or_default(),
                })
            })
            .collect()
    }
}

impl PairClassifier {
    fn load(path: &Path) -> Result<Self> {
        let session = load_session(path)?;
        let tokenizer = load_tokenizer(path)?;
        let metadata = tokenizer_metadata(path, &tokenizer)?;
        Ok(Self {
            output: sole_output(&session)?,
            session,
            tokenizer,
            pad_id: metadata.pad_id,
        })
    }

    fn choose(&mut self, sentence: &str, variants: &[String]) -> Result<String> {
        if variants.is_empty() {
            return Err(anyhow!("omograph has no variants"));
        }
        let prepared = Regex::new(r"\s+([,.?!:;…])")?.replace_all(sentence, "$1");
        let mut tokenizer = self.tokenizer.clone();
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: 512,
                strategy: TruncationStrategy::LongestFirst,
                ..Default::default()
            }))
            .map_err(|e| anyhow!("configure pair truncation: {e}"))?;
        let encodings = variants
            .iter()
            .map(|variant| {
                tokenizer
                    .encode(
                        EncodeInput::Dual(prepared.as_ref().into(), variant.as_str().into()),
                        true,
                    )
                    .map_err(|e| anyhow!("tokenize pair: {e}"))
            })
            .collect::<Result<Vec<_>>>()?;
        let max_len = encodings.iter().map(Encoding::len).max().unwrap_or(0);
        let mut best = (0usize, f32::NEG_INFINITY);
        for (index, encoding) in encodings.iter().enumerate() {
            let inputs = padded_encoding_inputs(&self.session, encoding, max_len, self.pad_id)?;
            let outputs = self.session.run(inputs)?;
            let (shape, logits) = output_f32(&outputs, &self.output)?;
            let classes = last_dimension(&shape, logits.len())?;
            let row = logits
                .get(..classes)
                .ok_or_else(|| anyhow!("empty omograph output"))?;
            let score = softmax_probability(row, 1);
            if score > best.1 {
                best = (index, score);
            }
        }
        Ok(variants[best.0].clone())
    }
}

fn load_session(path: &Path) -> Result<Session> {
    let model = path.join("model.onnx");
    Session::builder()
        .context("ort session builder")?
        .commit_from_file(&model)
        .with_context(|| format!("load {}", model.display()))
}

fn load_tokenizer(path: &Path) -> Result<Tokenizer> {
    let tokenizer = path.join("tokenizer.json");
    Tokenizer::from_file(&tokenizer)
        .map_err(|e| anyhow!("load local tokenizer {}: {e}", tokenizer.display()))
}

#[derive(Debug)]
struct TokenizerMetadata {
    pad_id: u32,
    unknown_id: Option<u32>,
    continuing_subword_prefix: Option<String>,
}

fn tokenizer_metadata(path: &Path, tokenizer: &Tokenizer) -> Result<TokenizerMetadata> {
    let config: serde_json::Value =
        serde_json::from_reader(File::open(path.join("tokenizer_config.json"))?)?;
    let pad_token = config
        .get("pad_token")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("[PAD]");
    let unknown_token = config.get("unk_token").and_then(serde_json::Value::as_str);
    let tokenizer_json: serde_json::Value =
        serde_json::from_reader(File::open(path.join("tokenizer.json"))?)?;
    let continuing_subword_prefix = tokenizer_json
        .pointer("/model/continuing_subword_prefix")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);
    Ok(TokenizerMetadata {
        pad_id: tokenizer
            .token_to_id(pad_token)
            .ok_or_else(|| anyhow!("{} lacks pad token {pad_token}", path.display()))?,
        unknown_id: unknown_token.and_then(|token| tokenizer.token_to_id(token)),
        continuing_subword_prefix,
    })
}

fn sole_output(session: &Session) -> Result<String> {
    let [output] = session.outputs() else {
        return Err(anyhow!("RUAccent graph must declare exactly one output"));
    };
    Ok(output.name().to_string())
}

fn encoding_inputs(
    session: &Session,
    encoding: &Encoding,
) -> Result<Vec<(String, SessionInputValue<'static>)>> {
    tensor_inputs(
        session,
        encoding.get_ids().iter().map(|&v| i64::from(v)).collect(),
        encoding
            .get_attention_mask()
            .iter()
            .map(|&v| i64::from(v))
            .collect(),
        encoding
            .get_type_ids()
            .iter()
            .map(|&v| i64::from(v))
            .collect(),
    )
}

fn padded_encoding_inputs(
    session: &Session,
    encoding: &Encoding,
    length: usize,
    pad_id: u32,
) -> Result<Vec<(String, SessionInputValue<'static>)>> {
    let mut ids: Vec<i64> = encoding
        .get_ids()
        .iter()
        .take(length)
        .map(|&v| i64::from(v))
        .collect();
    let mut mask: Vec<i64> = encoding
        .get_attention_mask()
        .iter()
        .take(length)
        .map(|&v| i64::from(v))
        .collect();
    let mut types: Vec<i64> = encoding
        .get_type_ids()
        .iter()
        .take(length)
        .map(|&v| i64::from(v))
        .collect();
    ids.resize(length, i64::from(pad_id));
    mask.resize(length, 0);
    types.resize(length, 0);
    tensor_inputs(session, ids, mask, types)
}

fn tensor_inputs(
    session: &Session,
    ids: Vec<i64>,
    mask: Vec<i64>,
    types: Vec<i64>,
) -> Result<Vec<(String, SessionInputValue<'static>)>> {
    let len = ids.len();
    let mut values = Vec::new();
    for input in session.inputs() {
        let data = match input.name() {
            "input_ids" => ids.clone(),
            "attention_mask" => mask.clone(),
            "token_type_ids" => types.clone(),
            other => return Err(anyhow!("unsupported RUAccent graph input {other}")),
        };
        values.push((
            input.name().to_string(),
            Tensor::from_array(([1, len], data.into_boxed_slice()))?.into(),
        ));
    }
    Ok(values)
}

fn output_f32(
    outputs: &ort::session::SessionOutputs<'_>,
    name: &str,
) -> Result<(Vec<usize>, Vec<f32>)> {
    let value = outputs
        .get(name)
        .ok_or_else(|| anyhow!("missing output {name}"))?;
    let (shape, data) = value.try_extract_tensor::<f32>()?;
    let shape = shape
        .iter()
        .map(|&dimension| {
            usize::try_from(dimension).map_err(|_| anyhow!("negative output dimension"))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok((shape, data.to_vec()))
}

fn last_dimension(shape: &[usize], data_len: usize) -> Result<usize> {
    let classes = shape
        .last()
        .copied()
        .ok_or_else(|| anyhow!("empty output shape"))?;
    if classes == 0 || data_len == 0 || data_len % classes != 0 {
        return Err(anyhow!("invalid classifier output shape"));
    }
    Ok(classes)
}

fn prediction_at(predictions: &[ClassifiedWord], index: usize) -> Option<&str> {
    predictions
        .get(index)
        .map(|prediction| prediction.entity.as_str())
}

fn softmax(values: &[f32]) -> Vec<f32> {
    let maximum = values.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let denominator: f32 = values.iter().map(|value| (*value - maximum).exp()).sum();
    values
        .iter()
        .map(|value| (*value - maximum).exp() / denominator)
        .collect()
}

fn argmax(values: &[f32]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.total_cmp(right.1))
        .map_or(0, |(index, _)| index)
}

fn average_vectors(vectors: &[Vec<f32>]) -> Result<Vec<f32>> {
    let Some(first) = vectors.first() else {
        return Err(anyhow!("cannot average empty score vectors"));
    };
    let mut average = vec![0.0; first.len()];
    for vector in vectors {
        if vector.len() != average.len() {
            return Err(anyhow!("classifier score vector width mismatch"));
        }
        for (total, value) in average.iter_mut().zip(vector) {
            *total += value;
        }
    }
    for value in &mut average {
        *value /= vectors.len() as f32;
    }
    Ok(average)
}

fn softmax_argmax(values: &[f32]) -> (usize, f32) {
    let scores = softmax(values);
    let label = argmax(&scores);
    (label, scores.get(label).copied().unwrap_or(0.0))
}

fn softmax_probability(values: &[f32], index: usize) -> f32 {
    let maximum = values.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let denominator: f32 = values.iter().map(|value| (*value - maximum).exp()).sum();
    values.get(index).map_or(f32::NEG_INFINITY, |value| {
        (*value - maximum).exp() / denominator
    })
}

fn read_labels(path: &Path) -> Result<Vec<String>> {
    let value: serde_json::Value = serde_json::from_reader(File::open(path)?)?;
    let labels = value
        .get("id2label")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| anyhow!("{} lacks id2label", path.display()))?;
    let maximum = labels
        .keys()
        .filter_map(|key| key.parse::<usize>().ok())
        .max()
        .unwrap_or(0);
    let mut output = vec![String::new(); maximum + 1];
    for (key, value) in labels {
        if let (Ok(index), Some(label)) = (key.parse::<usize>(), value.as_str()) {
            output[index] = label.to_string();
        }
    }
    Ok(output)
}

fn read_gzip_json<T: DeserializeOwned>(path: &Path) -> Result<T> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    read_gzip_json_from(file).with_context(|| format!("decode {}", path.display()))
}

fn read_gzip_json_from<T: DeserializeOwned>(reader: impl Read) -> Result<T> {
    Ok(serde_json::from_reader(GzDecoder::new(reader))?)
}

fn transfer_markers(source: &str, accented_lowercase: &str) -> String {
    let positions: Vec<usize> = accented_lowercase
        .chars()
        .scan(0usize, |letters, character| {
            if character == '+' {
                Some(Some(*letters))
            } else {
                *letters += 1;
                Some(None)
            }
        })
        .flatten()
        .collect();
    if positions.is_empty() {
        return source.to_string();
    }
    let mut output = String::with_capacity(source.len() + positions.len());
    let mut markers = positions.into_iter().peekable();
    for (index, character) in source.chars().enumerate() {
        while markers.peek() == Some(&&index) {
            output.push('+');
            markers.next();
        }
        output.push(character);
    }
    while markers.next().is_some() {
        output.push('+');
    }
    output
}

fn fix_capital(source: &str, target: &str) -> String {
    if source.chars().count() != target.chars().count() {
        return target.to_string();
    }
    source
        .chars()
        .zip(target.chars())
        .flat_map(|(source, target)| {
            if source.is_uppercase() {
                target.to_uppercase().collect::<Vec<_>>()
            } else {
                target.to_lowercase().collect::<Vec<_>>()
            }
        })
        .collect()
}

fn delete_spaces_before_punctuation(mut text: String) -> String {
    for punctuation in "!\"#$%&'()*,./:;<=>?@[\\]^_`{|}~-".chars() {
        text = text.replace(&format!(" {punctuation}"), &punctuation.to_string());
        if punctuation == '-' {
            text = text.replace(&format!("{punctuation} "), &punctuation.to_string());
        }
    }
    text.replace('~', "-")
}

fn russian_tag_spans(text: &str) -> Result<Vec<Range<usize>>> {
    let mut spans = Vec::new();
    let mut cursor = 0;
    let mut open: Option<usize> = None;
    while let Some(relative) = text[cursor..].find('<') {
        let start = cursor + relative;
        let Some(relative_end) = text[start..].find('>') else {
            return Err(anyhow!("unterminated language tag"));
        };
        let end = start + relative_end + 1;
        match &text[start..end] {
            "<ru>" => {
                if open.replace(end).is_some() {
                    return Err(anyhow!("nested Russian language spans are not supported"));
                }
            }
            "</ru>" => {
                let content_start = open
                    .take()
                    .ok_or_else(|| anyhow!("closing Russian language tag has no opener"))?;
                spans.push(content_start..start);
            }
            _ => {}
        }
        cursor = end;
    }
    if open.is_some() {
        return Err(anyhow!("Russian language tag is not closed"));
    }
    Ok(spans)
}

fn validate_spans(text: &str, spans: &[Range<usize>]) -> Result<()> {
    let mut end = 0;
    for span in spans {
        if span.start < end
            || span.start > span.end
            || span.end > text.len()
            || !text.is_char_boundary(span.start)
            || !text.is_char_boundary(span.end)
        {
            return Err(anyhow!(
                "Russian spans must be sorted, disjoint UTF-8 byte ranges"
            ));
        }
        end = span.end;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

    use super::*;
    use flate2::{write::GzEncoder, Compression};
    use std::io::Write;

    fn dictionary_runtime() -> RuAccent {
        RuAccent {
            mode: RuAccentMode::Dictionary,
            accents: HashMap::from([
                ("молоко".into(), "молок+о".into()),
                ("ёлка".into(), "+ёлка".into()),
            ]),
            omographs: HashMap::new(),
            yo_words: HashMap::from([("елка".into(), "ёлка".into())]),
            yo_homographs: HashMap::new(),
            normalize: Regex::new(r#"[^a-zA-Z0-9\sа-яА-ЯёЁ—.,!?:;'(){}\[\]«»„“”\-]"#).unwrap(),
            words: Regex::new(r"\w*(?:\+\w+)*|[^\w\s]+").unwrap(),
            dictionary_words: Regex::new(r"[A-Za-zА-Яа-яЁё]+").unwrap(),
            sentences: Regex::new(r#"[^.!?…]+[.!?…]*[\"»“]*"#).unwrap(),
            models: None,
        }
    }

    #[test]
    fn disabled_is_identity_without_assets() {
        let mut runtime =
            RuAccent::new(RuAccentConfig::new("missing", RuAccentMode::Disabled)).unwrap();
        assert_eq!(
            runtime.accent("текст 😀 +ручной").unwrap(),
            "текст 😀 +ручной"
        );
    }

    #[test]
    fn dictionary_applies_yo_accent_and_source_case() {
        let mut runtime = dictionary_runtime();
        assert_eq!(runtime.accent("Елка и МОЛОКО").unwrap(), "+Ёлка и МОЛОК+О");
        assert_eq!(runtime.accent("неизвестно").unwrap(), "неизвестно");
    }

    #[test]
    fn manual_marker_preserves_the_whole_selected_span() {
        let mut runtime = dictionary_runtime();
        let text = "<ru>молоко и р+ека</ru> <ru>молоко</ru>";
        let first = 4.."<ru>молоко и р+ека".len();
        let second_start = text.rfind("молоко").unwrap();
        let second = second_start..second_start + "молоко".len();
        assert_eq!(
            runtime.accent_ru_spans(text, &[first, second]).unwrap(),
            "<ru>молоко и р+ека</ru> <ru>молок+о</ru>"
        );
    }

    #[test]
    fn process_ru_spans_discovers_tags_and_keeps_manual_whole_span() {
        let mut runtime = dictionary_runtime();
        assert_eq!(
            runtime
                .process_ru_spans("<en>milk</en> <ru>молоко</ru> <ru>р+ека и молоко</ru>")
                .unwrap(),
            "<en>milk</en> <ru>молок+о</ru> <ru>р+ека и молоко</ru>"
        );
        assert!(runtime.process_ru_spans("<ru>молоко").is_err());
    }

    #[test]
    fn spans_reject_overlap_and_non_utf8_boundaries() {
        let mut runtime = dictionary_runtime();
        assert!(runtime.accent_ru_spans("абв", &[0..3]).is_err());
        assert!(runtime.accent_ru_spans("abcdef", &[1..4, 3..5]).is_err());
    }

    #[test]
    fn flate2_json_dictionary_decodes_in_memory() {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder
            .write_all(r#"{"слово":"сл+ово"}"#.as_bytes())
            .unwrap();
        let compressed = encoder.finish().unwrap();
        let decoded: HashMap<String, String> = read_gzip_json_from(compressed.as_slice()).unwrap();
        assert_eq!(decoded.get("слово").map(String::as_str), Some("сл+ово"));
    }

    #[test]
    fn marker_transfer_is_unicode_and_case_safe() {
        assert_eq!(transfer_markers("МОЛОКО", "молок+о"), "МОЛОК+О");
        assert_eq!(fix_capital("Елка", "ёлка"), "Ёлка");
    }

    #[test]
    fn subword_scores_are_averaged_before_argmax() {
        let averaged = average_vectors(&[
            vec![0.90, 0.10],
            vec![0.01, 0.99],
            vec![0.01, 0.99],
        ])
        .unwrap();
        assert_eq!(argmax(&averaged), 1);
        assert!((averaged[1] - 0.6933333).abs() < 1e-6);
    }

    #[test]
    fn predictions_follow_python_group_order() {
        let predictions = vec![
            ClassifiedWord { entity: "NO".into() },
            ClassifiedWord {
                entity: "STRESS".into(),
            },
        ];
        assert_eq!(prediction_at(&predictions, 0), Some("NO"));
        assert_eq!(prediction_at(&predictions, 1), Some("STRESS"));
    }
}
