use std::{
    fs::{File, OpenOptions},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

#[cfg(target_os = "linux")]
use std::{ffi::CString, os::unix::ffi::OsStrExt};

use anyhow::{anyhow, Context, Result};
use reqwest::Client;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;

use crate::manifest::{self, Manifest, MANIFEST_DIGEST_FILE, MANIFEST_FILE, MANIFEST_JSON};

static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct DownloadLock {
    _file: File,
}

impl DownloadLock {
    fn acquire(model_root: &Path) -> Result<Self> {
        std::fs::create_dir_all(model_root)
            .with_context(|| format!("create model root {}", model_root.display()))?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(model_root.join(".teratts-v2.download.lock"))
            .context("open model download lock")?;
        lock_file(&file)?;
        Ok(Self { _file: file })
    }
}

#[cfg(target_os = "linux")]
fn lock_file(file: &File) -> Result<()> {
    use std::os::fd::AsRawFd;

    const LOCK_EX: i32 = 2;
    const LOCK_NB: i32 = 4;
    unsafe extern "C" {
        fn flock(fd: i32, operation: i32) -> i32;
    }
    if unsafe { flock(file.as_raw_fd(), LOCK_EX | LOCK_NB) } == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error()).context("lock model downloads")
    }
}

#[cfg(not(target_os = "linux"))]
fn lock_file(_file: &File) -> Result<()> {
    Err(anyhow!(
        "model download locking is unsupported on this platform"
    ))
}

struct StagingDir(PathBuf);

impl StagingDir {
    fn create(model_root: &Path, revision: &str) -> Result<Self> {
        loop {
            let sequence = STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let path = model_root.join(format!(
                ".teratts-v2-{revision}.{}.{}.part",
                std::process::id(),
                sequence
            ));
            match std::fs::create_dir(&path) {
                Ok(()) => return Ok(Self(path)),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => {
                    return Err(error)
                        .with_context(|| format!("create staging dir {}", path.display()));
                }
            }
        }
    }

    fn path(&self) -> &Path {
        &self.0
    }

    fn publish(mut self, release: &Path) -> Result<()> {
        rename_no_replace(&self.0, release)
            .with_context(|| format!("publish model release {}", release.display()))?;
        self.0 = PathBuf::new();
        Ok(())
    }
}

impl Drop for StagingDir {
    fn drop(&mut self) {
        if !self.0.as_os_str().is_empty() {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}

#[cfg(target_os = "linux")]
fn rename_no_replace(source: &Path, destination: &Path) -> Result<()> {
    const AT_FDCWD: i32 = -100;
    const RENAME_NOREPLACE: u32 = 1;
    unsafe extern "C" {
        fn renameat2(
            olddirfd: i32,
            oldpath: *const std::ffi::c_char,
            newdirfd: i32,
            newpath: *const std::ffi::c_char,
            flags: u32,
        ) -> i32;
    }
    let source =
        CString::new(source.as_os_str().as_bytes()).context("staging path contains NUL")?;
    let destination =
        CString::new(destination.as_os_str().as_bytes()).context("release path contains NUL")?;
    if unsafe {
        renameat2(
            AT_FDCWD,
            source.as_ptr(),
            AT_FDCWD,
            destination.as_ptr(),
            RENAME_NOREPLACE,
        )
    } == 0
    {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error()).context("atomic no-replace rename")
    }
}

#[cfg(not(target_os = "linux"))]
fn rename_no_replace(_source: &Path, _destination: &Path) -> Result<()> {
    Err(anyhow!(
        "immutable publication is unsupported on this platform"
    ))
}

pub async fn download_models(model_root: &Path) -> Result<()> {
    let manifest = Manifest::pinned()?;
    let release = manifest.release_dir(model_root);
    if manifest::verify_release(&manifest, &release).is_ok() {
        println!(
            "models already installed and verified: {}",
            release.display()
        );
        return Ok(());
    }

    let _lock = DownloadLock::acquire(model_root)?;
    if release.exists() {
        manifest::verify_release(&manifest, &release).with_context(|| {
            format!(
                "immutable model release already exists but is invalid: {}",
                release.display()
            )
        })?;
        println!("models already installed: {}", release.display());
        return Ok(());
    }

    let staging = StagingDir::create(model_root, &manifest.revision)?;
    download_release(&manifest, staging.path()).await?;

    match staging.publish(&release) {
        Ok(()) => {
            println!("models installed: {}", release.display());
            Ok(())
        }
        Err(publish_error) if release.exists() => {
            manifest::verify_release(&manifest, &release).with_context(|| {
                format!(
                    "publication raced with an invalid existing release after: {publish_error:#}"
                )
            })?;
            println!(
                "models already installed by another process: {}",
                release.display()
            );
            Ok(())
        }
        Err(error) => Err(error),
    }
}

async fn download_release(manifest: &Manifest, staging: &Path) -> Result<()> {
    let client = Client::builder().build()?;
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
        file.sync_all().await?;
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
    tokio::fs::write(staging.join(MANIFEST_FILE), MANIFEST_JSON).await?;
    tokio::fs::write(
        staging.join(MANIFEST_DIGEST_FILE),
        format!("{}\n", manifest::manifest_digest()),
    )
    .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[cfg(target_os = "linux")]
    #[test]
    fn download_lock_excludes_another_process_attempt() {
        let root = tempfile::tempdir().unwrap();
        let first = DownloadLock::acquire(root.path()).unwrap();
        assert!(DownloadLock::acquire(root.path()).is_err());
        drop(first);
        assert!(DownloadLock::acquire(root.path()).is_ok());
    }

    #[test]
    fn staging_dirs_are_unique_and_inside_model_root() {
        let root = tempfile::tempdir().unwrap();
        let first = StagingDir::create(root.path(), "revision").unwrap();
        let second = StagingDir::create(root.path(), "revision").unwrap();
        assert_ne!(first.path(), second.path());
        assert_eq!(first.path().parent(), Some(root.path()));
        assert_eq!(second.path().parent(), Some(root.path()));
    }

    #[test]
    fn publication_never_replaces_existing_release() {
        let root = tempfile::tempdir().unwrap();
        let release = root.path().join("release");
        std::fs::create_dir(&release).unwrap();
        std::fs::write(release.join("winner"), b"keep").unwrap();
        let staging = StagingDir::create(root.path(), "revision").unwrap();
        let staging_path = staging.path().to_path_buf();
        std::fs::write(staging.path().join("candidate"), b"discard").unwrap();

        assert!(staging.publish(&release).is_err());
        assert_eq!(std::fs::read(release.join("winner")).unwrap(), b"keep");
        assert!(!release.join("candidate").exists());
        assert!(!staging_path.exists());
    }
}
