//! Pinned TeraTTSv2 model manifest and installed-release checks.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Result};
use serde::Deserialize;

pub const MANIFEST_JSON: &str = include_str!("../manifest/teratts-v2.json");

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub model: String,
    pub revision: String,
    pub url_template: String,
    pub files: Vec<ManifestFile>,
}

#[derive(Debug, Clone, Deserialize)]
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

pub fn check_installed(manifest: &Manifest, release_dir: &Path) -> Result<()> {
    if !release_dir.join("manifest.json").is_file() {
        return Err(anyhow!("publish marker missing"));
    }
    for entry in &manifest.files {
        let path = release_dir.join(&entry.path);
        let meta = std::fs::metadata(&path).map_err(|_| anyhow!("missing {}", entry.path))?;
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
        assert_eq!(manifest.files.len(), 27);
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

    #[test]
    fn installed_check_requires_marker_and_sizes() {
        let dir = tempfile::tempdir().unwrap();
        let manifest = Manifest {
            model: "TeraSpace/TeraTTSv2".into(),
            revision: "a".repeat(40),
            url_template: "https://huggingface.co/x/resolve/{revision}/{path}".into(),
            files: vec![ManifestFile {
                path: "a.bin".into(),
                size: 4,
                sha256: "0".repeat(64),
            }],
        };
        assert!(check_installed(&manifest, dir.path()).is_err());
        std::fs::write(dir.path().join("manifest.json"), "{}").unwrap();
        std::fs::write(dir.path().join("a.bin"), b"abcd").unwrap();
        assert!(check_installed(&manifest, dir.path()).is_ok());
    }
}
