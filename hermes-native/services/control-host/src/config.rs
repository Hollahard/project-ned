use crate::{json, ControlError};
use hermes_resource_host::WorkerSpec;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::File;
use std::io::Read;
use std::os::windows::fs::MetadataExt;
use std::path::{Component, Path, PathBuf, Prefix};
use std::time::Duration;
use windows_sys::Win32::Storage::FileSystem::GetDriveTypeW;
use windows_sys::Win32::System::SystemInformation::GetWindowsDirectoryW;

pub const SOURCE_FILES: &[&str] = &[
    "worker/__init__.py",
    "worker/errors.py",
    "worker/profiles.py",
    "worker/state.py",
    "worker/protocol.py",
    "inference/__init__.py",
    "inference/admission.py",
    "inference/errors.py",
    "inference/profiles.py",
];

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub path: PathBuf,
    pub sha256: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LaunchConfig {
    pub schema_version: u32,
    pub python: FilePin,
    pub bootstrap: FilePin,
    pub inference_src: PathBuf,
    pub state_dir: PathBuf,
    pub sources: BTreeMap<String, String>,
    pub startup_timeout_ms: u64,
    pub request_timeout_ms: u64,
    pub shutdown_timeout_ms: u64,
}

pub(crate) struct VerifiedConfig {
    pub spec: WorkerSpec,
    pub startup: Duration,
    pub request: Duration,
    pub shutdown: Duration,
}

pub(crate) fn load(path: &Path) -> Result<VerifiedConfig, ControlError> {
    checked_path(path, false)?;
    let file = File::open(path).map_err(|_| ControlError::config())?;
    let mut bytes = Vec::new();
    file.take(65_537)
        .read_to_end(&mut bytes)
        .map_err(|_| ControlError::config())?;
    if bytes.len() > 65_536 {
        return Err(ControlError::config());
    }
    let config: LaunchConfig =
        serde_json::from_value(json::decode(&bytes).map_err(|_| ControlError::config())?)
            .map_err(|_| ControlError::config())?;
    verify(config)
}

fn verify(config: LaunchConfig) -> Result<VerifiedConfig, ControlError> {
    if config.schema_version != 1
        || !(50..=30_000).contains(&config.startup_timeout_ms)
        || !(50..=30_000).contains(&config.request_timeout_ms)
        || !(50..=10_000).contains(&config.shutdown_timeout_ms)
        || config.sources.len() != SOURCE_FILES.len()
        || SOURCE_FILES
            .iter()
            .any(|name| !config.sources.contains_key(*name))
    {
        return Err(ControlError::config());
    }
    let python = verify_file(&config.python.path, &config.python.sha256, 64 * 1024 * 1024)?;
    if !python
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("exe"))
    {
        return Err(ControlError::config());
    }
    let bootstrap = verify_file(&config.bootstrap.path, &config.bootstrap.sha256, 1_048_576)?;
    if bootstrap
        .file_name()
        .is_none_or(|name| name != "bootstrap.py")
    {
        return Err(ControlError::config());
    }
    let worker_root = bootstrap.parent().ok_or_else(ControlError::config)?;
    let inference = checked_path(&config.inference_src, true)?;
    let state = checked_path(&config.state_dir, true)?;
    if state.starts_with(worker_root)
        || worker_root.starts_with(&state)
        || state.starts_with(&inference)
        || inference.starts_with(&state)
    {
        return Err(ControlError::config());
    }
    for entry in std::fs::read_dir(&state).map_err(|_| ControlError::config())? {
        let entry = entry.map_err(|_| ControlError::config())?;
        let name = entry.file_name();
        if ![
            "profiles.sqlite3",
            "profiles.sqlite3-journal",
            ".worker.lock",
        ]
        .iter()
        .any(|allowed| name == *allowed)
        {
            return Err(ControlError::config());
        }
        checked_path(&entry.path(), false)?;
    }
    for (relative, digest) in &config.sources {
        let (package, filename) = relative.split_once('/').ok_or_else(ControlError::config)?;
        let path = if package == "worker" {
            worker_root.join("src/hermes_control_worker").join(filename)
        } else {
            inference.join("hermes_inference").join(filename)
        };
        verify_file(&path, digest, 1_048_576)?;
    }
    let mut buffer = [0u16; 32_768];
    let count = unsafe { GetWindowsDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) } as usize;
    if count == 0 || count >= buffer.len() {
        return Err(ControlError::config());
    }
    let windows =
        OsString::from(String::from_utf16(&buffer[..count]).map_err(|_| ControlError::config())?);
    let environment = BTreeMap::from([
        ("SYSTEMROOT".into(), windows.clone()),
        ("WINDIR".into(), windows),
        ("TEMP".into(), state.clone().into_os_string()),
        ("TMP".into(), state.clone().into_os_string()),
        ("HOME".into(), state.clone().into_os_string()),
        ("USERPROFILE".into(), state.clone().into_os_string()),
    ]);
    Ok(VerifiedConfig {
        spec: WorkerSpec {
            executable: python,
            working_directory: state.clone(),
            environment,
            arguments: vec![
                "-I".into(),
                "-S".into(),
                "-B".into(),
                "-X".into(),
                "utf8".into(),
                bootstrap.into_os_string(),
                "--inference-src".into(),
                inference.into_os_string(),
                "--state-dir".into(),
                state.into_os_string(),
            ],
        },
        startup: Duration::from_millis(config.startup_timeout_ms),
        request: Duration::from_millis(config.request_timeout_ms),
        shutdown: Duration::from_millis(config.shutdown_timeout_ms),
    })
}

fn checked_path(path: &Path, directory: bool) -> Result<PathBuf, ControlError> {
    if !path.is_absolute()
        || !matches!(path.components().next(), Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)))
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err(ControlError::config());
    }
    let drive = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
            _ => return Err(ControlError::config()),
        },
        _ => return Err(ControlError::config()),
    };
    let drive_root = [u16::from(drive), b':' as u16, b'\\' as u16, 0];
    // Reject mapped network/unknown/CD-ROM roots before filesystem traversal.
    // DRIVE_REMOVABLE=2 and DRIVE_FIXED=3 are local storage categories.
    if !matches!(unsafe { GetDriveTypeW(drive_root.as_ptr()) }, 2 | 3) {
        return Err(ControlError::config());
    }
    for part in path.ancestors() {
        let metadata = std::fs::symlink_metadata(part).map_err(|_| ControlError::config())?;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(ControlError::config());
        }
    }
    let metadata = std::fs::metadata(path).map_err(|_| ControlError::config())?;
    if directory != metadata.is_dir() || (!directory && !metadata.is_file()) {
        return Err(ControlError::config());
    }
    path.canonicalize().map_err(|_| ControlError::config())
}

fn verify_file(path: &Path, expected: &str, limit: u64) -> Result<PathBuf, ControlError> {
    if expected.len() != 64
        || !expected
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ControlError::config());
    }
    let path = checked_path(path, false)?;
    let mut input = File::open(&path)
        .map_err(|_| ControlError::config())?
        .take(limit + 1);
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 16_384];
    let mut total = 0;
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|_| ControlError::config())?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > limit {
            return Err(ControlError::config());
        }
        hasher.update(&buffer[..count]);
    }
    if format!("{:x}", hasher.finalize()) != expected {
        return Err(ControlError::config());
    }
    Ok(path)
}
