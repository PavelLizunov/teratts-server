use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, Result};
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{header, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use tower_http::cors::{Any, CorsLayer};

use crate::chunk;
use crate::manifest::{self, Manifest};
use crate::tera::{TeraEngine, SAMPLE_RATE, SEED};
use crate::wav;

const MAX_TEXT_CHARS: usize = 10_000;

struct AppState {
    engine: Arc<Mutex<TeraEngine>>,
    voices: Vec<String>,
    revision: String,
}

#[derive(Debug, Deserialize)]
pub struct TtsRequest {
    pub text: String,
    pub voice: Option<String>,
    pub duration_scale: Option<f32>,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    revision: String,
    sample_rate: u32,
    voices: Vec<String>,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
}

pub async fn serve(model_root: &Path, host: &str, port: u16) -> Result<()> {
    let manifest = Manifest::pinned()?;
    let release = manifest.release_dir(model_root);
    let voices = manifest::installed_voices(&release);
    if voices.is_empty() {
        return Err(anyhow!("no installed voices; run --download-models"));
    }
    let state = Arc::new(AppState {
        engine: Arc::new(Mutex::new(TeraEngine::load(model_root)?)),
        voices,
        revision: manifest.revision,
    });
    let app = Router::new()
        .route("/health", get(health))
        .route("/tts", post(tts))
        .layer(DefaultBodyLimit::max(64 * 1024))
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods([Method::GET, Method::POST])
                .allow_headers([header::CONTENT_TYPE]),
        )
        .with_state(state);
    let listener = tokio::net::TcpListener::bind((host, port)).await?;
    println!(
        "teratts-server listening on http://{host}:{}",
        listener.local_addr()?.port()
    );
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ready",
        revision: state.revision.clone(),
        sample_rate: SAMPLE_RATE,
        voices: state.voices.clone(),
    })
}

async fn tts(
    State(state): State<Arc<AppState>>,
    Json(request): Json<TtsRequest>,
) -> Result<Response, ApiError> {
    let text = chunk::sanitize(request.text.trim());
    let text_chars = text.chars().count();
    if text_chars == 0 || text_chars > MAX_TEXT_CHARS {
        return Err(ApiError::bad_request(format!(
            "text must contain 1..={MAX_TEXT_CHARS} characters"
        )));
    }
    let voice = request.voice.unwrap_or_else(|| "ru_f1".to_string());
    if !state.voices.iter().any(|installed| installed == &voice) {
        return Err(ApiError::bad_request("unknown voice"));
    }
    let scale = request.duration_scale.unwrap_or(1.0);
    if !scale.is_finite() || !(0.25..=4.0).contains(&scale) {
        return Err(ApiError::bad_request(
            "duration_scale must be between 0.25 and 4.0",
        ));
    }
    let engine = Arc::clone(&state.engine);
    let audio = tokio::task::spawn_blocking(move || {
        let mut engine = engine.blocking_lock();
        let mut all = Vec::new();
        for (index, part) in chunk::chunk_text(&text).into_iter().enumerate() {
            let output = engine.synthesize(&part, &voice, "ru", scale, SEED + index as u64)?;
            all.extend(output.chunks);
        }
        wav::encode_mono_i16(&all)
    })
    .await
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

struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(ErrorResponse {
                error: self.message,
            }),
        )
            .into_response()
    }
}
