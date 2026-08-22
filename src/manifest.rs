//! Pinned TeraTTSv2 model manifest and installed-release checks.

use std::{
    fs::File,
    io::{BufReader, Read},
    path::{Path, PathBuf},
};

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use sha2::{Digest, Sha256};

pub const MANIFEST_JSON: &str = include_str!("../manifest/teratts-v2.json");
pub const MANIFEST_FILE: &str = "manifest.json";
pub const MANIFEST_DIGEST_FILE: &str = "manifest.sha256";

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Manifest {
    pub model: String,
    pub revision: String,
    pub url_template: String,
    pub files: Vec<ManifestFile>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct ManifestFile {
    pub path: String,
    pub size: u64,
    pub sha256: String,
}

impl Manifest {
    pub fn pinned() -> Result<Self> {
        Self::from_json(MANIFEST_JSON)
    }

    pub fn from_json(raw: &str) -> Result<Self> {
        let manifest: Self =
            serde_json::from_str(raw).map_err(|e| anyhow!("manifest parse: {e}"))?;
        if manifest.model != "TeraSpace/TeraTTSv2" {
            return Err(anyhow!("manifest model is not TeraSpace/TeraTTSv2"));
        }
        if manifest.revision.len() != 40
            || !manifest.revision.chars().all(|c| c.is_ascii_hexdigit())
        {
            return Err(anyhow!("manifest revision must be a 40-char git sha"));
        }
        if !manifest.url_template.starts_with("https://huggingface.co/")
            || !manifest.url_template.contains("{revision}")
            || !manifest.url_template.contains("{path}")
        {
            return Err(anyhow!("manifest url_template is invalid"));
        }
        if manifest.files.is_empty() {
            return Err(anyhow!("manifest lists no files"));
        }
        for file in &manifest.files {
            if file.path.is_empty()
                || file.path.starts_with('/')
                || file.path.contains("..")
                || file.path.contains('\\')
            {
                return Err(anyhow!("manifest path is unsafe: {:?}", file.path));
            }
            if file.sha256.len() != 64 || !file.sha256.chars().all(|c| c.is_ascii_hexdigit()) {
                return Err(anyhow!("manifest SHA-256 is invalid: {:?}", file.path));
            }
        }
        Ok(manifest)
    }

    pub fn release_dir(&self, model_root: &Path) -> PathBuf {
        model_root.join(format!("teratts-v2-{}", self.revision))
    }

    pub fn url_for(&self, path: &str) -> String {
        self.url_template
            .replace("{revision}", &self.revision)
            .replace("{path}", path)
    }
}

pub fn manifest_digest() -> String {
    format!("{:x}", Sha256::digest(MANIFEST_JSON.as_bytes()))
}

pub fn check_installed(manifest: &Manifest, release_dir: &Path) -> Result<()> {
    if manifest != &Manifest::pinned()? {
        return Err(anyhow!(
            "verification manifest does not match pinned manifest"
        ));
    }
    check_release(manifest, release_dir)
}

fn check_release(manifest: &Manifest, release_dir: &Path) -> Result<()> {
    require_regular_file(&release_dir.join(MANIFEST_FILE), "published manifest")?;
    require_regular_file(
        &release_dir.join(MANIFEST_DIGEST_FILE),
        "manifest digest marker",
    )?;
    let published = std::fs::read(release_dir.join(MANIFEST_FILE))
        .map_err(|_| anyhow!("published manifest missing"))?;
    if published != MANIFEST_JSON.as_bytes() {
        return Err(anyhow!("published manifest does not match pinned manifest"));
    }
    let marker = std::fs::read_to_string(release_dir.join(MANIFEST_DIGEST_FILE))
        .map_err(|_| anyhow!("manifest digest marker missing"))?;
    if marker.trim() != manifest_digest() {
        return Err(anyhow!(
            "manifest digest marker does not match pinned manifest"
        ));
    }
    for entry in &manifest.files {
        let path = release_dir.join(&entry.path);
        let meta =
            std::fs::symlink_metadata(&path).map_err(|_| anyhow!("missing {}", entry.path))?;
        if !meta.file_type().is_file() {
            return Err(anyhow!("{} is not a regular file", entry.path));
        }
        if meta.len() != entry.size {
            return Err(anyhow!(
                "{}: size {} != pinned {}",
                entry.path,
                meta.len(),
                entry.size
            ));
        }
    }
    Ok(())
}

fn require_regular_file(path: &Path, description: &str) -> Result<()> {
    let meta = std::fs::symlink_metadata(path).map_err(|_| anyhow!("{description} missing"))?;
    if !meta.file_type().is_file() {
        return Err(anyhow!("{description} is not a regular file"));
    }
    Ok(())
}

pub fn verify_models(model_root: &Path) -> Result<()> {
    let manifest = Manifest::pinned()?;
    let release = manifest.release_dir(model_root);
    verify_release(&manifest, &release)
}

pub(crate) fn verify_release(manifest: &Manifest, release_dir: &Path) -> Result<()> {
    if manifest != &Manifest::pinned()? {
        return Err(anyhow!(
            "verification manifest does not match pinned manifest"
        ));
    }
    verify_release_files(manifest, release_dir)
}

fn verify_release_files(manifest: &Manifest, release_dir: &Path) -> Result<()> {
    check_release(manifest, release_dir)?;
    let mut buffer = [0u8; 64 * 1024];
    for entry in &manifest.files {
        let path = release_dir.join(&entry.path);
        let file = File::open(&path).with_context(|| format!("open {}", entry.path))?;
        let mut reader = BufReader::new(file);
        let mut hash = Sha256::new();
        loop {
            let count = reader
                .read(&mut buffer)
                .with_context(|| format!("read {}", entry.path))?;
            if count == 0 {
                break;
            }
            hash.update(&buffer[..count]);
        }
        let digest = format!("{:x}", hash.finalize());
        if digest != entry.sha256 {
            return Err(anyhow!(
                "{}: sha256 {} != pinned {}",
                entry.path,
                digest,
                entry.sha256
            ));
        }
    }
    Ok(())
}

pub fn installed_voices(release_dir: &Path) -> Vec<String> {
    let mut voices = Vec::new();
    let styles = release_dir.join("styles");
    let Ok(entries) = std::fs::read_dir(styles) else {
        return voices;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir()
            && path.join("style_ttl.npy").is_file()
            && path.join("style_dp.npy").is_file()
        {
            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                voices.push(name.to_string());
            }
        }
    }
    voices.sort();
    voices
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;

    #[test]
    fn pinned_manifest_has_full_sha256_contract() {
        let manifest = Manifest::pinned().unwrap();
        assert_eq!(
            manifest.revision,
            "f05ea799094571a3553904a555df3834fb0b963b"
        );
        assert_eq!(manifest.files.len(), 57);
        assert!(manifest.files.iter().all(|f| f.sha256.len() == 64));
        assert!(manifest
            .url_for("config.json")
            .ends_with(&format!("/resolve/{}/config.json", manifest.revision)));
    }

    #[test]
    fn rejects_unsafe_or_unpinned_manifests() {
        let rev = "a".repeat(40);
        let bad = format!(
            r#"{{"model":"TeraSpace/TeraTTSv2","revision":"{rev}","url_template":"https://huggingface.co/x/resolve/{{revision}}/{{path}}","files":[{{"path":"../evil","size":1,"sha256":"{}"}}]}}"#,
            "0".repeat(64)
        );
        assert!(Manifest::from_json(&bad).is_err());
    }

    fn test_manifest(contents: &[u8]) -> Manifest {
        Manifest {
            model: "TeraSpace/TeraTTSv2".into(),
            revision: "a".repeat(40),
            url_template: "https://huggingface.co/x/resolve/{revision}/{path}".into(),
            files: vec![ManifestFile {
                path: "a.bin".into(),
                size: contents.len() as u64,
                sha256: format!("{:x}", Sha256::digest(contents)),
            }],
        }
    }

    fn write_publish_markers(dir: &Path) {
        std::fs::write(dir.join(MANIFEST_FILE), MANIFEST_JSON).unwrap();
        std::fs::write(dir.join(MANIFEST_DIGEST_FILE), manifest_digest()).unwrap();
    }

    #[test]
    fn installed_check_binds_exact_pinned_manifest_and_sizes() {
        let dir = tempfile::tempdir().unwrap();
        let manifest = test_manifest(b"abcd");
        std::fs::write(dir.path().join("a.bin"), b"abcd").unwrap();
        assert!(check_release(&manifest, dir.path()).is_err());

        write_publish_markers(dir.path());
        assert!(check_release(&manifest, dir.path()).is_ok());

        std::fs::write(dir.path().join(MANIFEST_FILE), b"{}").unwrap();
        assert!(check_release(&manifest, dir.path()).is_err());
        std::fs::write(dir.path().join(MANIFEST_FILE), MANIFEST_JSON).unwrap();
        std::fs::write(dir.path().join(MANIFEST_DIGEST_FILE), "0".repeat(64)).unwrap();
        assert!(check_release(&manifest, dir.path()).is_err());
    }

    #[test]
    fn explicit_verify_hashes_full_file_contents() {
        let dir = tempfile::tempdir().unwrap();
        let manifest = test_manifest(b"abcd");
        write_publish_markers(dir.path());
        std::fs::write(dir.path().join("a.bin"), b"abcd").unwrap();
        assert!(verify_release_files(&manifest, dir.path()).is_ok());

        std::fs::write(dir.path().join("a.bin"), b"wxyz").unwrap();
        assert!(check_release(&manifest, dir.path()).is_ok());
        assert!(verify_release_files(&manifest, dir.path()).is_err());
    }
}
