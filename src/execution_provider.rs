//! Operator-selected Tera provider; configuration is not GPU memory admission.

use std::ffi::OsStr;

use anyhow::{anyhow, Result};
use ort::session::builder::SessionBuilder;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Provider {
    Cpu,
    #[cfg(feature = "cuda")]
    Cuda {
        memory_limit: usize,
    },
}

impl Provider {
    pub(crate) fn from_env() -> Result<Self> {
        Self::parse(
            std::env::var_os("TERATTS_EXECUTION_PROVIDER").as_deref(),
            std::env::var_os("TERATTS_CUDA_MEMORY_LIMIT_MIB").as_deref(),
        )
    }

    fn parse(provider: Option<&OsStr>, budget: Option<&OsStr>) -> Result<Self> {
        match provider.map(OsStr::to_str) {
            None | Some(Some("cpu")) => Ok(Self::Cpu),
            Some(Some("cuda")) => {
                if !cfg!(feature = "cuda") {
                    return Err(anyhow!("CUDA requires a build with --features cuda"));
                }
                let mib = budget
                    .and_then(OsStr::to_str)
                    .filter(|value| !value.is_empty() && value.bytes().all(|b| b.is_ascii_digit()))
                    .and_then(|value| value.parse::<usize>().ok())
                    .filter(|value| (1..=16384).contains(value))
                    .ok_or_else(|| anyhow!("CUDA requires TERATTS_CUDA_MEMORY_LIMIT_MIB in 1..=16384 (per session; not a total VRAM cap)"))?;
                let _memory_limit = mib
                    .checked_mul(1024 * 1024)
                    .ok_or_else(|| anyhow!("CUDA memory limit exceeds platform address range"))?;
                #[cfg(feature = "cuda")]
                return Ok(Self::Cuda {
                    memory_limit: _memory_limit,
                });
                #[cfg(not(feature = "cuda"))]
                Err(anyhow!("CUDA requires a build with --features cuda"))
            }
            _ => Err(anyhow!("TERATTS_EXECUTION_PROVIDER must be cpu or cuda")),
        }
    }

    pub(crate) fn configure(self, builder: SessionBuilder) -> Result<SessionBuilder> {
        match self {
            Self::Cpu => Ok(builder),
            #[cfg(feature = "cuda")]
            Self::Cuda { memory_limit } => {
                use ort::ep::{cuda::ConvAlgorithmSearch, ArenaExtendStrategy, CUDA};
                let cuda = CUDA::default()
                    .with_device_id(0)
                    .with_memory_limit(memory_limit)
                    .with_arena_extend_strategy(ArenaExtendStrategy::SameAsRequested)
                    .with_conv_algorithm_search(ConvAlgorithmSearch::Heuristic)
                    .with_conv_max_workspace(false)
                    .with_tf32(false)
                    .build()
                    .error_on_failure();
                builder
                    .with_execution_providers([cuda])
                    .map_err(|error| anyhow!("CUDA registration failed (no CPU fallback): {error}"))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(provider: Option<&str>, budget: Option<&str>) -> Result<Provider> {
        Provider::parse(provider.map(OsStr::new), budget.map(OsStr::new))
    }

    #[test]
    fn cpu_default_and_explicit_ignore_cuda_budget() {
        assert_eq!(parse(None, None).unwrap(), Provider::Cpu);
        assert_eq!(parse(Some("cpu"), Some("invalid")).unwrap(), Provider::Cpu);
    }

    #[test]
    fn invalid_provider_is_rejected() {
        for provider in ["", "CUDA", "auto", " cpu", "tensorrt"] {
            assert!(parse(Some(provider), None).is_err());
        }
    }

    #[cfg(not(feature = "cuda"))]
    #[test]
    fn cuda_requires_compiled_feature() {
        for budget in [None, Some("128")] {
            let error = parse(Some("cuda"), budget).unwrap_err();
            assert!(error.to_string().contains("--features cuda"));
        }
    }

    #[cfg(feature = "cuda")]
    #[test]
    fn cuda_requires_bounded_positive_budget() {
        for budget in [
            None,
            Some(""),
            Some("0"),
            Some("-1"),
            Some("+1"),
            Some("1.5"),
            Some(" 128"),
            Some("16385"),
            Some("184467440737095516160"),
        ] {
            assert!(parse(Some("cuda"), budget).is_err(), "{budget:?}");
        }
        assert_eq!(
            parse(Some("cuda"), Some("128")).unwrap(),
            Provider::Cuda {
                memory_limit: 128 * 1024 * 1024
            }
        );
        assert_eq!(
            parse(Some("cuda"), Some("1")).unwrap(),
            Provider::Cuda {
                memory_limit: 1024 * 1024
            }
        );
        #[cfg(target_pointer_width = "64")]
        assert!(parse(Some("cuda"), Some("16384")).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn non_unicode_configuration_is_rejected() {
        use std::os::unix::ffi::OsStrExt;
        let invalid = OsStr::from_bytes(b"\xff");
        assert!(Provider::parse(Some(invalid), None).is_err());
        assert!(Provider::parse(Some(OsStr::new("cuda")), Some(invalid)).is_err());
    }
}
