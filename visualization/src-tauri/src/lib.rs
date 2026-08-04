use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(serde::Serialize, Clone, Debug)]
pub struct BackendConnection {
    pub host: String,
    pub port: u16,
    pub token: String,
    pub protocol_version: i64,
    pub instance_id: String,
    pub project_identity: String,
    pub project_root: String,
}

#[derive(Deserialize, Debug)]
struct InstanceRecord {
    schema_version: i64,
    instance_id: String,
    project_root: String,
    project_identity: String,
    host: String,
    port: u16,
    token: String,
    protocol_version: i64,
}

#[tauri::command]
fn discover_backend(project_root: String) -> Result<Option<BackendConnection>, String> {
    let root = fs::canonicalize(Path::new(&project_root))
        .map_err(|error| format!("Project root cannot be resolved: {error}"))?;
    let identity = project_identity(&root);
    let record_path = instance_directory()?.join(format!("{identity}.json"));
    let text = match fs::read_to_string(&record_path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(format!(
                "TinySoul connection record cannot be read: {error}"
            ))
        }
    };
    let record: InstanceRecord = serde_json::from_str(&text)
        .map_err(|error| format!("TinySoul connection record is invalid: {error}"))?;
    if record.schema_version != 1
        || record.project_identity != identity
        || record.host != "127.0.0.1"
        || record.port == 0
        || record.token.len() < 32
        || record.instance_id.is_empty()
    {
        return Ok(None);
    }
    Ok(Some(BackendConnection {
        host: record.host,
        port: record.port,
        token: record.token,
        protocol_version: record.protocol_version,
        instance_id: record.instance_id,
        project_identity: record.project_identity,
        project_root: record.project_root,
    }))
}

fn project_identity(root: &Path) -> String {
    let mut value = root.to_string_lossy().to_string();
    if cfg!(windows) {
        value = value
            .strip_prefix(r"\\?\")
            .unwrap_or(&value)
            .replace('/', "\\")
            .to_lowercase();
    }
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn instance_directory() -> Result<PathBuf, String> {
    if let Some(value) = env::var_os("TINYSOUL_INSTANCE_DIR") {
        return Ok(PathBuf::from(value));
    }
    if cfg!(windows) {
        if let Some(value) = env::var_os("LOCALAPPDATA") {
            return Ok(PathBuf::from(value).join("TinySoul").join("instances"));
        }
    }
    if let Some(value) = env::var_os("XDG_RUNTIME_DIR") {
        return Ok(PathBuf::from(value).join("tinysoul").join("instances"));
    }
    let home = env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "Current user home directory is unavailable".to_string())?;
    if cfg!(target_os = "macos") {
        return Ok(home
            .join("Library")
            .join("Application Support")
            .join("TinySoul")
            .join("instances"));
    }
    Ok(home
        .join(".local")
        .join("state")
        .join("tinysoul")
        .join("instances"))
}

#[derive(Deserialize, Debug)]
struct ExportFileInput {
    path: String,
    contents: String,
}

/// Write the turn trace export bundle under a user-picked directory.
/// Every path must stay relative to `base_dir`; returns the export root.
#[tauri::command]
fn write_export_files(base_dir: String, files: Vec<ExportFileInput>) -> Result<String, String> {
    let base = Path::new(&base_dir);
    if !base.is_dir() {
        return Err("The chosen export directory does not exist".to_string());
    }
    for file in &files {
        let relative = Path::new(&file.path);
        if relative.is_absolute()
            || relative
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err(format!("Invalid export path: {}", file.path));
        }
        let target = base.join(relative);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Cannot create export directory: {e}"))?;
        }
        fs::write(&target, &file.contents)
            .map_err(|e| format!("Cannot write {}: {e}", target.display()))?;
    }
    // The bundle root is the first path component shared by all files.
    let root = files
        .first()
        .and_then(|f| Path::new(&f.path).components().next())
        .map(|c| base.join(c.as_os_str()))
        .unwrap_or_else(|| base.to_path_buf());
    Ok(root.to_string_lossy().to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            discover_backend,
            write_export_files
        ])
        .run(tauri::generate_context!())
        .expect("error while running TinySoul visualization");
}
