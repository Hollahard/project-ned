use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::Read;
use std::os::windows::fs::MetadataExt;
use std::path::{Component, Path, PathBuf, Prefix};
use windows_sys::Win32::Storage::FileSystem::GetDriveTypeW;

pub type ProofResult<T> = Result<T, &'static str>;
pub const UPSTREAM: &str = "649d6c0391029f35959cfbc240eb3534a6667cf5";
pub const BACKEND_FILES: &[&str] = &[
    "diagnostics/bootstrap.py",
    "src/hermes_backend_host/__init__.py",
    "src/hermes_backend_host/readiness.py",
    "src/hermes_backend_host/diagnostic_source.py",
    "src/hermes_backend_host/diagnostic_policy.py",
];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema_version: u32,
    python: FilePin,
    helper_source_root: PathBuf,
    backend_root: PathBuf,
    backend_files: BTreeMap<String, String>,
    candidate: PathBuf,
    candidate_manifest_sha256: String,
    site_packages: PathBuf,
}

pub struct Prepared {
    pub python: PathBuf,
    pub backend_root: PathBuf,
    pub helper_source_root: PathBuf,
    pub candidate: PathBuf,
    pub manifest_hash: String,
    pub source_file_count: usize,
    pub policy_hash: String,
    pub site_packages: PathBuf,
    pub state: PathBuf,
    pub report: PathBuf,
    config_file: PathBuf,
    config_hash: String,
}

impl Prepared {
    pub fn load(path: &Path) -> ProofResult<Self> {
        let path = checked(path, false)?;
        let bytes = read_bounded(&path, 65_536)?;
        let config: Config = serde_json::from_slice(&bytes).map_err(|_| "CONFIG_INVALID")?;
        if config.schema_version != 1
            || config.backend_files.len() != BACKEND_FILES.len()
            || BACKEND_FILES
                .iter()
                .any(|name| !config.backend_files.contains_key(*name))
        {
            return Err("CONFIG_INVALID");
        }
        let python = verify_file(&config.python.path, &config.python.sha256, 64 * 1024 * 1024)?;
        if !python
            .extension()
            .is_some_and(|name| name.eq_ignore_ascii_case("exe"))
        {
            return Err("CONFIG_INVALID");
        }
        let backend_root = checked(&config.backend_root, true)?;
        let helper_source_root = checked(&config.helper_source_root, true)?;
        verify_helper_tree(&backend_root)?;
        for (name, digest) in &config.backend_files {
            verify_file(&backend_root.join(name), digest, 2 * 1024 * 1024)?;
            verify_file(&helper_source_root.join(name), digest, 2 * 1024 * 1024)?;
        }
        let candidate = checked(&config.candidate, true)?;
        let site_packages = checked(&config.site_packages, true)?;
        let manifest = candidate.join("source-manifest.json");
        verify_file(
            &manifest,
            &config.candidate_manifest_sha256,
            2 * 1024 * 1024,
        )?;
        let source_file_count = verify_candidate(&candidate)?;
        let output = path.parent().ok_or("CONFIG_INVALID")?;
        for input in [
            &backend_root,
            &helper_source_root,
            &candidate,
            &site_packages,
        ] {
            if output.starts_with(input) || input.starts_with(output) {
                return Err("STATE_OVERLAPS_INPUT");
            }
        }
        let state = output.join("state");
        let report = output.join("result.json");
        if state.exists() || report.exists() {
            return Err("STATE_ALREADY_USED");
        }
        Ok(Self {
            python,
            backend_root,
            helper_source_root,
            candidate,
            manifest_hash: config.candidate_manifest_sha256,
            source_file_count,
            policy_hash: config
                .backend_files
                .get("src/hermes_backend_host/diagnostic_policy.py")
                .ok_or("CONFIG_INVALID")?
                .clone(),
            site_packages,
            state,
            report,
            config_file: path,
            config_hash: digest(&bytes),
        })
    }

    pub fn verify_unchanged(&self) -> ProofResult<()> {
        verify_file(&self.config_file, &self.config_hash, 65_536)?;
        let config: Config = serde_json::from_slice(&read_bounded(&self.config_file, 65_536)?)
            .map_err(|_| "CONFIG_INVALID")?;
        verify_helper_tree(&self.backend_root)?;
        verify_file(&config.python.path, &config.python.sha256, 64 * 1024 * 1024)?;
        for (name, expected) in &config.backend_files {
            verify_file(&self.backend_root.join(name), expected, 2 * 1024 * 1024)?;
            verify_file(
                &self.helper_source_root.join(name),
                expected,
                2 * 1024 * 1024,
            )?;
        }
        verify_file(
            &self.candidate.join("source-manifest.json"),
            &self.manifest_hash,
            2 * 1024 * 1024,
        )?;
        verify_candidate(&self.candidate).map(|_| ())
    }
}

fn verify_candidate(candidate: &Path) -> ProofResult<usize> {
    let manifest: serde_json::Value = serde_json::from_slice(&read_bounded(
        &candidate.join("source-manifest.json"),
        2 * 1024 * 1024,
    )?)
    .map_err(|_| "CANDIDATE_INVALID")?;
    if manifest["upstream_commit"] != UPSTREAM
        || manifest["mode"] != "diagnostic-http-subset-v1"
        || manifest["retained_handlers"]
            != serde_json::json!([
                "hermes_cli.web_routers.config_env.get_config",
                "hermes_cli.web_routers.sessions.get_sessions"
            ])
    {
        return Err("CANDIDATE_INVALID");
    }
    let files = manifest["source_files"]
        .as_object()
        .ok_or("CANDIDATE_INVALID")?;
    if files.is_empty() || files.len() > 10_000 {
        return Err("CANDIDATE_INVALID");
    }
    let source = checked(&candidate.join("source"), true)?;
    if source_tree(&source, true)? != files.keys().cloned().collect() {
        return Err("CANDIDATE_FILE_SET_CHANGED");
    }
    for (name, expected) in files {
        let relative = Path::new(name);
        if relative.is_absolute()
            || relative
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
        {
            return Err("CANDIDATE_INVALID");
        }
        verify_file(
            &source.join(relative),
            expected.as_str().ok_or("CANDIDATE_INVALID")?,
            16 * 1024 * 1024,
        )?;
    }
    // The exported diagnostic bootstrap additionally reverses/hash-checks all four
    // audited patches before importing handlers. Source trees reject bytecode and
    // native import shadows; -B alone would not prevent loading an existing cache.
    Ok(files.len())
}

fn verify_helper_tree(root: &Path) -> ProofResult<()> {
    if source_tree(root, false)?
        != BACKEND_FILES
            .iter()
            .map(|name| (*name).to_owned())
            .collect()
    {
        return Err("HELPER_FILE_SET_CHANGED");
    }
    Ok(())
}

pub fn source_tree(root: &Path, python_only: bool) -> ProofResult<BTreeSet<String>> {
    let root = checked(root, true)?;
    let mut pending = vec![root.clone()];
    let mut files = BTreeSet::new();
    let mut entries = 0usize;
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory).map_err(|_| "SOURCE_TREE_INVALID")? {
            let entry = entry.map_err(|_| "SOURCE_TREE_INVALID")?;
            entries += 1;
            if entries > 16_384 {
                return Err("SOURCE_TREE_LIMIT");
            }
            let path = entry.path();
            let is_directory = entry
                .file_type()
                .map_err(|_| "SOURCE_TREE_INVALID")?
                .is_dir();
            let path = checked(&path, is_directory)?;
            if is_directory {
                if entry.file_name().eq_ignore_ascii_case("__pycache__") {
                    return Err("SOURCE_IMPORT_SHADOW");
                }
                pending.push(path);
            } else {
                let python = path
                    .extension()
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("py"));
                let documentation = path.extension().is_some_and(|extension| {
                    extension.eq_ignore_ascii_case("md") || extension.eq_ignore_ascii_case("txt")
                });
                if !python && (python_only || !documentation) {
                    return Err("SOURCE_IMPORT_SHADOW");
                }
                if !python {
                    continue;
                }
                files.insert(
                    path.strip_prefix(&root)
                        .map_err(|_| "SOURCE_TREE_INVALID")?
                        .to_str()
                        .ok_or("SOURCE_TREE_INVALID")?
                        .replace('\\', "/"),
                );
            }
        }
    }
    Ok(files)
}

pub fn checked(path: &Path, directory: bool) -> ProofResult<PathBuf> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err("PATH_INVALID");
    }
    let drive = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
            _ => return Err("PATH_INVALID"),
        },
        _ => return Err("PATH_INVALID"),
    };
    let root = [u16::from(drive), b':' as u16, b'\\' as u16, 0];
    if !matches!(unsafe { GetDriveTypeW(root.as_ptr()) }, 2 | 3) {
        return Err("PATH_INVALID");
    }
    for part in path.ancestors() {
        if std::fs::symlink_metadata(part)
            .map_err(|_| "PATH_INVALID")?
            .file_attributes()
            & 0x400
            != 0
        {
            return Err("PATH_INVALID");
        }
    }
    let metadata = std::fs::metadata(path).map_err(|_| "PATH_INVALID")?;
    if directory != metadata.is_dir() || (!directory && !metadata.is_file()) {
        return Err("PATH_INVALID");
    }
    path.canonicalize().map_err(|_| "PATH_INVALID")
}

pub fn read_bounded(path: &Path, limit: u64) -> ProofResult<Vec<u8>> {
    let mut result = Vec::new();
    File::open(path)
        .map_err(|_| "READ_FAILED")?
        .take(limit + 1)
        .read_to_end(&mut result)
        .map_err(|_| "READ_FAILED")?;
    if result.len() as u64 > limit {
        return Err("READ_TOO_LARGE");
    }
    Ok(result)
}

pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn verify_file(path: &Path, expected: &str, limit: u64) -> ProofResult<PathBuf> {
    if expected.len() != 64
        || !expected
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("HASH_INVALID");
    }
    let path = checked(path, false)?;
    if digest(&read_bounded(&path, limit)?) != expected {
        return Err("SOURCE_CHANGED");
    }
    Ok(path)
}
