use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
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
use crate::tera::{TeraEngine, MAX_AUDIO_SECONDS, SAMPLE_RATE, SEED};
use crate::wav;

const MAX_TEXT_CHARS: usize = 2_000;
const MAX_ADMITTED_REQUESTS: usize = 3;
const QUEUE_TTL: Duration = Duration::from_secs(60);
const REQUEST_DEADLINE: Duration = Duration::from_secs(120);
const BODY_LIMIT_BYTES: usize = 16 * 1024;
const APP_GIT_SHA: &str = match option_env!("TERATTS_APP_GIT_SHA") {
    Some(value) => value,
    None => "unknown",
};

struct AppState {
    engine: Arc<Mutex<TeraEngine>>,
    voices: Vec<String>,
    manifest: Manifest,
    release: PathBuf,
    admission: Arc<Admission>,
    bearer_token: Option<String>,
    ruaccent_mode: String,
    ruaccent_ready: bool,
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
    let ruaccent_ready = ruaccent_mode == "disabled" || release.join("ruaccent").is_dir();
    let state = Arc::new(AppState {
        engine: Arc::new(Mutex::new(TeraEngine::load(model_root)?)),
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
    let app_sha_verified = APP_GIT_SHA != "unknown"
        && expected_sha
            .as_deref()
            .map_or(true, |sha| sha == APP_GIT_SHA);
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
    if request.russian_stress == Some(true) && !state.ruaccent_ready {
        return Err(ApiError::bad_request(
            "russian_stress requires an RUAccent-capable backend",
        ));
    }
    let PreparedRequest {
        text,
        voice,
        language,
        scale,
        russian_stress,
    } = prepare_request(request, &state.voices)?;
    let ticket = state.admission.try_reserve()?;
    let active = ticket.activate().await?;
    let remaining = REQUEST_DEADLINE
        .checked_sub(started.elapsed())
        .ok_or_else(ApiError::deadline)?;
    let engine = Arc::clone(&state.engine);
    let task = tokio::task::spawn_blocking(move || {
        let _active = active;
        let mut engine = engine.blocking_lock();
        let mut all = Vec::new();
        let mut samples = 0usize;
        for (index, part) in chunk::chunk_text(&text).into_iter().enumerate() {
            let output = engine.synthesize(
                &part,
                &voice,
                language.as_str(),
                scale,
                SEED + index as u64,
                russian_stress,
            )?;
            for chunk in output.chunks {
                samples = checked_audio_samples(samples, chunk.len())?;
                all.try_reserve(1)
                    .map_err(|_| anyhow!("audio allocation failed"))?;
                all.push(chunk);
            }
        }
        wav::encode_mono_i16(&all)
    });
    let audio = tokio::time::timeout(remaining, task)
        .await
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

fn prepare_request(request: TtsRequest, voices: &[String]) -> Result<PreparedRequest, ApiError> {
    let text = chunk::sanitize(request.text.trim());
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
    let russian_stress = request
        .russian_stress
        .unwrap_or(matches!(language, Language::Ru));
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
        .and_then(|value| value.strip_prefix("Bearer "));
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
        response
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    fn request(text: &str) -> TtsRequest {
        TtsRequest {
            text: text.into(),
            voice: None,
            language: None,
            duration_scale: None,
            russian_stress: None,
        }
    }

    #[test]
    fn enforces_text_language_rate_and_audio_limits() {
        let voices = vec!["ru_f1".to_string(), "eng_f3".to_string()];
        let russian = prepare_request(request("hello"), &voices).unwrap();
        assert!(matches!(russian.language, Language::Ru));
        assert!(russian.russian_stress);
        let mut english_request = request("hello");
        english_request.voice = Some("eng_f3".into());
        let english = prepare_request(english_request, &voices).unwrap();
        assert!(matches!(english.language, Language::En));
        assert!(!english.russian_stress);
        assert!(prepare_request(request(&"x".repeat(MAX_TEXT_CHARS + 1)), &voices).is_err());
        let mut invalid = request("hello");
        invalid.language = Some(Language::En);
        invalid.russian_stress = Some(true);
        assert!(prepare_request(invalid, &voices).is_err());
        let mut unstressed = request("hello");
        unstressed.russian_stress = Some(false);
        assert!(!prepare_request(unstressed, &voices).unwrap().russian_stress);
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
    fn bearer_auth_is_exact_when_configured() {
        let mut headers = HeaderMap::new();
        assert!(authorize(&headers, None).is_ok());
        assert!(authorize(&headers, Some("secret")).is_err());
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_static("Bearer secret"),
        );
        assert!(authorize(&headers, Some("secret")).is_ok());
        assert!(authorize(&headers, Some("other")).is_err());
        assert!(!is_loopback_host("0.0.0.0"));
    }
}
