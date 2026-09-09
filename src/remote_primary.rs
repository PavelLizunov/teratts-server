//! Optional single-attempt loopback primary; no text processing or detached work.
use std::net::{IpAddr, SocketAddr};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use anyhow::{anyhow, Result};
use reqwest::header::{self, HeaderValue};
use reqwest::{Client, StatusCode, Url};
use serde::{Deserialize, Serialize};

use crate::tera::{MAX_AUDIO_SECONDS, SAMPLE_RATE};

const MAX_WAV_BYTES: usize = 44 + MAX_AUDIO_SECONDS as usize * SAMPLE_RATE as usize * 2;
const MAX_ERROR_BYTES: usize = 4096;
pub(crate) const TOTAL_DEADLINE: Duration = Duration::from_secs(55);

pub(crate) struct RemotePrimary {
    client: Client,
    url: Url,
    authorization: HeaderValue,
    timeout: Duration,
}

#[derive(Serialize)]
pub(crate) struct ForwardRequest<'a> {
    pub text: &'a str,
    pub voice: &'a str,
    pub language: &'static str,
    pub duration_scale: f32,
    pub speech_front: bool,
    pub text_mode: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub russian_stress: Option<bool>,
}

#[derive(Debug, PartialEq)]
pub(crate) enum Failure {
    Fallback,
    Cancelled,
    Reject(StatusCode, &'static str, Option<u64>),
}

impl RemotePrimary {
    pub(crate) fn from_env(listen_port: u16) -> Result<Option<Self>> {
        let read = |name| match std::env::var(name) {
            Ok(value) => Ok(Some(value)),
            Err(std::env::VarError::NotPresent) => Ok(None),
            Err(_) => Err(anyhow!("primary configuration must be Unicode")),
        };
        Self::parse(
            read("TERATTS_PRIMARY_URL")?.as_deref(),
            read("TERATTS_PRIMARY_TOKEN")?.as_deref(),
            read("TERATTS_PRIMARY_TIMEOUT_MS")?.as_deref(),
            listen_port,
        )
    }

    pub(crate) fn parse(
        url: Option<&str>,
        token: Option<&str>,
        timeout: Option<&str>,
        listen_port: u16,
    ) -> Result<Option<Self>> {
        let (url, token) = match (url, token) {
            (None, None) if timeout.is_none() => return Ok(None),
            (Some(url), Some(token)) if !url.is_empty() && !token.is_empty() => (url, token),
            _ => {
                return Err(anyhow!(
                    "TERATTS_PRIMARY_URL and TERATTS_PRIMARY_TOKEN must be configured together"
                ))
            }
        };
        // Validate the literal authority BEFORE URL parsing can normalize shorthand,
        // numeric IPv4, dot segments, whitespace, or escaped spellings.
        let authority = url
            .strip_prefix("http://")
            .and_then(|v| v.strip_suffix("/tts"))
            .ok_or_else(|| {
                anyhow!("primary URL must be literal loopback HTTP with fixed /tts path")
            })?;
        let ip = authority
            .parse::<SocketAddr>()
            .map(|v| v.ip())
            .ok()
            .or_else(|| authority.parse::<IpAddr>().ok())
            .or_else(|| {
                authority
                    .strip_prefix('[')
                    .and_then(|v| v.strip_suffix(']'))
                    .and_then(|v| v.parse::<IpAddr>().ok())
            });
        if !ip.is_some_and(|v| v.is_loopback()) {
            return Err(anyhow!("primary URL must use a literal loopback address"));
        }
        let url = Url::parse(url).map_err(|_| anyhow!("invalid primary URL"))?;
        let port = url.port_or_known_default().unwrap_or(0);
        if port == 0 || listen_port == 0 || port == listen_port {
            return Err(anyhow!(
                "primary port must differ from a fixed nonzero listening port"
            ));
        }
        let timeout_ms = timeout
            .unwrap_or("3000")
            .parse::<u64>()
            .ok()
            .filter(|v| (1..=10_000).contains(v))
            .ok_or_else(|| anyhow!("TERATTS_PRIMARY_TIMEOUT_MS must be 1..=10000"))?;
        if token.bytes().any(|v| !v.is_ascii_graphic()) {
            return Err(anyhow!("invalid primary bearer token"));
        }
        let mut authorization = HeaderValue::from_str(&format!("Bearer {token}"))
            .map_err(|_| anyhow!("invalid primary bearer token"))?;
        authorization.set_sensitive(true);
        let timeout = Duration::from_millis(timeout_ms);
        let client = Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .no_proxy()
            .timeout(timeout)
            .build()
            .map_err(|_| anyhow!("primary HTTP client initialization failed"))?;
        Ok(Some(Self {
            client,
            url,
            authorization,
            timeout,
        }))
    }

    pub(crate) fn has_attempt_budget(&self, remaining: Duration) -> bool {
        remaining >= self.timeout + Duration::from_secs(5)
    }

    pub(crate) async fn attempt(
        &self,
        request: &ForwardRequest<'_>,
        cancel: &AtomicBool,
    ) -> Result<Vec<u8>, Failure> {
        if cancel.load(Ordering::Acquire) {
            return Err(Failure::Cancelled);
        }
        let mut received_status = None;
        let attempt = async {
            let body = serde_json::to_vec(request).map_err(|_| invalid_response())?;
            let mut response = self
                .client
                .post(self.url.clone())
                .header(header::AUTHORIZATION, self.authorization.clone())
                .header(header::CONTENT_TYPE, "application/json")
                .body(body)
                .send()
                .await
                .map_err(|_| Failure::Fallback)?;
            let status = response.status();
            received_status = Some(status);
            if status != StatusCode::OK {
                let retry_header = response
                    .headers()
                    .get(header::RETRY_AFTER)
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse::<u64>().ok())
                    .filter(|v| (1..=60).contains(v))
                    .map(|v| v * 1000);
                let body = bounded_body(&mut response, MAX_ERROR_BYTES).await;
                let mut failure = match body {
                    Ok(body) => classify_status(status, &body),
                    Err(_) => rejection(status, "primary_rejected"),
                };
                if let Failure::Reject(_, _, retry) = &mut failure {
                    if status == StatusCode::TOO_MANY_REQUESTS {
                        *retry = retry_header.or(*retry);
                    }
                }
                return Err(failure);
            }
            if response
                .headers()
                .get(header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                != Some("audio/wav")
                || response
                    .headers()
                    .get("x-teratts-text-mode")
                    .and_then(|v| v.to_str().ok())
                    != Some(request.text_mode)
            {
                return Err(invalid_response());
            }
            let body = bounded_body(&mut response, MAX_WAV_BYTES).await?;
            if !valid_wav(&body) {
                return Err(invalid_response());
            }
            Ok(body)
        };
        let result = tokio::time::timeout(self.timeout, attempt).await;
        if cancel.load(Ordering::Acquire) {
            return Err(Failure::Cancelled);
        }
        match result {
            Ok(result) => result,
            Err(_) => Err(match received_status {
                Some(status) if status != StatusCode::OK => rejection(status, "primary_rejected"),
                _ => Failure::Fallback,
            }),
        }
    }
}

fn invalid_response() -> Failure {
    Failure::Reject(StatusCode::BAD_GATEWAY, "primary_invalid_response", None)
}

fn rejection(status: StatusCode, code: &'static str) -> Failure {
    Failure::Reject(
        if status.is_client_error() || status.is_server_error() {
            status
        } else {
            StatusCode::BAD_GATEWAY
        },
        code,
        None,
    )
}

fn classify_status(status: StatusCode, body: &[u8]) -> Failure {
    #[derive(Deserialize)]
    struct ErrorCode {
        code: String,
        retry_after_ms: Option<u64>,
    }
    let parsed = serde_json::from_slice::<ErrorCode>(body).ok();
    let code = parsed.as_ref().map(|v| v.code.as_str()).unwrap_or("");
    // Only known backend failures qualify. Unknown/malformed and semantic errors
    // fail closed regardless of HTTP status; never return the upstream message.
    if matches!(
        (status.as_u16(), code),
        (500, "internal") | (503, "queue_timeout") | (504, "deadline_exceeded")
    ) {
        return Failure::Fallback;
    }
    let safe_code = match code {
        "text_mode_unavailable" => "text_mode_unavailable",
        "text_conversion_timeout" => "text_conversion_timeout",
        "text_conversion_failed" => "text_conversion_failed",
        "invalid_request" => "invalid_request",
        _ => "primary_rejected",
    };
    let mut failure = rejection(status, safe_code);
    if let Failure::Reject(_, _, retry) = &mut failure {
        if status == StatusCode::TOO_MANY_REQUESTS {
            *retry = parsed
                .and_then(|v| v.retry_after_ms)
                .filter(|v| (1..=60_000).contains(v));
        }
    }
    failure
}

async fn bounded_body(response: &mut reqwest::Response, limit: usize) -> Result<Vec<u8>, Failure> {
    if response.content_length().is_some_and(|v| v > limit as u64) {
        return Err(invalid_response());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| Failure::Fallback)? {
        if chunk.len() > limit.saturating_sub(bytes.len()) {
            return Err(invalid_response());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn valid_wav(bytes: &[u8]) -> bool {
    // The pinned server encoder emits exactly this 44-byte PCM header; reject
    // alternate containers/chunks rather than accepting unvalidated payloads.
    bytes.len() >= 46
        && bytes.len() <= MAX_WAV_BYTES
        && bytes.len().is_multiple_of(2)
        && bytes[0..4] == *b"RIFF"
        && bytes[8..16] == *b"WAVEfmt "
        && bytes[4..8] == ((bytes.len() - 8) as u32).to_le_bytes()
        && bytes[16..20] == 16u32.to_le_bytes()
        && bytes[20..24] == [1, 0, 1, 0]
        && bytes[24..28] == SAMPLE_RATE.to_le_bytes()
        && bytes[28..32] == (SAMPLE_RATE * 2).to_le_bytes()
        && bytes[32..36] == [2, 0, 16, 0]
        && bytes[36..40] == *b"data"
        && bytes[40..44] == ((bytes.len() - 44) as u32).to_le_bytes()
}

#[cfg(test)]
pub(crate) mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::task::JoinHandle;

    pub(crate) async fn mock(
        response: Vec<u8>,
        delay: Duration,
        timeout_ms: u64,
    ) -> (RemotePrimary, JoinHandle<Vec<u8>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = Vec::new();
            let mut buf = [0; 2048];
            loop {
                let n = stream.read(&mut buf).await.unwrap();
                if n == 0 {
                    break;
                }
                request.extend_from_slice(&buf[..n]);
                if let Some(end) = request.windows(4).position(|v| v == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..end]).to_ascii_lowercase();
                    let length: usize = headers
                        .lines()
                        .find_map(|v| v.strip_prefix("content-length: "))
                        .unwrap()
                        .parse()
                        .unwrap();
                    if request.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            // Send headers immediately; delay the body to exercise whole-attempt bounds.
            let split = response.windows(4).position(|v| v == b"\r\n\r\n").unwrap() + 4;
            let _ = stream.write_all(&response[..split]).await;
            tokio::time::sleep(delay).await;
            let _ = stream.write_all(&response[split..]).await;
            request
        });
        let primary = RemotePrimary::parse(
            Some(&format!("http://127.0.0.1:{port}/tts")),
            Some("test-token"),
            Some(&timeout_ms.to_string()),
            1,
        )
        .unwrap()
        .unwrap();
        (primary, server)
    }

    pub(crate) fn response(status: u16, mime: &str, mode: &str, body: &[u8]) -> Vec<u8> {
        let mut response = format!("HTTP/1.1 {status} Test\r\nContent-Type: {mime}\r\nX-Teratts-Text-Mode: {mode}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).into_bytes();
        response.extend_from_slice(body);
        response
    }

    fn forward() -> ForwardRequest<'static> {
        ForwardRequest {
            text: "  <en>Widget 15%</en>  ",
            voice: "eng_f3",
            language: "en",
            duration_scale: 1.25,
            speech_front: false,
            text_mode: "compatible",
            russian_stress: None,
        }
    }

    #[test]
    fn validates_pair_literal_uri_self_loop_and_timeout() {
        assert!(RemotePrimary::parse(None, None, None, 8088)
            .unwrap()
            .is_none());
        for (url, token, timeout) in [
            (None, Some("t"), None),
            (Some("http://127.0.0.1:18089/tts"), None, None),
            (None, None, Some("3")),
            (Some(""), Some("t"), None),
        ] {
            assert!(RemotePrimary::parse(url, token, timeout, 8088).is_err());
        }
        for url in [
            "https://127.0.0.1:18089/tts",
            "http://localhost:18089/tts",
            "http://192.168.1.1:18089/tts",
            "http://127.1:18089/tts",
            "http://2130706433:18089/tts",
            "http://0x7f000001:18089/tts",
            "http://127.0.0.1:8088/tts",
            "http://[::1]:8088/tts",
            "http://u:p@127.0.0.1:18089/tts",
            "http://@127.0.0.1:18089/tts",
            "http://127.0.0.1:18089/tts?",
            "http://127.0.0.1:18089/tts#",
            "http://127.0.0.1:18089/a/../tts",
            "http://127.0.0.1:18089/%74ts",
            "http://127.0.0.1:18089/tts/",
            "http://127.0.0.1:18089\\tts",
            " http://127.0.0.1:18089/tts",
            "http://127.0.0.1:0/tts",
            "http://::1/tts",
        ] {
            assert!(
                RemotePrimary::parse(Some(url), Some("t"), None, 8088).is_err(),
                "{url}"
            );
        }
        for url in [
            "http://127.0.0.1:18089/tts",
            "http://[::1]:18089/tts",
            "http://127.0.0.2/tts",
            "http://[::1]/tts",
        ] {
            let primary = RemotePrimary::parse(Some(url), Some("t"), None, 8088)
                .unwrap()
                .unwrap();
            assert_eq!(primary.timeout, Duration::from_millis(3000));
        }
        for timeout in ["0", "10001", "-1", "bad", "", " 3"] {
            assert!(RemotePrimary::parse(
                Some("http://127.0.0.1:18089/tts"),
                Some("t"),
                Some(timeout),
                8088
            )
            .is_err());
        }
        for token in ["", "x\ny", "x y", "секрет"] {
            assert!(RemotePrimary::parse(
                Some("http://127.0.0.1:18089/tts"),
                Some(token),
                None,
                8088
            )
            .is_err());
        }
        assert!(RemotePrimary::parse(
            Some("http://127.0.0.1:18089/tts"),
            Some("t"),
            Some("10000"),
            0
        )
        .is_err());
    }

    #[test]
    fn status_classification_is_allowlisted_and_never_leaks_messages() {
        for status in [400, 401, 403, 429, 500, 502, 503, 504] {
            for code in [
                "text_mode_unavailable",
                "text_conversion_timeout",
                "text_conversion_failed",
                "invalid_request",
                "unsupported_text",
                "unknown",
            ] {
                let body = format!(r#"{{"code":"{code}","message":"sensitive text/token"}}"#);
                let failure =
                    classify_status(StatusCode::from_u16(status).unwrap(), body.as_bytes());
                assert!(matches!(failure, Failure::Reject(_, _, _)));
                assert!(!format!("{failure:?}").contains("sensitive"));
            }
            for body in [b"not json".as_slice(), b"{}", b"{\"code\":4}"] {
                assert!(matches!(
                    classify_status(StatusCode::from_u16(status).unwrap(), body),
                    Failure::Reject(_, _, _)
                ));
            }
        }
        for (status, code) in [
            (500, "internal"),
            (503, "queue_timeout"),
            (504, "deadline_exceeded"),
        ] {
            assert_eq!(
                classify_status(
                    StatusCode::from_u16(status).unwrap(),
                    format!(r#"{{"code":"{code}"}}"#).as_bytes()
                ),
                Failure::Fallback
            );
        }
        assert!(matches!(
            classify_status(StatusCode::TOO_MANY_REQUESTS, b"{\"code\":\"internal\"}"),
            Failure::Reject(_, _, _)
        ));
    }

    #[tokio::test]
    async fn preserves_only_bounded_numeric_retry_metadata() {
        for (json_value, expected) in [(1000, Some(1000)), (0, None), (60001, None)] {
            assert_eq!(
                classify_status(
                    StatusCode::TOO_MANY_REQUESTS,
                    format!(r#"{{"code":"busy","retry_after_ms":{json_value}}}"#).as_bytes()
                ),
                Failure::Reject(StatusCode::TOO_MANY_REQUESTS, "primary_rejected", expected)
            );
        }
        let reply =
            b"HTTP/1.1 429 Busy\r\nRetry-After: 2\r\nContent-Length: 15\r\n\r\n{\"code\":\"busy\"}"
                .to_vec();
        let (primary, server) = mock(reply, Duration::ZERO, 1000).await;
        assert_eq!(
            primary.attempt(&forward(), &AtomicBool::new(false)).await,
            Err(Failure::Reject(
                StatusCode::TOO_MANY_REQUESTS,
                "primary_rejected",
                Some(2000)
            ))
        );
        server.await.unwrap();
        assert!(!primary.has_attempt_budget(Duration::from_millis(5999)));
        assert!(primary.has_attempt_budget(Duration::from_millis(6000)));
    }

    #[test]
    fn strict_wav_shape_and_maximum() {
        let good = crate::wav::encode_mono_i16(&[vec![0.0, 0.25]]).unwrap();
        assert!(valid_wav(&good));
        for index in [0, 4, 8, 16, 20, 22, 24, 28, 32, 34, 36, 40] {
            let mut bad = good.clone();
            bad[index] ^= 1;
            assert!(!valid_wav(&bad), "index {index}");
        }
        assert!(!valid_wav(&good[..43]));
        assert!(!valid_wav(&vec![0; MAX_WAV_BYTES + 1]));
        let max = crate::wav::encode_mono_i16(&[vec![0.0; (MAX_WAV_BYTES - 44) / 2]]).unwrap();
        assert!(valid_wav(&max));
    }

    #[tokio::test]
    async fn forwards_exact_json_and_validates_complete_audio() {
        let wav = crate::wav::encode_mono_i16(&[vec![0.0, 0.25]]).unwrap();
        let (primary, server) = mock(
            response(200, "audio/wav", "compatible", &wav),
            Duration::ZERO,
            1000,
        )
        .await;
        assert_eq!(
            primary
                .attempt(&forward(), &AtomicBool::new(false))
                .await
                .unwrap(),
            wav
        );
        let request = server.await.unwrap();
        let split = request.windows(4).position(|v| v == b"\r\n\r\n").unwrap() + 4;
        assert!(
            String::from_utf8_lossy(&request[..split]).contains("authorization: Bearer test-token")
        );
        let json: serde_json::Value = serde_json::from_slice(&request[split..]).unwrap();
        assert_eq!(
            json,
            serde_json::json!({"text":"  <en>Widget 15%</en>  ","voice":"eng_f3","language":"en","duration_scale":1.25,"speech_front":false,"text_mode":"compatible"})
        );
    }

    #[tokio::test]
    async fn rejects_bad_mime_mode_wav_oversize_and_redirect() {
        let wav = crate::wav::encode_mono_i16(&[vec![0.0]]).unwrap();
        let oversized_header = format!("HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nX-Teratts-Text-Mode: compatible\r\nContent-Length: {}\r\n\r\n", MAX_WAV_BYTES + 1).into_bytes();
        for reply in [
            response(200, "text/html", "compatible", &wav),
            response(200, "audio/wav", "russian_only", &wav),
            response(200, "audio/wav", "compatible", b"bad wav"),
            oversized_header,
            b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/tts\r\nContent-Length: 0\r\n\r\n"
                .to_vec(),
            response(
                500,
                "application/json",
                "compatible",
                &vec![b'x'; MAX_ERROR_BYTES + 1],
            ),
        ] {
            let (primary, server) = mock(reply, Duration::ZERO, 1000).await;
            assert!(matches!(
                primary.attempt(&forward(), &AtomicBool::new(false)).await,
                Err(Failure::Reject(_, _, _))
            ));
            server.await.unwrap();
        }
    }

    #[tokio::test]
    async fn bounds_stream_without_content_length_and_allows_transport_fallback() {
        let mut reply = b"HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nX-Teratts-Text-Mode: compatible\r\nConnection: close\r\n\r\n".to_vec();
        reply.resize(reply.len() + MAX_WAV_BYTES + 1, 0);
        let (primary, server) = mock(reply, Duration::ZERO, 1000).await;
        assert!(matches!(
            primary.attempt(&forward(), &AtomicBool::new(false)).await,
            Err(Failure::Reject(_, _, _))
        ));
        server.await.unwrap();
        let reply = b"HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nX-Teratts-Text-Mode: compatible\r\nContent-Length: 100\r\n\r\npartial".to_vec();
        let (primary, server) = mock(reply, Duration::ZERO, 1000).await;
        assert_eq!(
            primary.attempt(&forward(), &AtomicBool::new(false)).await,
            Err(Failure::Fallback)
        );
        server.await.unwrap();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let primary = RemotePrimary::parse(
            Some(&format!("http://127.0.0.1:{port}/tts")),
            Some("t"),
            Some("100"),
            1,
        )
        .unwrap()
        .unwrap();
        drop(listener);
        assert_eq!(
            primary.attempt(&forward(), &AtomicBool::new(false)).await,
            Err(Failure::Fallback)
        );
    }

    #[tokio::test]
    async fn body_timeout_falls_back_but_error_status_timeout_does_not() {
        for status in [200, 400, 401, 429, 500, 503] {
            let body = crate::wav::encode_mono_i16(&[vec![0.0]]).unwrap();
            let (primary, server) = mock(
                response(status, "audio/wav", "compatible", &body),
                Duration::from_millis(200),
                30,
            )
            .await;
            let result = primary.attempt(&forward(), &AtomicBool::new(false)).await;
            if status == 200 {
                assert_eq!(result, Err(Failure::Fallback));
            } else {
                assert!(matches!(result, Err(Failure::Reject(_, _, _))));
            }
            server.abort();
            let _ = server.await;
        }
    }

    #[tokio::test]
    async fn cancellation_prevents_dispatch_and_overrides_fallback() {
        let (primary, server) = mock(
            response(
                500,
                "application/json",
                "compatible",
                b"{\"code\":\"internal\"}",
            ),
            Duration::from_millis(50),
            1000,
        )
        .await;
        assert_eq!(
            primary.attempt(&forward(), &AtomicBool::new(true)).await,
            Err(Failure::Cancelled)
        );
        let cancel = AtomicBool::new(false);
        let set_cancel = async {
            tokio::time::sleep(Duration::from_millis(10)).await;
            cancel.store(true, Ordering::Release);
        };
        let request = forward();
        let (result, ()) = tokio::join!(primary.attempt(&request, &cancel), set_cancel);
        assert_eq!(result, Err(Failure::Cancelled));
        server.await.unwrap();
    }
}
