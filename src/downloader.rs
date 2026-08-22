use std::path::Path;

use anyhow::{anyhow, Context, Result};
use reqwest::Client;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;

use crate::manifest::{Manifest, MANIFEST_JSON};

pub async fn download_models(model_root: &Path) -> Result<()> {
    let manifest = Manifest::pinned()?;
    let release = manifest.release_dir(model_root);
    if crate::manifest::check_installed(&manifest, &release).is_ok() {
        println!("models already installed: {}", release.display());
        return Ok(());
    }

    let staging = model_root.join(format!(".teratts-v2-{}.part", manifest.revision));
    if staging.exists() {
        std::fs::remove_dir_all(&staging)
            .with_context(|| format!("remove stale staging dir {}", staging.display()))?;
    }
    std::fs::create_dir_all(&staging)
        .with_context(|| format!("create staging dir {}", staging.display()))?;

    let client = Client::builder().build()?;
    let result = async {
        for entry in &manifest.files {
            let target = staging.join(&entry.path);
            if let Some(parent) = target.parent() {
                tokio::fs::create_dir_all(parent).await?;
            }
            println!("downloading {}", entry.path);
            let mut response = client
                .get(manifest.url_for(&entry.path))
                .send()
                .await?
                .error_for_status()?;
            let part = target.with_extension(format!(
                "{}part",
                target
                    .extension()
                    .and_then(|value| value.to_str())
                    .map(|value| format!("{value}."))
                    .unwrap_or_default()
            ));
            let mut file = tokio::fs::File::create(&part).await?;
            let mut hash = Sha256::new();
            let mut size = 0u64;
            while let Some(chunk) = response.chunk().await? {
                size = size
                    .checked_add(chunk.len() as u64)
                    .ok_or_else(|| anyhow!("download size overflow"))?;
                hash.update(&chunk);
                file.write_all(&chunk).await?;
            }
            file.flush().await?;
            drop(file);
            let digest = format!("{:x}", hash.finalize());
            if size != entry.size || digest != entry.sha256 {
                return Err(anyhow!(
                    "{} failed verification: size {size}/{}, sha256 {digest}/{}",
                    entry.path,
                    entry.size,
                    entry.sha256
                ));
            }
            tokio::fs::rename(part, target).await?;
        }
        tokio::fs::write(staging.join("manifest.json"), MANIFEST_JSON).await?;
        Result::<()>::Ok(())
    }
    .await;

    if let Err(error) = result {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error);
    }
    if release.exists() {
        std::fs::remove_dir_all(&release)
            .with_context(|| format!("remove incomplete release {}", release.display()))?;
    }
    std::fs::rename(&staging, &release)
        .with_context(|| format!("publish model release {}", release.display()))?;
    println!("models installed: {}", release.display());
    Ok(())
}
