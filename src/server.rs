use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{anyhow, Result};
use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tokio::sync::{Mutex, OwnedSemaphorePermit, Semaphore};

use crate::chunk;
use crate::manifest::{self, Manifest};
use crate::speechfront;
use crate::tera::{TeraEngine, MAX_AUDIO_SECONDS, SAMPLE_RATE, SEED};
use crate::wav;

pub(crate) const MAX_TEXT_CHARS: usize = 2_400;
const MAX_ADMITTED_REQUESTS: usize = 3;
const QUEUE_TTL: Duration = Duration::from_secs(60);
const REQUEST_DEADLINE: Duration = Duration::from_secs(120);
const BODY_LIMIT_BYTES: usize = 16 * 1024;
const APP_GIT_SHA: &str = match option_env!("TERATTS_APP_GIT_SHA") {
    Some(value) => value,
    None => "unknown",
};

struct AppState {
    /// Phase B (perf spec): one engine per parallel chunk slot. Per-chunk seeds
    /// are deterministic (`SEED + index`), so parallel synthesis is byte-identical
    /// to sequential; no crossfade is required because chunks already concatenate
    /// cleanly.
    pool: Arc<Vec<Mutex<TeraEngine>>>,
    voices: Vec<String>,
    manifest: Manifest,
    release: PathBuf,
    admission: Arc<Admission>,
    bearer_token: Option<String>,
    ruaccent_mode: String,
    ruaccent_ready: bool,
}

fn ort_threads() -> usize {
    std::env::var("TERATTS_ORT_THREADS")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value: &usize| *value > 0)
        .unwrap_or(4)
}

fn determine_parallel_slots(
    requested: usize,
    ort_threads: usize,
    available_parallelism: usize,
) -> usize {
    let requested = requested.clamp(1, 4);
    let ort_threads = ort_threads.max(1);
    let max_safe = (available_parallelism / ort_threads).max(1);
    requested.min(max_safe)
}

/// Parallel chunk slots (Phase B). 1 = sequential (legacy); >1 = bounded
/// parallel synthesis. Capped at 4 and safely clamped against the thread product
/// (`slots * ORT_THREADS <= available_parallelism`) to prevent thread oversubscription.
fn parallel_chunks() -> usize {
    let requested = std::env::var("TERATTS_PARALLEL_CHUNKS")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value: &usize| *value > 0)
        .unwrap_or(1);
    let threads = ort_threads();
    let cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    determine_parallel_slots(requested, threads, cores)
}

struct Admission {
    admitted: AtomicUsize,
    active: Arc<Semaphore>,
}

struct AdmissionTicket {
    admission: Arc<Admission>,
}

impl Admission {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            admitted: AtomicUsize::new(0),
            active: Arc::new(Semaphore::new(1)),
        })
    }

    fn try_reserve(self: &Arc<Self>) -> Result<AdmissionTicket, ApiError> {
        self.admitted
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < MAX_ADMITTED_REQUESTS).then_some(current + 1)
            })
            .map_err(|_| ApiError::busy())?;
        Ok(AdmissionTicket {
            admission: Arc::clone(self),
        })
    }

    fn view(&self) -> QueueView {
        let admitted = self.admitted.load(Ordering::Acquire);
        let active = usize::from(self.active.available_permits() == 0);
        QueueView {
            active,
            waiting: admitted.saturating_sub(active),
            capacity: MAX_ADMITTED_REQUESTS - 1,
        }
    }
}

impl AdmissionTicket {
    async fn activate(self) -> Result<ActiveRequest, ApiError> {
        let permit = tokio::time::timeout(
            QUEUE_TTL,
            Arc::clone(&self.admission.active).acquire_owned(),
        )
        .await
        .map_err(|_| ApiError::queue_timeout())?
        .map_err(|_| ApiError::internal("admission queue closed"))?;
        Ok(ActiveRequest {
            _ticket: self,
            _permit: permit,
        })
    }
}

impl Drop for AdmissionTicket {
    fn drop(&mut self) {
        self.admission.admitted.fetch_sub(1, Ordering::AcqRel);
    }
}

struct ActiveRequest {
    _ticket: AdmissionTicket,
    _permit: OwnedSemaphorePermit,
}

/// Async-request-owned cancellation edge. Dropping the Axum request future
/// (client disconnect) or returning after timeout sets the cooperative flag.
/// The current native ORT `Session::run` remains non-interruptible; workers stop
/// before the next chunk. `ActiveRequest` stays in the async handler so its
/// admission permit is released immediately when that handler is dropped.
struct CancelOnDrop(Arc<AtomicBool>);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    Ru,
    En,
}

impl Language {
    fn as_str(self) -> &'static str {
        match self {
            Self::Ru => "ru",
            Self::En => "en",
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct TtsRequest {
    pub text: String,
    pub voice: Option<String>,
    pub language: Option<Language>,
    pub duration_scale: Option<f32>,
    pub russian_stress: Option<bool>,
    #[serde(default)]
    pub speech_front: Option<bool>,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    app_git_sha: &'static str,
    app_sha_verified: bool,
    model_revision: String,
    verification: &'static str,
    ruaccent_mode: String,
    ruaccent_ready: bool,
    sample_rate: u32,
    voices: Vec<String>,
    queue: QueueView,
}

#[derive(Debug, Serialize)]
struct QueueView {
    active: usize,
    waiting: usize,
    capacity: usize,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    code: &'static str,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    retry_after_ms: Option<u64>,
}

pub async fn serve(model_root: &Path, host: &str, port: u16) -> Result<()> {
    let manifest = Manifest::pinned()?;
    let release = manifest.release_dir(model_root);
    manifest::verify_release(&manifest, &release)
        .map_err(|error| anyhow!("models failed verification: {error}"))?;
    let voices = manifest::installed_voices(&release);
    if voices.is_empty() {
        return Err(anyhow!("no installed voices; run --download-models"));
    }
    let bearer_token = std::env::var("TERATTS_BEARER_TOKEN")
        .ok()
        .filter(|value| !value.is_empty());
    if bearer_token.is_none() {
        return Err(anyhow!("TERATTS_BEARER_TOKEN is required"));
    }
    if !is_loopback_host(host) {
        return Err(anyhow!("server must bind to loopback only"));
    }
    let ruaccent_mode = std::env::var("TERATTS_RUACCENT_MODE").unwrap_or_else(|_| "full".into());
    if !matches!(ruaccent_mode.as_str(), "full" | "dictionary" | "disabled") {
        return Err(anyhow!(
            "TERATTS_RUACCENT_MODE must be full, dictionary, or disabled"
        ));
    }
    let ruaccent_ready = ruaccent_mode != "disabled" && release.join("ruaccent").is_dir();
    let slots = parallel_chunks();
    let mut pool = Vec::with_capacity(slots);
    for _ in 0..slots {
        pool.push(Mutex::new(TeraEngine::load(model_root)?));
    }
    println!("[teratts-server] parallel chunk slots: {slots}");
    let state = Arc::new(AppState {
        pool: Arc::new(pool),
        voices,
        manifest,
        release,
        admission: Admission::new(),
        bearer_token,
        ruaccent_mode,
        ruaccent_ready,
    });
    let app = Router::new()
        .route("/health", get(health))
        .route("/tts", post(tts))
        .layer(DefaultBodyLimit::max(BODY_LIMIT_BYTES))
        .with_state(state);
    let listener = tokio::net::TcpListener::bind((host, port)).await?;
    println!(
        "teratts-server listening on http://{host}:{}",
        listener.local_addr()?.port()
    );
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health(State(state): State<Arc<AppState>>) -> Response {
    // Full hashes are verified before startup; keep the live probe bounded to markers and sizes.
    let models_ready = manifest::check_installed(&state.manifest, &state.release).is_ok();
    let expected_sha = std::env::var("TERATTS_EXPECTED_APP_GIT_SHA").ok();
    let app_sha_verified =
        APP_GIT_SHA != "unknown" && expected_sha.as_deref().is_none_or(|sha| sha == APP_GIT_SHA);
    let ruaccent_ok = state.ruaccent_mode == "disabled" || state.ruaccent_ready;
    let ready = models_ready && app_sha_verified && ruaccent_ok;
    (
        if ready {
            StatusCode::OK
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        },
        Json(HealthResponse {
            status: if ready { "ready" } else { "not_ready" },
            app_git_sha: APP_GIT_SHA,
            app_sha_verified,
            model_revision: state.manifest.revision.clone(),
            verification: if models_ready { "verified" } else { "failed" },
            ruaccent_mode: state.ruaccent_mode.clone(),
            ruaccent_ready: state.ruaccent_ready,
            sample_rate: SAMPLE_RATE,
            voices: state.voices.clone(),
            queue: state.admission.view(),
        }),
    )
        .into_response()
}

async fn tts(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    request: Result<Json<TtsRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    authorize(&headers, state.bearer_token.as_deref())?;
    let started = Instant::now();
    let Json(request) = request.map_err(ApiError::from_json_rejection)?;
    let PreparedRequest {
        text,
        voice,
        language,
        scale,
        russian_stress,
    } = prepare_request(request, &state.voices, state.ruaccent_ready)?;
    let ticket = state.admission.try_reserve()?;
    let active = ticket.activate().await?;
    // Keep admission ownership in the async request future, not in the
    // non-cancellable blocking inference task.
    let _active = active;
    let remaining = REQUEST_DEADLINE
        .checked_sub(started.elapsed())
        .ok_or_else(ApiError::deadline)?;
    let pool = Arc::clone(&state.pool);
    let cancel = Arc::new(AtomicBool::new(false));
    let _cancel_on_drop = CancelOnDrop(Arc::clone(&cancel));
    let cancel_for_task = Arc::clone(&cancel);
    let task = tokio::task::spawn_blocking(move || {
        if cancel_for_task.load(Ordering::Acquire) {
            return Err(anyhow!("synthesis cancelled"));
        }
        let prepared =
            pool[0]
                .blocking_lock()
                .preprocess(&text, language.as_str(), russian_stress)?;
        let parts = TeraEngine::chunk_preprocessed(&prepared, chunk::MAX_CHUNK_CHARS)?;
        if parts.is_empty() {
            return wav::encode_mono_i16(&[]);
        }

        // Per-chunk synthesis; seeds are `SEED + index` so output is identical
        // regardless of execution order. Sequential when the pool has one slot
        // or there is only one chunk.
        let synthesize_into = |all: &mut Vec<Vec<f32>>,
                               samples: &mut usize,
                               index: usize,
                               part: &str,
                               engine: &mut TeraEngine|
         -> Result<()> {
            let output =
                engine.synthesize_preprocessed(part, &voice, scale, SEED + index as u64)?;
            for chunk in output.chunks {
                *samples = checked_audio_samples(*samples, chunk.len())?;
                all.try_reserve(1)
                    .map_err(|_| anyhow!("audio allocation failed"))?;
                all.push(chunk);
            }
            Ok(())
        };

        let mut all = Vec::new();
        let mut samples = 0usize;
        if pool.len() == 1 || parts.len() == 1 {
            let mut engine = pool[0].blocking_lock();
            for (index, part) in parts.iter().enumerate() {
                if cancel_for_task.load(Ordering::Acquire) {
                    return Err(anyhow!("synthesis cancelled"));
                }
                synthesize_into(&mut all, &mut samples, index, part, &mut engine)?;
            }
        } else {
            // Bounded parallelism: spawn at most `pool.len()` worker threads.
            // Workers dynamically pull chunks from `next_chunk` and synthesize
            // on their dedicated engine slot `pool[worker_idx]`.
            let worker_count = pool.len().min(parts.len());
            let parts = Arc::new(parts);
            let next_chunk = Arc::new(AtomicUsize::new(0));
            let mut handles = Vec::with_capacity(worker_count);

            for worker_idx in 0..worker_count {
                let pool = Arc::clone(&pool);
                let cancel = Arc::clone(&cancel_for_task);
                let parts = Arc::clone(&parts);
                let next_chunk = Arc::clone(&next_chunk);
                let voice = voice.clone();
                handles.push(std::thread::spawn(move || {
                    let guarded = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        let mut engine = pool[worker_idx].blocking_lock();
                        let mut outputs = Vec::new();
                        loop {
                            if cancel.load(Ordering::Acquire) {
                                return Err(anyhow!("synthesis cancelled"));
                            }
                            let idx = next_chunk.fetch_add(1, Ordering::Relaxed);
                            if idx >= parts.len() {
                                break;
                            }
                            if cancel.load(Ordering::Acquire) {
                                return Err(anyhow!("synthesis cancelled"));
                            }
                            let res = engine.synthesize_preprocessed(
                                &parts[idx],
                                &voice,
                                scale,
                                SEED + idx as u64,
                            );
                            match res {
                                Ok(output) => outputs.push((idx, output)),
                                Err(err) => {
                                    cancel.store(true, Ordering::Release);
                                    return Err(err);
                                }
                            }
                        }
                        Ok(outputs)
                    }));
                    match guarded {
                        Ok(result) => result,
                        Err(payload) => {
                            cancel.store(true, Ordering::Release);
                            std::panic::resume_unwind(payload)
                        }
                    }
                }));
            }

            // Always join all created workers so no JoinHandles are detached or leaked.
            let mut worker_results = Vec::with_capacity(handles.len());
            let mut panic_err = None;
            for handle in handles {
                match handle.join() {
                    Ok(res) => worker_results.push(res),
                    Err(_) => {
                        cancel_for_task.store(true, Ordering::Release);
                        if panic_err.is_none() {
                            panic_err = Some(anyhow!("synthesis worker thread panicked"));
                        }
                    }
                }
            }

            if let Some(err) = panic_err {
                return Err(err);
            }

            let mut collected: Vec<Option<_>> = (0..parts.len()).map(|_| None).collect();
            let mut root_error = None;
            let mut cancellation_error = None;
            for res in worker_results {
                match res {
                    Ok(outputs) => {
                        for (idx, output) in outputs {
                            collected[idx] = Some(output);
                        }
                    }
                    Err(error) if error.to_string() == "synthesis cancelled" => {
                        if cancellation_error.is_none() {
                            cancellation_error = Some(error);
                        }
                    }
                    Err(error) => {
                        if root_error.is_none() {
                            root_error = Some(error);
                        }
                    }
                }
            }
            if let Some(error) = root_error.or(cancellation_error) {
                return Err(error);
            }

            for (idx, opt) in collected.into_iter().enumerate() {
                let output = opt.ok_or_else(|| anyhow!("missing chunk {idx} output"))?;
                for chunk in output.chunks {
                    samples = checked_audio_samples(samples, chunk.len())?;
                    all.try_reserve(1)
                        .map_err(|_| anyhow!("audio allocation failed"))?;
                    all.push(chunk);
                }
            }
        }
        wav::encode_mono_i16(&all)
    });
    let task_result = tokio::time::timeout(remaining, task).await;
    if task_result.is_err() {
        cancel.store(true, Ordering::Release);
    }
    let audio = task_result
        .map_err(|_| ApiError::deadline())?
        .map_err(|_| ApiError::internal("synthesis task failed"))?
        .map_err(|error| {
            eprintln!("[teratts-server] synthesis failed: {error:#}");
            ApiError::internal("synthesis failed")
        })?;

    Ok((
        [
            (header::CONTENT_TYPE, HeaderValue::from_static("audio/wav")),
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
        ],
        audio,
    )
        .into_response())
}

struct PreparedRequest {
    text: String,
    voice: String,
    language: Language,
    scale: f32,
    russian_stress: bool,
}

/// Phase D (speech-front): opt-in Russian text front-end (lexicon + versions /
/// numbers / dates / percents / units) so technical tokens speak naturally.
fn speech_front_enabled() -> bool {
    std::env::var("TERATTS_SPEECH_FRONT")
        .map(|value| value == "1")
        .unwrap_or(false)
}

fn speech_front() -> Option<&'static speechfront::Normalizer> {
    use std::sync::OnceLock;
    static NORM: OnceLock<Option<speechfront::Normalizer>> = OnceLock::new();
    NORM.get_or_init(|| match speechfront::Normalizer::builtin() {
        Ok(normalizer) => Some(normalizer),
        Err(error) => {
            eprintln!("[teratts-server] speech-front lexicon failed: {error}");
            None
        }
    })
    .as_ref()
}

/// Apply Russian normalization to untagged/Russian spans while preserving
/// explicit English spans byte-for-byte. Malformed tags are left for the
/// downstream language-tag validator to reject.
fn normalize_russian_spans(text: &str, normalizer: &speechfront::Normalizer) -> String {
    if !text.contains("<ru>") && !text.contains("<en>") {
        return normalizer.normalize(text);
    }
    let mut output = String::with_capacity(text.len());
    let normalize_gap = |gap: &str| {
        if gap.chars().all(char::is_whitespace) {
            gap.to_string()
        } else {
            normalizer.normalize(gap)
        }
    };
    let mut cursor = 0;
    while let Some(relative) = text[cursor..].find('<') {
        let start = cursor + relative;
        output.push_str(&normalize_gap(&text[cursor..start]));
        if text[start..].starts_with("<ru>") {
            let content_start = start + 4;
            let Some(relative_end) = text[content_start..].find("</ru>") else {
                output.push_str(&text[start..]);
                return output;
            };
            let content_end = content_start + relative_end;
            output.push_str("<ru>");
            output.push_str(&normalizer.normalize(&text[content_start..content_end]));
            output.push_str("</ru>");
            cursor = content_end + 5;
        } else if text[start..].starts_with("<en>") {
            let content_start = start + 4;
            let Some(relative_end) = text[content_start..].find("</en>") else {
                output.push_str(&text[start..]);
                return output;
            };
            let content_end = content_start + relative_end;
            output.push_str(&text[start..content_end + 5]);
            cursor = content_end + 5;
        } else {
            output.push('<');
            cursor = start + 1;
        }
    }
    output.push_str(&normalize_gap(&text[cursor..]));
    output
}

fn prepare_request(
    request: TtsRequest,
    voices: &[String],
    ruaccent_capable: bool,
) -> Result<PreparedRequest, ApiError> {
    let mut text = chunk::sanitize(request.text.trim());
    let text_chars = text.chars().count();
    if text_chars == 0 || text_chars > MAX_TEXT_CHARS {
        return Err(ApiError::bad_request(format!(
            "text must contain 1..={MAX_TEXT_CHARS} characters"
        )));
    }
    let voice = request.voice.unwrap_or_else(|| "ru_f1".to_string());
    if !voices.iter().any(|installed| installed == &voice) {
        return Err(ApiError::bad_request("unknown voice"));
    }
    let scale = request.duration_scale.unwrap_or(1.0);
    if !scale.is_finite() || !(0.25..=4.0).contains(&scale) {
        return Err(ApiError::bad_request(
            "duration_scale must be between 0.25 and 4.0",
        ));
    }
    let language = request.language.unwrap_or_else(|| {
        if voice.starts_with("eng_") {
            Language::En
        } else {
            Language::Ru
        }
    });
    if request.russian_stress.is_some() && !matches!(language, Language::Ru) {
        return Err(ApiError::bad_request(
            "russian_stress is only valid for language ru",
        ));
    }
    let russian_stress = match request.russian_stress {
        Some(true) if !ruaccent_capable => {
            return Err(ApiError::bad_request(
                "russian_stress requires an RUAccent-capable backend",
            ));
        }
        Some(value) => value,
        None => matches!(language, Language::Ru) && ruaccent_capable,
    };
    let want_speech_front = request.speech_front.unwrap_or(false) || speech_front_enabled();
    if matches!(language, Language::Ru) && want_speech_front {
        if let Some(normalizer) = speech_front() {
            text = normalize_russian_spans(&text, normalizer);
        }
    }
    Ok(PreparedRequest {
        text,
        voice,
        language,
        scale,
        russian_stress,
    })
}

fn checked_audio_samples(current: usize, additional: usize) -> Result<usize> {
    let maximum = (SAMPLE_RATE as usize)
        .checked_mul(MAX_AUDIO_SECONDS as usize)
        .ok_or_else(|| anyhow!("audio allocation limit overflow"))?;
    let total = current
        .checked_add(additional)
        .ok_or_else(|| anyhow!("audio allocation overflow"))?;
    if total > maximum {
        return Err(anyhow!(
            "predicted audio exceeds {MAX_AUDIO_SECONDS} seconds"
        ));
    }
    Ok(total)
}

fn authorize(headers: &HeaderMap, expected: Option<&str>) -> Result<(), ApiError> {
    let Some(expected) = expected else {
        return Ok(());
    };
    let supplied = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| {
            let mut parts = value.split_ascii_whitespace();
            let scheme = parts.next()?;
            let token = parts.next()?;
            (parts.next().is_none() && scheme.eq_ignore_ascii_case("bearer")).then_some(token)
        });
    if supplied.is_some_and(|value| constant_time_eq(value.as_bytes(), expected.as_bytes())) {
        Ok(())
    } else {
        Err(ApiError::unauthorized())
    }
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn is_loopback_host(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "::1" | "localhost")
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    code: &'static str,
    message: String,
    retry_after_ms: Option<u64>,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            code: "invalid_request",
            message: message.into(),
            retry_after_ms: None,
        }
    }

    fn busy() -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            code: "busy",
            message: "synthesis queue is full".into(),
            retry_after_ms: Some(1_000),
        }
    }

    fn queue_timeout() -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: "queue_timeout",
            message: "synthesis did not start within 60 seconds".into(),
            retry_after_ms: Some(1_000),
        }
    }

    fn deadline() -> Self {
        Self {
            status: StatusCode::GATEWAY_TIMEOUT,
            code: "deadline_exceeded",
            message: "request exceeded 120 second deadline".into(),
            retry_after_ms: None,
        }
    }

    fn unauthorized() -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            code: "unauthorized",
            message: "valid bearer token required".into(),
            retry_after_ms: None,
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            code: "internal",
            message: message.into(),
            retry_after_ms: None,
        }
    }

    fn from_json_rejection(rejection: JsonRejection) -> Self {
        let status = rejection.status();
        let (code, message) = if status == StatusCode::PAYLOAD_TOO_LARGE {
            (
                "body_too_large",
                "request body exceeds the configured limit",
            )
        } else if status == StatusCode::UNSUPPORTED_MEDIA_TYPE {
            (
                "unsupported_media_type",
                "content-type must be application/json",
            )
        } else {
            ("invalid_json", "request body is not valid TTS JSON")
        };
        Self {
            status,
            code,
            message: message.into(),
            retry_after_ms: None,
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let mut response = (
            self.status,
            Json(ErrorResponse {
                code: self.code,
                message: self.message,
                retry_after_ms: self.retry_after_ms,
            }),
        )
            .into_response();
        if self.status == StatusCode::UNAUTHORIZED {
            response
                .headers_mut()
                .insert(header::WWW_AUTHENTICATE, HeaderValue::from_static("Bearer"));
        }
        if let Some(retry_after_ms) = self.retry_after_ms {
            let seconds = retry_after_ms.div_ceil(1_000).max(1).to_string();
            if let Ok(value) = HeaderValue::from_str(&seconds) {
                response.headers_mut().insert(header::RETRY_AFTER, value);
            }
        }
        response
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

    use super::*;

    fn request(text: &str) -> TtsRequest {
        TtsRequest {
            text: text.into(),
            voice: None,
            language: None,
            duration_scale: None,
            russian_stress: None,
            speech_front: None,
        }
    }

    #[test]
    fn enforces_text_language_rate_and_audio_limits() {
        let voices = vec!["ru_f1".to_string(), "eng_f3".to_string()];
        let russian = prepare_request(request("hello"), &voices, true).unwrap();
        assert!(matches!(russian.language, Language::Ru));
        assert!(russian.russian_stress);
        let mut english_request = request("hello");
        english_request.voice = Some("eng_f3".into());
        let english = prepare_request(english_request, &voices, true).unwrap();
        assert!(matches!(english.language, Language::En));
        assert!(!english.russian_stress);
        assert!(prepare_request(request(&"x".repeat(MAX_TEXT_CHARS)), &voices, true).is_ok());
        assert!(prepare_request(request(&"x".repeat(MAX_TEXT_CHARS + 1)), &voices, true).is_err());
        let mut invalid = request("hello");
        invalid.language = Some(Language::En);
        invalid.russian_stress = Some(true);
        assert!(prepare_request(invalid, &voices, true).is_err());
        let mut unstressed = request("hello");
        unstressed.russian_stress = Some(false);
        assert!(
            !prepare_request(unstressed, &voices, true)
                .unwrap()
                .russian_stress
        );
        let disabled_default = prepare_request(request("привет"), &voices, false).unwrap();
        assert!(!disabled_default.russian_stress);
        let mut disabled_explicit = request("привет");
        disabled_explicit.russian_stress = Some(true);
        assert!(prepare_request(disabled_explicit, &voices, false).is_err());
        let mut disabled_false = request("привет");
        disabled_false.russian_stress = Some(false);
        assert!(
            !prepare_request(disabled_false, &voices, false)
                .unwrap()
                .russian_stress
        );
        let maximum = SAMPLE_RATE as usize * MAX_AUDIO_SECONDS as usize;
        assert!(checked_audio_samples(0, maximum).is_ok());
        assert!(checked_audio_samples(0, maximum + 1).is_err());
    }

    #[test]
    fn admits_only_one_active_and_two_waiting() {
        let admission = Admission::new();
        let first = admission.try_reserve();
        let second = admission.try_reserve();
        let third = admission.try_reserve();
        assert!(first.is_ok() && second.is_ok() && third.is_ok());
        assert_eq!(admission.view().waiting, 3);
        assert!(admission.try_reserve().is_err());
        drop((first, second, third));
        assert_eq!(admission.view().waiting, 0);
    }

    #[test]
    fn busy_error_exposes_retry_after_header() {
        let response = ApiError::busy().into_response();
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(response.headers().get(header::RETRY_AFTER).unwrap(), "1");
    }

    #[test]
    fn bearer_auth_is_exact_when_configured() {
        let mut headers = HeaderMap::new();
        assert!(authorize(&headers, None).is_ok());
        assert!(authorize(&headers, Some("secret")).is_err());
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_static("Bearer secret"),
        );
        assert!(authorize(&headers, Some("secret")).is_ok());
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_static("bearer secret"),
        );
        assert!(authorize(&headers, Some("secret")).is_ok());
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_static("BEARER secret"),
        );
        assert!(authorize(&headers, Some("secret")).is_ok());
        assert!(authorize(&headers, Some("other")).is_err());
        assert!(!is_loopback_host("0.0.0.0"));
    }

    #[test]
    fn thread_product_guard_clamps_slots_safely() {
        // CT221: cores=4, threads=2 -> max slots 2
        assert_eq!(determine_parallel_slots(4, 2, 4), 2);
        assert_eq!(determine_parallel_slots(2, 2, 4), 2);
        assert_eq!(determine_parallel_slots(1, 2, 4), 1);

        // cores=4, threads=4 -> max slots 1
        assert_eq!(determine_parallel_slots(4, 4, 4), 1);
        assert_eq!(determine_parallel_slots(2, 4, 4), 1);
        assert_eq!(determine_parallel_slots(1, 4, 4), 1);

        // cores=8, threads=2 -> max slots 4
        assert_eq!(determine_parallel_slots(4, 2, 8), 4);
        assert_eq!(determine_parallel_slots(3, 2, 8), 3);

        // cores=1, threads=4 -> minimum 1 slot
        assert_eq!(determine_parallel_slots(2, 4, 1), 1);

        // clamping bounds
        assert_eq!(determine_parallel_slots(0, 0, 0), 1);
        assert_eq!(determine_parallel_slots(10, 1, 16), 4);
    }

    #[test]
    fn speech_front_preserves_english_spans_and_whitespace() {
        let normalizer = speechfront::Normalizer::builtin().unwrap();
        assert_eq!(
            normalize_russian_spans(
                "<ru>Релиз 15%</ru> <en>section 2026-08-12</en>",
                &normalizer,
            ),
            "<ru>Релиз пятнадцать процентов</ru> <en>section 2026-08-12</en>"
        );
    }

    #[test]
    fn worker_execution_respects_cancellation_and_joins_all() {
        // Simulated worker dispatch matching the server's chunk worker loop
        let cancel = Arc::new(AtomicBool::new(false));
        let num_chunks = 10;
        let worker_count = 3;
        let next_chunk = Arc::new(AtomicUsize::new(0));
        let processed_count = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::with_capacity(worker_count);
        for _ in 0..worker_count {
            let cancel = Arc::clone(&cancel);
            let next_chunk = Arc::clone(&next_chunk);
            let processed_count = Arc::clone(&processed_count);
            handles.push(std::thread::spawn(move || {
                let mut outputs = Vec::new();
                loop {
                    if cancel.load(Ordering::Acquire) {
                        return Err(anyhow!("synthesis cancelled"));
                    }
                    let idx = next_chunk.fetch_add(1, Ordering::Relaxed);
                    if idx >= num_chunks {
                        break;
                    }
                    if cancel.load(Ordering::Acquire) {
                        return Err(anyhow!("synthesis cancelled"));
                    }
                    // Cancel after processing 2 chunks across workers
                    let count = processed_count.fetch_add(1, Ordering::SeqCst);
                    if count >= 2 {
                        cancel.store(true, Ordering::Release);
                    }
                    outputs.push(idx);
                }
                Ok(outputs)
            }));
        }

        // All handles must always join
        let mut worker_results = Vec::new();
        for handle in handles {
            let res = match handle.join() {
                Ok(res) => res,
                Err(_) => panic!("worker thread panicked unexpectedly"),
            };
            worker_results.push(res);
        }

        assert!(cancel.load(Ordering::Acquire));
        // Total processed should be small (stopped early by cancellation)
        let total_processed = processed_count.load(Ordering::SeqCst);
        assert!(total_processed < num_chunks);
        // At least one worker observed cancellation error or cleanly stopped
        assert!(worker_results.iter().any(|r| r.is_err()) || total_processed <= worker_count + 2);
    }
}
