//! Optional bounded private stage telemetry. Never writes a separate disk spool.
use serde_json::Value;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::sync::mpsc;

static SENDER: OnceLock<Option<mpsc::Sender<Vec<u8>>>> = OnceLock::new();

fn private_endpoint(value: &str) -> Option<reqwest::Url> {
    let url = reqwest::Url::parse(value).ok()?;
    let host = url.host_str()?;
    let allowed = host == "127.0.0.1" || host == "localhost" || host == "[::1]"
        || host.parse::<std::net::Ipv4Addr>().ok().is_some_and(|ip| {
            let octets = ip.octets(); octets[0] == 100 && (64..=127).contains(&octets[1])
        });
    (allowed && url.scheme() == "http" && url.username().is_empty()
        && url.password().is_none() && url.path() == "/record"
        && url.query().is_none() && url.fragment().is_none()).then_some(url)
}

fn frame(metadata: Value) -> Option<Vec<u8>> {
    let header = serde_json::to_vec(&serde_json::json!({"metadata": metadata,"attachments": []})).ok()?;
    if header.len() > 1024 * 1024 { return None; }
    let mut result = (header.len() as u32).to_be_bytes().to_vec();
    result.extend(header);
    Some(result)
}

pub fn initialize() {
    SENDER.get_or_init(|| {
        let endpoint = std::env::var("VOICE_TELEMETRY_INGEST").ok()?;
        let Some(url) = private_endpoint(&endpoint) else {
            eprintln!("[telemetry] status=disabled reason=invalid_private_endpoint");
            return None;
        };
        let client = reqwest::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(8)).build().ok()?;
        let (sender, mut receiver) = mpsc::channel::<Vec<u8>>(16);
        tokio::spawn(async move {
            while let Some(body) = receiver.recv().await {
                match client.post(url.clone()).header("content-type", "application/octet-stream")
                    .body(body).send().await {
                    Ok(response) if response.status().is_success() => {},
                    _ => eprintln!("[telemetry] status=dropped reason=ingest_unavailable"),
                }
            }
        });
        Some(sender)
    });
}

pub fn record(metadata: Value) {
    if let Some(Some(sender)) = SENDER.get() {
        if let Some(body) = frame(metadata) {
            if sender.try_send(body).is_err() {
                eprintln!("[telemetry] status=dropped reason=queue_full");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_external_and_credential_urls() {
        for endpoint in ["https://example.com/record", "http://192.168.0.1/record",
                         "http://u:p@100.110.84.30/record", "http://100.110.84.30/status",
                         "http://100.110.84.30/record?token=secret"] {
            assert!(private_endpoint(endpoint).is_none());
        }
        assert!(private_endpoint("http://100.110.84.30:10003/record").is_some());
        assert!(private_endpoint("http://127.0.0.1:10003/record").is_some());
    }
    #[test]
    fn binary_frame_preserves_private_text() -> anyhow::Result<()> {
        let body = frame(serde_json::json!({"text":"Иван, 123", "kind":"tts_stages"}))
            .ok_or_else(|| anyhow::anyhow!("missing frame"))?;
        let count = u32::from_be_bytes(body[..4].try_into()?) as usize;
        assert_eq!(count, body.len() - 4);
        let header: Value = serde_json::from_slice(&body[4..])?;
        assert_eq!(header["metadata"]["text"], "Иван, 123");
        Ok(())
    }
}
