use std::path::PathBuf;
use anyhow::{anyhow, Result};

#[path = "../tera.rs"]
mod tera;
#[path = "../indexer.rs"]
mod indexer;
#[path = "../textnorm.rs"]
mod textnorm;
#[path = "../manifest.rs"]
mod manifest;
#[path = "../execution_provider.rs"]
mod execution_provider;
#[path = "../rng.rs"]
mod rng;
#[path = "../npy.rs"]
mod npy;
#[path = "../wav.rs"]
mod wav;

use tera::{TeraEngine, VocoderWindowPolicy};

fn main() -> Result<()> {
    let model_dir = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/var/lib/teratts/models"));

    println!("Loading TeraEngine from {}...", model_dir.display());
    let mut engine = TeraEngine::load(&model_dir)?;

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
            VocoderWindowPolicy::Fixed16,
        )?;
        let flat_fixed16: Vec<f32> = out_fixed16.chunks.into_iter().flatten().collect();

        // 3. Decode with First16Then32 on the EXACT SAME latent
        let out_16_32 = engine.decode_latent_with_policy(
            &latent_out,
            latent_length,
            max_samples,
            VocoderWindowPolicy::First16Then32,
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
        let boundary_sample = 16 * 3072;
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
