use crate::{json, CatalogError};
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
    "__init__.py",
    "catalog.py",
    "common.py",
    "paths.py",
    "tensors.py",
];
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub path: PathBuf,
    pub sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LaunchConfig {
    pub schema_version: u32,
    pub python: FilePin,
    pub bootstrap: FilePin,
    pub catalog_src: PathBuf,
    pub working_directory: PathBuf,
    pub root_grants: Vec<PathBuf>,
    pub sources: BTreeMap<String, String>,
    pub work_timeout_ms: u64,
    pub cleanup_timeout_ms: u64,
}
pub(crate) struct Verified {
    pub spec: WorkerSpec,
    pub grants: Vec<PathBuf>,
}
pub(crate) fn load(path: &Path) -> Result<LaunchConfig, CatalogError> {
    checked_path(path, false)?;
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| CatalogError::config())?
        .take(65537)
        .read_to_end(&mut bytes)
        .map_err(|_| CatalogError::config())?;
    if bytes.len() > 65536 {
        return Err(CatalogError::config());
    }
    let config: LaunchConfig =
        serde_json::from_value(json::decode(&bytes).map_err(|_| CatalogError::config())?)
            .map_err(|_| CatalogError::config())?;
    verify(&config)?;
    Ok(config)
}
pub(crate) fn verify(config: &LaunchConfig) -> Result<Verified, CatalogError> {
    if config.schema_version != 1
        || !(50..=30000).contains(&config.work_timeout_ms)
        || !(50..=5000).contains(&config.cleanup_timeout_ms)
        || config.root_grants.is_empty()
        || config.root_grants.len() > 8
        || config.sources.len() != SOURCE_FILES.len()
        || SOURCE_FILES
            .iter()
            .any(|key| !config.sources.contains_key(*key))
    {
        return Err(CatalogError::config());
    }
    let python = verify_file(&config.python.path, &config.python.sha256, 64 * 1024 * 1024)?;
    if !python
        .extension()
        .is_some_and(|s| s.eq_ignore_ascii_case("exe"))
    {
        return Err(CatalogError::config());
    }
    let bootstrap = verify_file(&config.bootstrap.path, &config.bootstrap.sha256, 1048576)?;
    if bootstrap.file_name().is_none_or(|s| s != "bootstrap.py") {
        return Err(CatalogError::config());
    }
    let source = checked_path(&config.catalog_src, true)?;
    let cwd = checked_path(&config.working_directory, true)?;
    let own = bootstrap.parent().ok_or_else(CatalogError::config)?;
    if cwd.starts_with(&source)
        || source.starts_with(&cwd)
        || cwd.starts_with(own)
        || own.starts_with(&cwd)
    {
        return Err(CatalogError::config());
    }
    if std::fs::read_dir(&cwd)
        .map_err(|_| CatalogError::config())?
        .next()
        .is_some()
    {
        return Err(CatalogError::config());
    }
    for (name, digest) in &config.sources {
        verify_file(
            &source.join("hermes_model_catalog").join(name),
            digest,
            1048576,
        )?;
    }
    let mut grants = Vec::new();
    for path in &config.root_grants {
        let grant = checked_path(path, true)?;
        if grants.contains(&grant) || grant.starts_with(&cwd) || cwd.starts_with(&grant) {
            return Err(CatalogError::config());
        }
        grants.push(grant);
    }
    let mut buffer = [0u16; 32768];
    let count = unsafe { GetWindowsDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) } as usize;
    if count == 0 || count >= buffer.len() {
        return Err(CatalogError::config());
    }
    let windows =
        OsString::from(String::from_utf16(&buffer[..count]).map_err(|_| CatalogError::config())?);
    Ok(Verified {
        grants,
        spec: WorkerSpec {
            executable: python,
            working_directory: cwd,
            environment: BTreeMap::from([
                ("SYSTEMROOT".into(), windows.clone()),
                ("WINDIR".into(), windows),
            ]),
            arguments: vec![
                "-I".into(),
                "-S".into(),
                "-B".into(),
                "-X".into(),
                "utf8".into(),
                bootstrap.into_os_string(),
                "--catalog-src".into(),
                source.into_os_string(),
                "--source-pins".into(),
                serde_json::to_string(&config.sources)
                    .map_err(|_| CatalogError::config())?
                    .into(),
            ],
        },
    })
}
pub(crate) fn select_model(verified: &mut Verified, raw: &str) -> Result<String, CatalogError> {
    let requested = Path::new(raw);
    if raw.len() > 32760
        || !requested.is_absolute()
        || !matches!(requested.components().next(),Some(Component::Prefix(p)) if matches!(p.kind(),Prefix::Disk(_)))
        || requested
            .components()
            .any(|p| matches!(p, Component::ParentDir | Component::CurDir))
    {
        return Err(CatalogError::invalid());
    }
    if !requested
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(crate::protocol::basename)
    {
        return Err(CatalogError::invalid());
    }
    let lexical_parent = requested.parent().ok_or_else(CatalogError::invalid)?;
    let granted = verified
        .grants
        .iter()
        .find(|grant| {
            ordinary_root(grant).is_ok_and(|ordinary| {
                ordinary
                    .to_string_lossy()
                    .eq_ignore_ascii_case(&lexical_parent.to_string_lossy())
            })
        })
        .ok_or_else(CatalogError::outside)?;
    let path = checked_path(requested, true).map_err(|_| CatalogError::invalid())?;
    let parent = path.parent().ok_or_else(CatalogError::invalid)?;
    if parent != granted {
        return Err(CatalogError::outside());
    }
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or_else(CatalogError::invalid)?;
    if !crate::protocol::basename(name) {
        return Err(CatalogError::invalid());
    }
    verified.spec.arguments.extend([
        "--root".into(),
        ordinary_root(parent)?.into_os_string(),
        format!("--model={name}").into(),
    ]);
    Ok(name.to_owned())
}
pub(crate) fn work(config: &LaunchConfig) -> Duration {
    Duration::from_millis(config.work_timeout_ms)
}
pub(crate) fn cleanup(config: &LaunchConfig) -> Duration {
    Duration::from_millis(config.cleanup_timeout_ms)
}
pub(crate) fn checked_path(path: &Path, directory: bool) -> Result<PathBuf, CatalogError> {
    if !path.is_absolute()
        || !matches!(path.components().next(), Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)))
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err(CatalogError::config());
    }
    let drive = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
            _ => return Err(CatalogError::config()),
        },
        _ => return Err(CatalogError::config()),
    };
    let drive_root = [u16::from(drive), b':' as u16, b'\\' as u16, 0];
    // Reject mapped network/unknown/CD-ROM roots before filesystem traversal.
    // DRIVE_REMOVABLE=2 and DRIVE_FIXED=3 are local storage categories.
    if !matches!(unsafe { GetDriveTypeW(drive_root.as_ptr()) }, 2 | 3) {
        return Err(CatalogError::config());
    }
    for part in path.ancestors().collect::<Vec<_>>().into_iter().rev() {
        let metadata = std::fs::symlink_metadata(part).map_err(|_| CatalogError::config())?;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(CatalogError::config());
        }
    }
    let metadata = std::fs::metadata(path).map_err(|_| CatalogError::config())?;
    if directory != metadata.is_dir() || (!directory && !metadata.is_file()) {
        return Err(CatalogError::config());
    }
    path.canonicalize().map_err(|_| CatalogError::config())
}

fn verify_file(path: &Path, expected: &str, limit: u64) -> Result<PathBuf, CatalogError> {
    if expected.len() != 64
        || !expected
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CatalogError::config());
    }
    let path = checked_path(path, false)?;
    let mut input = File::open(&path)
        .map_err(|_| CatalogError::config())?
        .take(limit + 1);
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 16_384];
    let mut total = 0;
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|_| CatalogError::config())?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > limit {
            return Err(CatalogError::config());
        }
        hasher.update(&buffer[..count]);
    }
    if format!("{:x}", hasher.finalize()) != expected {
        return Err(CatalogError::config());
    }
    Ok(path)
}

fn ordinary_root(path: &Path) -> Result<PathBuf, CatalogError> {
    let mut parts = path.components();
    let drive = match parts.next() {
        Some(Component::Prefix(p)) => match p.kind() {
            Prefix::VerbatimDisk(d) | Prefix::Disk(d) => d,
            _ => return Err(CatalogError::config()),
        },
        _ => return Err(CatalogError::config()),
    };
    let mut ordinary = PathBuf::from(format!("{}:\\", drive as char));
    for part in parts {
        match part {
            Component::RootDir => {}
            Component::Normal(name) => {
                let text = name.to_str().ok_or_else(CatalogError::config)?;
                if !crate::protocol::basename(text) {
                    return Err(CatalogError::config());
                }
                ordinary.push(name);
            }
            _ => return Err(CatalogError::config()),
        }
    }
    if checked_path(&ordinary, true)? != path {
        return Err(CatalogError::config());
    }
    Ok(ordinary)
}
