mod chunk;
mod downloader;
mod execution_provider;
mod indexer;
mod lexicon_reload;
mod manifest;
mod npy;
mod num2words;
mod remote_primary;
mod rng;
mod russian_only;
mod server;
mod speechfront;
mod tera;
mod textnorm;
mod wav;

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};

// Phase A (perf spec): mimalloc reduces allocator contention/fragmentation for
// ORT's per-step tensor allocations; zero numerical impact.
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

fn usage() -> &'static str {
    "teratts-server\n\
     \n\
     Usage:\n\
       teratts-server --download-models [--model-dir PATH]\n\
       teratts-server --verify-models [--model-dir PATH]\n\
       teratts-server --serve [--host HOST] [--port PORT] [--model-dir PATH]\n\
       teratts-server --speak TEXT [--voice ID] [--duration-scale N] [--output FILE] [--model-dir PATH]\n\
       teratts-server --vocoder-compare [--model-dir PATH]\n\
     \n\
     Defaults: host 127.0.0.1, port 8088, voice ru_f1, duration-scale 1.0, output output.wav.\n"
}

#[derive(Debug, PartialEq)]
enum Command {
    Download {
        model_dir: PathBuf,
    },
    Verify {
        model_dir: PathBuf,
    },
    Serve {
        model_dir: PathBuf,
        host: String,
        port: u16,
    },
    Speak {
        model_dir: PathBuf,
        text: String,
        voice: String,
        duration_scale: f32,
        output: PathBuf,
    },
    VocoderCompare {
        model_dir: PathBuf,
    },
    Help,
}

fn default_model_dir() -> PathBuf {
    if let Some(path) = std::env::var_os("TERATTS_MODEL_DIR") {
        return path.into();
    }
    if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join("teratts-server")
            .join("models")
    } else {
        std::env::var_os("XDG_CACHE_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
            .unwrap_or_else(|| PathBuf::from("."))
            .join("teratts-server")
            .join("models")
    }
}

fn take_value(args: &[String], index: &mut usize, flag: &str) -> Result<String> {
    *index += 1;
    args.get(*index)
        .cloned()
        .ok_or_else(|| anyhow!("{flag} requires a value"))
}

fn parse_args(args: Vec<String>) -> Result<Command> {
    if args.is_empty() || args.iter().any(|arg| arg == "--help" || arg == "-h") {
        return Ok(Command::Help);
    }
    let mut mode: Option<&str> = None;
    let mut text: Option<String> = None;
    let mut model_dir = default_model_dir();
    let mut host = "127.0.0.1".to_string();
    let mut port = 8088u16;
    let mut voice = "ru_f1".to_string();
    let mut duration_scale = 1.0f32;
    let mut output = PathBuf::from("output.wav");
    let mut index = 0usize;
    while index < args.len() {
        match args[index].as_str() {
            "--download-models" | "--verify-models" | "--serve" | "--vocoder-compare" => {
                if mode.replace(args[index].as_str()).is_some() {
                    return Err(anyhow!("choose exactly one command"));
                }
            }
            "--speak" => {
                if mode.replace("--speak").is_some() {
                    return Err(anyhow!("choose exactly one command"));
                }
                text = Some(take_value(&args, &mut index, "--speak")?);
            }
            "--model-dir" => model_dir = take_value(&args, &mut index, "--model-dir")?.into(),
            "--host" => host = take_value(&args, &mut index, "--host")?,
            "--port" => {
                port = take_value(&args, &mut index, "--port")?
                    .parse()
                    .context("--port must be an integer from 0 to 65535")?;
            }
            "--voice" => voice = take_value(&args, &mut index, "--voice")?,
            "--duration-scale" => {
                duration_scale = take_value(&args, &mut index, "--duration-scale")?
                    .parse()
                    .context("--duration-scale must be a number")?;
            }
            "--output" => output = take_value(&args, &mut index, "--output")?.into(),
            unknown => return Err(anyhow!("unknown argument: {unknown}")),
        }
        index += 1;
    }
    match mode {
        Some("--download-models") => Ok(Command::Download { model_dir }),
        Some("--verify-models") => Ok(Command::Verify { model_dir }),
        Some("--serve") => Ok(Command::Serve {
            model_dir,
            host,
            port,
        }),
        Some("--vocoder-compare") => Ok(Command::VocoderCompare { model_dir }),
        Some("--speak") => Ok(Command::Speak {
            model_dir,
            text: text.ok_or_else(|| anyhow!("--speak requires text"))?,
            voice,
            duration_scale,
            output,
        }),
        _ => Err(anyhow!("no command selected")),
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    match parse_args(std::env::args().skip(1).collect())? {
        Command::Help => print!("{}", usage()),
        Command::Download { model_dir } => downloader::download_models(&model_dir).await?,
        Command::Verify { model_dir } => {
            manifest::verify_models(&model_dir)?;
            println!("models verified: {}", model_dir.display());
        }
        Command::Serve {
            model_dir,
            host,
            port,
        } => server::serve(&model_dir, &host, port).await?,
        Command::Speak {
            model_dir,
            text,
            voice,
            duration_scale,
            output,
        } => speak(&model_dir, &text, &voice, duration_scale, &output)?,
        Command::VocoderCompare { model_dir } => run_vocoder_compare(&model_dir)?,
    }
    Ok(())
}

fn run_vocoder_compare(model_dir: &Path) -> Result<()> {
    println!("Loading TeraEngine from {}...", model_dir.display());
    let mut engine = tera::TeraEngine::load(model_dir)?;

    let test_cases = [
        ("short (~50 frames)", "Привет! Это проверка короткой фразы."),
        ("medium (~85 frames)", "В данном отчете рассматриваются результаты первичного аудита инфраструктуры серверов синтеза речи."),
        ("long (~120 frames)", "Подсистема представляет собой высокопроизводительный сервер синтеза речи на базе ONNX Runtime с поддержкой causal overlap-save streaming."),
    ];

    println!("\n=== RUNNING VOCODER WINDOW FIDELITY VALIDATION ===");

    for (label, text) in test_cases {
        println!("\n--- Test Case: {label} ---");
        println!("Input text: \"{text}\"");

        // 1. Run Sampler ONCE on this text to get the exact identical latent
        let (latent_out, latent_length, max_samples) =
            engine.sample_latent(text, "ru_f1", 1.0, 12345)?;
        println!("Latent frames: {latent_length}, max_samples: {max_samples}");

        // 2. Decode with Fixed16
        let out_fixed16 = engine.decode_latent_with_policy(
            &latent_out,
            latent_length,
            max_samples,
            tera::VocoderWindowPolicy::Fixed16,
        )?;
        let flat_fixed16: Vec<f32> = out_fixed16.chunks.into_iter().flatten().collect();

        // 3. Decode with First16Then32 on the EXACT SAME latent
        let out_16_32 = engine.decode_latent_with_policy(
            &latent_out,
            latent_length,
            max_samples,
            tera::VocoderWindowPolicy::First16Then32,
        )?;
        let flat_16_32: Vec<f32> = out_16_32.chunks.into_iter().flatten().collect();

        // 4. Detailed numerical comparison
        assert_eq!(
            flat_fixed16.len(),
            flat_16_32.len(),
            "Sample count must match exactly"
        );
        let n = flat_fixed16.len();
        println!("Total samples: {n}");

        let mut max_abs_diff = 0.0f32;
        let mut sum_sq_diff = 0.0f64;
        let mut sum_sq_signal = 0.0f64;
        let mut nan_inf_count = 0usize;

        // Check frame 16 boundary (sample 16 * 3072 = 49152)
        let boundary_sample: usize = 16 * 3072;
        let mut boundary_max_diff = 0.0f32;

        for i in 0..n {
            let a = flat_fixed16[i];
            let b = flat_16_32[i];

            if !a.is_finite() || !b.is_finite() {
                nan_inf_count += 1;
            }

            let diff = (a - b).abs();
            if diff > max_abs_diff {
                max_abs_diff = diff;
            }
            sum_sq_diff += (diff as f64) * (diff as f64);
            sum_sq_signal += (a as f64) * (a as f64);

            if i >= boundary_sample.saturating_sub(100) && i <= boundary_sample + 100 && diff > boundary_max_diff {
                boundary_max_diff = diff;
            }
        }

        let rms_error = (sum_sq_diff / n as f64).sqrt();
        let rms_signal = (sum_sq_signal / n as f64).sqrt();
        let snr_db = if rms_error > 0.0 {
            20.0 * (rms_signal / rms_error).log10()
        } else {
            f64::INFINITY
        };

        println!("NaN/Inf count: {nan_inf_count}");
        println!("Max abs error: {max_abs_diff:.6}");
        println!("RMS error: {rms_error:.6}");
        println!("SNR (Signal-to-Noise Ratio): {snr_db:.2} dB");
        println!("Boundary error (around sample {boundary_sample}): {boundary_max_diff:.6}");

        // Save WAVs
        let wav_fixed16 = wav::encode_mono_i16(&[flat_fixed16])?;
        let wav_16_32 = wav::encode_mono_i16(&[flat_16_32])?;

        let out_f16 = format!("/tmp/vocoder_{}_fixed16.wav", latent_length);
        let out_16_32_path = format!("/tmp/vocoder_{}_16_32.wav", latent_length);
        std::fs::write(&out_f16, &wav_fixed16)?;
        std::fs::write(&out_16_32_path, &wav_16_32)?;
        println!("Saved comparison WAVs to {out_f16} and {out_16_32_path}");
    }

    println!("\n=== ALL TEST CASES COMPLETED SUCCESSFULLY ===");
    Ok(())
}

fn speak(
    model_dir: &Path,
    text: &str,
    voice: &str,
    duration_scale: f32,
    output: &Path,
) -> Result<()> {
    let text_chars = text.trim().chars().count();
    if text_chars == 0 || text_chars > server::MAX_TEXT_CHARS {
        return Err(anyhow!(
            "text must contain 1..={} characters",
            server::MAX_TEXT_CHARS
        ));
    }
    if !duration_scale.is_finite() || !(0.25..=4.0).contains(&duration_scale) {
        return Err(anyhow!("duration-scale must be between 0.25 and 4.0"));
    }
    let mut engine = tera::TeraEngine::load(model_dir)?;
    let mut chunks = Vec::new();
    for (index, part) in chunk::chunk_text(&chunk::sanitize(text))
        .into_iter()
        .enumerate()
    {
        chunks.extend(
            engine
                .synthesize(
                    &part,
                    voice,
                    "ru",
                    duration_scale,
                    tera::SEED + index as u64,
                    true,
                )?
                .chunks,
        );
    }
    wav::write_atomic(output, &wav::encode_mono_i16(&chunks)?)?;
    println!("wrote {}", output.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn parses_minimal_commands() {
        let command = parse_args(vec!["--serve".into(), "--port".into(), "9000".into()]).unwrap();
        assert!(matches!(command, Command::Serve { port: 9000, .. }));
        let command = parse_args(vec!["--speak".into(), "привет".into()]).unwrap();
        assert!(matches!(command, Command::Speak { text, .. } if text == "привет"));
        let command = parse_args(vec!["--verify-models".into()]).unwrap();
        assert!(matches!(command, Command::Verify { .. }));
        let command = parse_args(vec!["--vocoder-compare".into()]).unwrap();
        assert!(matches!(command, Command::VocoderCompare { .. }));
        assert!(parse_args(vec!["--serve".into(), "--speak".into(), "x".into()]).is_err());
    }
}
