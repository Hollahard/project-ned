use crate::{Kind, WatchError};
use std::ffi::OsString;
use std::fs::{self, Metadata};
use std::io;
use std::path::{Component, Path, PathBuf};
use std::time::SystemTime;

/// Construct only from native host decisions (verified source/picker roots), not
/// raw renderer requests or untrusted backend advertisements. Roots grant local
/// metadata observation below these directories; they never grant file reads.
/// Empty grants deliberately disable registration while allowing subscriptions.
#[derive(Debug)]
pub struct TrustedRoots {
    roots: Vec<PathBuf>,
}

impl TrustedRoots {
    pub fn from_host_paths(paths: impl IntoIterator<Item = PathBuf>) -> Result<Self, WatchError> {
        let mut roots = Vec::new();
        for path in paths {
            if roots.len() >= 16 {
                return Err(WatchError::LimitExceeded);
            }
            validate_syntax(&path)?;
            require_fixed_drive(&path)?;
            reject_sensitive(&path)?;
            reject_reparse_components(&path)?;
            let canonical = fs::canonicalize(&path).map_err(io_error)?;
            if canonical.parent().is_none() || !canonical.is_dir() {
                return Err(WatchError::WrongKind);
            }
            if !roots.contains(&canonical) {
                roots.push(canonical);
            }
        }
        Ok(Self { roots })
    }

    pub(crate) fn resolve(&self, raw: &str) -> Result<PathBuf, WatchError> {
        if raw.is_empty() || raw.len() > 32767 || raw.contains('\0') || raw.trim() != raw {
            return Err(WatchError::InvalidPath);
        }
        let path = if raw.to_ascii_lowercase().starts_with("file:") {
            let url = url::Url::parse(raw).map_err(|_| WatchError::InvalidPath)?;
            if url.scheme() != "file"
                || url
                    .host_str()
                    .is_some_and(|host| !host.is_empty() && host != "localhost")
                || !url.username().is_empty()
                || url.password().is_some()
                || url.query().is_some()
                || url.fragment().is_some()
            {
                return Err(WatchError::InvalidPath);
            }
            url.to_file_path().map_err(|_| WatchError::InvalidPath)?
        } else {
            PathBuf::from(raw)
        };
        validate_syntax(&path)?;
        reject_sensitive(&path)?;
        // Check lexical grant before any filesystem access so an arbitrary
        // renderer path cannot become an existence probe outside granted roots.
        let lexical = canonical_style(&path)?;
        if !self.roots.iter().any(|root| lexical.starts_with(root)) {
            return Err(WatchError::PathDenied);
        }
        self.validate_current(&lexical)?;
        let canonical = fs::canonicalize(&lexical).map_err(io_error)?;
        if !self.roots.iter().any(|root| canonical.starts_with(root)) {
            return Err(WatchError::PathDenied);
        }
        Ok(canonical)
    }

    fn validate_current(&self, path: &Path) -> Result<(), WatchError> {
        if !self.roots.iter().any(|root| path.starts_with(root)) {
            return Err(WatchError::PathDenied);
        }
        reject_sensitive(path)?;
        require_fixed_drive(path)?;
        // The path is validated each scan, including its entire ancestry. A
        // replacement junction/symlink is never followed intentionally.
        reject_reparse_components(path)
    }

    pub(crate) fn snapshot(
        &self,
        path: &Path,
        kind: Kind,
        entry_limit: usize,
    ) -> Result<Snapshot, WatchError> {
        match self.validate_current(path) {
            Ok(()) => {}
            Err(WatchError::Missing) => return Ok(Snapshot::Missing),
            Err(error) => return Err(error),
        }
        let metadata = match fs::symlink_metadata(path) {
            Ok(value) => value,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Snapshot::Missing),
            Err(error) => return Err(io_error(error)),
        };
        if is_reparse(&metadata) {
            return Err(WatchError::ReparsePoint);
        }
        match kind {
            Kind::File if metadata.is_file() => Ok(Snapshot::File(stamp(&metadata))),
            Kind::Directory if metadata.is_dir() => {
                let mut entries = Vec::new();
                for (index, entry) in fs::read_dir(path).map_err(io_error)?.enumerate() {
                    // Count excluded entries too, so filtering cannot bypass the
                    // scan bound. Never recurse or inspect secret child metadata.
                    if index >= entry_limit {
                        return Err(WatchError::LimitExceeded);
                    }
                    let entry = entry.map_err(io_error)?;
                    let child = entry.path();
                    if reject_sensitive(&child).is_err() {
                        continue;
                    }
                    let metadata = match fs::symlink_metadata(&child) {
                        Ok(value) => value,
                        Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
                        Err(error) => return Err(io_error(error)),
                    };
                    if is_reparse(&metadata) {
                        continue;
                    }
                    entries.push((entry.file_name(), metadata.is_dir(), stamp(&metadata)));
                }
                entries.sort_by(|left, right| left.0.cmp(&right.0));
                // No root mtime: secret/excluded entry churn does not trigger a
                // visible event merely by changing the directory's own metadata.
                Ok(Snapshot::Directory(entries))
            }
            _ => Err(WatchError::WrongKind),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum Snapshot {
    Missing,
    File(Stamp),
    Directory(Vec<(OsString, bool, Stamp)>),
}

impl Snapshot {
    pub(crate) fn is_missing(&self) -> bool {
        matches!(self, Self::Missing)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Stamp {
    len: u64,
    modified: Option<SystemTime>,
    created: Option<SystemTime>,
}

fn stamp(metadata: &Metadata) -> Stamp {
    Stamp {
        len: metadata.len(),
        modified: metadata.modified().ok(),
        created: metadata.created().ok(),
    }
}

fn validate_syntax(path: &Path) -> Result<(), WatchError> {
    if !path.is_absolute() {
        return Err(WatchError::InvalidPath);
    }
    let text = path.to_str().ok_or(WatchError::InvalidPath)?;
    if text.len() > 32767 || text.contains('\0') {
        return Err(WatchError::InvalidPath);
    }
    #[cfg(windows)]
    {
        use std::path::Prefix;
        if !matches!(path.components().next(), Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_)))
        {
            return Err(WatchError::InvalidPath);
        }
    }
    for component in path.components() {
        match component {
            Component::ParentDir | Component::CurDir => return Err(WatchError::InvalidPath),
            Component::Normal(name) => {
                let name = name.to_str().ok_or(WatchError::InvalidPath)?;
                // Windows ADS, ambiguous Win32 normalization and wildcard/device
                // spellings are outside this local preview capability.
                if name.contains([':', '*', '?']) || name.ends_with(['.', ' ']) {
                    return Err(WatchError::InvalidPath);
                }
                #[cfg(windows)]
                {
                    let stem = name.split('.').next().unwrap_or("").to_ascii_uppercase();
                    if matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
                        || (stem.len() == 4
                            && (stem.starts_with("COM") || stem.starts_with("LPT"))
                            && matches!(stem.as_bytes()[3], b'1'..=b'9'))
                    {
                        return Err(WatchError::InvalidPath);
                    }
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn canonical_style(path: &Path) -> Result<PathBuf, WatchError> {
    #[cfg(windows)]
    {
        // Input syntax is already an ordinary absolute drive path. Adding the
        // verbatim disk prefix lets lexical grant checks match canonical roots
        // without following or probing a user-selected path first.
        Ok(PathBuf::from(format!(
            "\\\\?\\{}",
            path.to_str().ok_or(WatchError::InvalidPath)?
        )))
    }
    #[cfg(not(windows))]
    {
        Ok(path.to_path_buf())
    }
}

fn require_fixed_drive(path: &Path) -> Result<(), WatchError> {
    #[cfg(windows)]
    {
        use std::path::Prefix;
        use windows_sys::Win32::Storage::FileSystem::GetDriveTypeW;
        let drive = match path.components().next() {
            Some(Component::Prefix(prefix)) => match prefix.kind() {
                Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
                _ => return Err(WatchError::InvalidPath),
            },
            _ => return Err(WatchError::InvalidPath),
        };
        let root = [u16::from(drive), b':' as u16, b'\\' as u16, 0];
        // SAFETY: root is a live, NUL-terminated UTF-16 drive-root buffer.
        // DRIVE_FIXED = 3. Reject mapped network, removable, unknown and RAM
        // drives; polling offers no cancellation of a blocked OS metadata call.
        if unsafe { GetDriveTypeW(root.as_ptr()) } != 3 {
            return Err(WatchError::PathDenied);
        }
    }
    #[cfg(not(windows))]
    let _ = path;
    Ok(())
}

pub(crate) fn display_path(path: &Path) -> Result<String, WatchError> {
    let text = path.to_str().ok_or(WatchError::InvalidPath)?;
    Ok(text.strip_prefix("\\\\?\\").unwrap_or(text).to_owned())
}

fn reject_reparse_components(path: &Path) -> Result<(), WatchError> {
    let mut ancestors: Vec<_> = path.ancestors().collect();
    ancestors.reverse();
    for ancestor in ancestors {
        let metadata = fs::symlink_metadata(ancestor).map_err(io_error)?;
        if is_reparse(&metadata) {
            return Err(WatchError::ReparsePoint);
        }
    }
    Ok(())
}

fn is_reparse(metadata: &Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

fn reject_sensitive(path: &Path) -> Result<(), WatchError> {
    let parts: Vec<String> = path
        .components()
        .filter_map(|part| match part {
            Component::Normal(name) => Some(name.to_string_lossy().to_ascii_lowercase()),
            _ => None,
        })
        .collect();
    if parts
        .iter()
        .any(|part| matches!(part.as_str(), ".ssh" | ".gnupg" | ".aws"))
    {
        return Err(WatchError::SensitivePath);
    }
    let Some(name) = parts.last() else {
        return Ok(());
    };
    if name == ".env"
        || name
            .strip_prefix(".env.")
            .is_some_and(|suffix| !matches!(suffix, "dist" | "example" | "sample" | "template"))
        || matches!(name.as_str(), ".npmrc" | ".netrc" | ".pypirc")
        || [".kdbx", ".p12", ".pem", ".pfx"]
            .iter()
            .any(|extension| name.ends_with(extension))
        || (["id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"]
            .iter()
            .any(|prefix| name == prefix || name.starts_with(&format!("{prefix}.")))
            && !name.ends_with(".pub"))
    {
        return Err(WatchError::SensitivePath);
    }
    Ok(())
}

fn io_error(error: io::Error) -> WatchError {
    if matches!(
        error.kind(),
        io::ErrorKind::NotFound | io::ErrorKind::NotADirectory
    ) {
        WatchError::Missing
    } else {
        WatchError::Io
    }
}
