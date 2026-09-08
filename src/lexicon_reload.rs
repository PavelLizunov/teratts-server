//! State-owned approved lexicon snapshots. Call `refresh` only on a blocking worker.
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};

use crate::speechfront::Normalizer;

const MAX_LEXICON_BYTES: u64 = 2 * 1024 * 1024;
const DIAGNOSTIC_INTERVAL: Duration = Duration::from_secs(60);

pub(crate) struct LexiconReload {
    path: Option<PathBuf>,
    state: Mutex<Snapshot>,
}

struct Snapshot {
    normalizer: Arc<Normalizer>,
    revision: [u8; 32],
    last_diagnostic: Option<Instant>,
}

pub(crate) struct Refresh {
    pub normalizer: Arc<Normalizer>,
    /// Fixed, bounded diagnostic only: never parser errors, file paths or source text.
    pub diagnostic: Option<&'static str>,
}

impl LexiconReload {
    /// Invalid configured files fail startup, even if speech-front defaults to off.
    pub(crate) fn new(path: Option<PathBuf>) -> Result<Self, &'static str> {
        let (normalizer, revision) = match &path {
            Some(path) => {
                let bytes = read_regular_file(path)?;
                (parse(&bytes)?, Sha256::digest(&bytes).into())
            }
            None => (
                Normalizer::builtin().map_err(|_| "builtin lexicon validation failed")?,
                Sha256::digest(include_bytes!("lexicon.toml")).into(),
            ),
        };
        Ok(Self {
            path,
            state: Mutex::new(Snapshot {
                normalizer: Arc::new(normalizer),
                revision,
                last_diagnostic: None,
            }),
        })
    }

    pub(crate) fn refresh(&self) -> Refresh {
        // Serialize reads and publication so concurrent requests cannot publish
        // older snapshots out of order. Normalization holds only an Arc, not this lock.
        let mut state = self.state.lock().unwrap_or_else(|error| error.into_inner());
        let result = self.path.as_ref().map_or(Ok(()), |path| {
            let bytes = read_regular_file(path)?;
            let revision = Sha256::digest(&bytes).into();
            if revision != state.revision {
                let normalizer = Arc::new(parse(&bytes)?);
                state.normalizer = normalizer;
                state.revision = revision;
            }
            Ok(())
        });
        let diagnostic = result.err().filter(|_| {
            let now = Instant::now();
            if state
                .last_diagnostic
                .is_none_or(|last| now.duration_since(last) >= DIAGNOSTIC_INTERVAL)
            {
                state.last_diagnostic = Some(now);
                true
            } else {
                false
            }
        });
        Refresh {
            normalizer: Arc::clone(&state.normalizer),
            diagnostic,
        }
    }

    #[cfg(test)]
    pub(crate) fn revision(&self) -> [u8; 32] {
        self.state
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .revision
    }
}

fn parse(bytes: &[u8]) -> Result<Normalizer, &'static str> {
    let text = std::str::from_utf8(bytes).map_err(|_| "lexicon is not UTF-8")?;
    Normalizer::from_toml(text).map_err(|_| "lexicon validation failed")
}

fn read_regular_file(path: &Path) -> Result<Vec<u8>, &'static str> {
    use std::io::Read;

    let file = open_regular_file(path)?;
    let metadata = file.metadata().map_err(|_| "lexicon metadata failed")?;
    if !metadata.is_file() {
        return Err("lexicon must be a regular file");
    }
    if metadata.len() > MAX_LEXICON_BYTES {
        return Err("lexicon exceeds 2 MiB limit");
    }
    let mut bytes = Vec::new();
    file.take(MAX_LEXICON_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "lexicon read failed")?;
    if bytes.len() as u64 > MAX_LEXICON_BYTES {
        return Err("lexicon exceeds 2 MiB limit");
    }
    Ok(bytes)
}

fn open_regular_file(path: &Path) -> Result<std::fs::File, &'static str> {
    // Configuration and its parent directory must be operator-owned. Reject
    // special files before open; verify the opened descriptor again in the caller.
    let metadata = std::fs::metadata(path).map_err(|_| "lexicon metadata failed")?;
    if !metadata.is_file() {
        return Err("lexicon must be a regular file");
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // Linux UAPI O_NONBLOCK (not portable to other Unix platforms). This
        // additionally prevents a raced FIFO replacement from hanging open.
        options.custom_flags(0x800);
    }
    options.open(path).map_err(|_| "lexicon open failed")
}

#[cfg(test)]
pub(crate) mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used)]
    use super::*;

    pub(crate) const APPROVED: &str = "schema_version = 1\n[[entry]]\nwritten = 'Widget'\nlanguage = 'ru-RU'\nspoken = 'первый'\nmatch = 'word'\n";

    /// Models the review tool publishing the approved export by atomic replacement.
    pub(crate) fn approve(path: &Path, source: &str) {
        let mut file = tempfile::NamedTempFile::new_in(path.parent().unwrap()).unwrap();
        std::io::Write::write_all(&mut file, source.as_bytes()).unwrap();
        file.persist(path).unwrap();
    }

    #[test]
    fn atomic_approval_and_same_length_revision_replace_snapshot() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("lexicon.toml");
        approve(&path, APPROVED);
        let loader = LexiconReload::new(Some(path.clone())).unwrap();
        let old = loader.refresh().normalizer;
        let revision = loader.revision();
        let next = APPROVED.replace("первый", "второй");
        assert_eq!(next.len(), APPROVED.len());
        approve(&path, &next);
        let refreshed = loader.refresh();
        assert!(refreshed.diagnostic.is_none());
        assert_ne!(revision, loader.revision());
        assert_eq!(refreshed.normalizer.normalize("Widget"), "второй");
        assert_eq!(old.normalize("Widget"), "первый");
        assert!(Arc::ptr_eq(
            &refreshed.normalizer,
            &loader.refresh().normalizer
        ));
    }

    #[test]
    fn rejects_entire_invalid_initial_file_without_echoing_input() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("private-path.toml");
        assert!(LexiconReload::new(Some(path.clone())).is_err());
        for source in [
            "private-user-text = [",
            "schema_version = 9\nentry = []",
            &format!("{APPROVED}\n[[entry]]\nwritten = 'secret'\nlanguage = 'ru'\nspoken = ''\nmatch = 'word'"),
            &format!("{APPROVED}\n[[entry]]{}", APPROVED.split_once("[[entry]]").unwrap().1),
        ] {
            approve(&path, source);
            let error = LexiconReload::new(Some(path.clone())).err().unwrap();
            assert_eq!(error, "lexicon validation failed");
        }
        std::fs::write(&path, [0xff, 0xfe]).unwrap();
        assert_eq!(
            LexiconReload::new(Some(path)).err(),
            Some("lexicon is not UTF-8")
        );
    }

    #[test]
    fn corrupted_or_missing_update_retains_reports_and_recovers() {
        for missing in [false, true] {
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("lexicon.toml");
            approve(&path, APPROVED);
            let loader = LexiconReload::new(Some(path.clone())).unwrap();
            let revision = loader.revision();
            if missing {
                std::fs::remove_file(&path).unwrap();
            } else {
                approve(&path, "private-invalid-text = [");
            }
            let failed = loader.refresh();
            assert!(failed.diagnostic.is_some());
            assert_eq!(failed.normalizer.normalize("Widget"), "первый");
            assert_eq!(loader.revision(), revision);
            assert!(
                loader.refresh().diagnostic.is_none(),
                "diagnostics must be rate limited"
            );
            approve(&path, &APPROVED.replace("первый", "второй"));
            assert_eq!(loader.refresh().normalizer.normalize("Widget"), "второй");
            assert_ne!(loader.revision(), revision);
        }
    }

    #[test]
    fn bounds_reads_and_rejects_nonregular_files() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(
            LexiconReload::new(Some(dir.path().into())).err(),
            Some("lexicon must be a regular file")
        );
        let path = dir.path().join("oversized.toml");
        let file = std::fs::File::create(&path).unwrap();
        file.set_len(MAX_LEXICON_BYTES + 1).unwrap();
        assert_eq!(
            LexiconReload::new(Some(path)).err(),
            Some("lexicon exceeds 2 MiB limit")
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn fifo_is_rejected_without_a_writer() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("fifo");
        assert!(std::process::Command::new("mkfifo")
            .arg(&path)
            .status()
            .unwrap()
            .success());
        assert_eq!(
            LexiconReload::new(Some(path)).err(),
            Some("lexicon must be a regular file")
        );
    }

    #[test]
    #[ignore = "requires SPEECH_FRONT_TEST_BIN pointing to the speech-front CLI"]
    fn cross_project_approve_reloads() {
        let binary = std::env::var_os("SPEECH_FRONT_TEST_BIN").expect("set SPEECH_FRONT_TEST_BIN");
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("lexicon.toml");
        let database = dir.path().join("queue.sqlite3");
        approve(&path, "schema_version = 1\nentry = []\n");
        let loader = LexiconReload::new(Some(path.clone())).unwrap();
        let initial_revision = loader.revision();
        assert_eq!(
            loader.refresh().normalizer.normalize("MyWidget"),
            "MyWidget"
        );
        for args in [
            vec![
                "observe",
                "--project",
                "integration-test",
                "Проверяем MyWidget сейчас.",
            ],
            vec![
                "approve",
                "--written",
                "MyWidget",
                "--spoken",
                "май виджет",
                "--confirm",
            ],
        ] {
            let output = std::process::Command::new(&binary)
                .args(args)
                .arg("--db")
                .arg(&database)
                .arg("--lexicon")
                .arg(&path)
                .output()
                .unwrap();
            // Do not echo CLI output: a failure must not leak source or local paths.
            assert!(
                output.status.success(),
                "speech-front fixture command failed"
            );
        }
        let refreshed = loader.refresh();
        assert!(refreshed.diagnostic.is_none());
        assert_ne!(loader.revision(), initial_revision);
        assert_eq!(refreshed.normalizer.normalize("MyWidget"), "май виджет");
    }

    #[test]
    fn unset_uses_builtin_without_external_files() {
        let loader = LexiconReload::new(None).unwrap();
        let refreshed = loader.refresh();
        assert!(refreshed.diagnostic.is_none());
        assert!(refreshed.normalizer.entry_count() >= 162);
        assert_eq!(
            refreshed.normalizer.normalize("Рост 15%"),
            "Рост пятнадцать процентов"
        );
    }
}
