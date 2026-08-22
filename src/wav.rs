use std::io::Write;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

use anyhow::{anyhow, Context, Result};

use crate::tera::SAMPLE_RATE;

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub fn encode_mono_i16(chunks: &[Vec<f32>]) -> Result<Vec<u8>> {
    let samples = chunks.iter().try_fold(0usize, |total, chunk| {
        total
            .checked_add(chunk.len())
            .ok_or_else(|| anyhow!("wav sample count overflow"))
    })?;
    let data_len = samples
        .checked_mul(2)
        .and_then(|n| u32::try_from(n).ok())
        .ok_or_else(|| anyhow!("wav is too large"))?;
    let riff_len = data_len
        .checked_add(36)
        .ok_or_else(|| anyhow!("wav is too large"))?;
    let capacity = (data_len as usize)
        .checked_add(44)
        .ok_or_else(|| anyhow!("wav is too large"))?;
    let mut wav = Vec::new();
    wav.try_reserve_exact(capacity)
        .map_err(|_| anyhow!("wav allocation failed"))?;
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&riff_len.to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&SAMPLE_RATE.to_le_bytes());
    wav.extend_from_slice(&(SAMPLE_RATE * 2).to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&data_len.to_le_bytes());
    for sample in chunks.iter().flatten() {
        let pcm = (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i16;
        wav.extend_from_slice(&pcm.to_le_bytes());
    }
    Ok(wav)
}

pub fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow!("output path has no valid file name"))?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temporary = parent.join(format!(".{name}.{}.{}.tmp", std::process::id(), sequence));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .with_context(|| format!("create {}", temporary.display()))?;
        file.write_all(bytes)
            .with_context(|| format!("write {}", temporary.display()))?;
        file.sync_all()
            .with_context(|| format!("sync {}", temporary.display()))?;
        drop(file);
        std::fs::rename(&temporary, path).with_context(|| format!("publish {}", path.display()))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn writes_pcm_wav_header_and_clamps_samples() {
        let wav = encode_mono_i16(&[vec![-2.0, 0.0, 2.0]]).unwrap();
        assert_eq!(&wav[0..4], b"RIFF");
        assert_eq!(&wav[8..12], b"WAVE");
        assert_eq!(u32::from_le_bytes(wav[24..28].try_into().unwrap()), 44_100);
        assert_eq!(u16::from_le_bytes(wav[34..36].try_into().unwrap()), 16);
        assert_eq!(u32::from_le_bytes(wav[40..44].try_into().unwrap()), 6);
        assert_eq!(i16::from_le_bytes(wav[44..46].try_into().unwrap()), -32767);
        assert_eq!(i16::from_le_bytes(wav[48..50].try_into().unwrap()), 32767);
    }

    #[test]
    fn atomically_replaces_output_without_leaving_staging() {
        let dir = tempfile::tempdir().unwrap();
        let output = dir.path().join("voice.wav");
        std::fs::write(&output, b"old").unwrap();
        write_atomic(&output, b"new").unwrap();
        assert_eq!(std::fs::read(&output).unwrap(), b"new");
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 1);
    }
}
