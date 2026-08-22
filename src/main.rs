mod chunk;
mod downloader;
mod indexer;
mod manifest;
mod npy;
mod num2words;
mod rng;
mod server;
mod tera;
mod textnorm;
mod wav;

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};

fn usage() -> &'static str {
    "teratts-server\n\
     \n\
     Usage:\n\
       teratts-server --download-models [--model-dir PATH]\n\
       teratts-server --serve [--host HOST] [--port PORT] [--model-dir PATH]\n\
       teratts-server --speak TEXT [--voice ID] [--duration-scale N] [--output FILE] [--model-dir PATH]\n\
     \n\
     Defaults: host 127.0.0.1, port 8088, voice ru_f1, duration-scale 1.0, output output.wav.\n"
}

#[derive(Debug, PartialEq)]
enum Command {
    Download {
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
            "--download-models" | "--serve" => {
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
        Some("--serve") => Ok(Command::Serve {
            model_dir,
            host,
            port,
        }),
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
    }
    Ok(())
}

fn speak(
    model_dir: &Path,
    text: &str,
    voice: &str,
    duration_scale: f32,
    output: &Path,
) -> Result<()> {
    if text.trim().is_empty() {
        return Err(anyhow!("text is empty"));
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
                )?
                .chunks,
        );
    }
    std::fs::write(output, wav::encode_mono_i16(&chunks)?)
        .with_context(|| format!("write {}", output.display()))?;
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
        assert!(parse_args(vec!["--serve".into(), "--speak".into(), "x".into()]).is_err());
    }
}
