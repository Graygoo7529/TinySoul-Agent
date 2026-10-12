use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

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

#[tauri::command]
fn write_export_archive(
    archive_path: String,
    files: Vec<ExportFileInput>,
) -> Result<String, String> {
    let archive = PathBuf::from(&archive_path);
    if archive.as_os_str().is_empty() {
        return Err("The export archive path is empty".to_string());
    }
    let parent = archive
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    if !parent.is_dir() {
        return Err("The chosen export location does not exist".to_string());
    }
    if files.is_empty() {
        return Err("The trace export has no files".to_string());
    }
    let mut paths = HashSet::new();
    for file in &files {
        let relative = Path::new(&file.path);
        if relative.as_os_str().is_empty()
            || relative.is_absolute()
            || relative
                .components()
                .any(|component| matches!(component, std::path::Component::ParentDir))
            || !paths.insert(file.path.replace('\\', "/"))
        {
            return Err(format!("Invalid or duplicate export path: {}", file.path));
        }
    }
    let file_name = archive
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("turn-trace.zip");
    let temporary = parent.join(format!(".{file_name}.tinysoul.tmp"));
    let result = (|| -> Result<(), String> {
        let handle = fs::File::create(&temporary)
            .map_err(|error| format!("Cannot create temporary export archive: {error}"))?;
        let mut writer = ZipWriter::new(handle);
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
        for file in &files {
            let path = file.path.replace('\\', "/");
            writer
                .start_file(path, options)
                .map_err(|error| format!("Cannot add export file: {error}"))?;
            writer
                .write_all(file.contents.as_bytes())
                .map_err(|error| format!("Cannot write export file: {error}"))?;
        }
        writer
            .finish()
            .map_err(|error| format!("Cannot finish export archive: {error}"))?;
        if archive.exists() {
            fs::remove_file(&archive)
                .map_err(|error| format!("Cannot replace existing export archive: {error}"))?;
        }
        fs::rename(&temporary, &archive)
            .map_err(|error| format!("Cannot finalize export archive: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result?;
    Ok(archive.to_string_lossy().to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            discover_backend,
            write_export_archive
        ])
        .run(tauri::generate_context!())
        .expect("error while running TinySoul visualization");
}

#[cfg(test)]
mod tests {
    use super::{write_export_archive, ExportFileInput};
    use std::fs;
    use std::io::Read;
    use std::time::{SystemTime, UNIX_EPOCH};
    use zip::ZipArchive;

    #[test]
    fn writes_a_valid_archive_and_rejects_escape_paths() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock before unix epoch")
            .as_nanos();
        let directory = std::env::temp_dir().join(format!("tinysoul-trace-export-{stamp}"));
        fs::create_dir_all(&directory).expect("create test directory");
        let archive = directory.join("trace.zip");
        let files = vec![ExportFileInput {
            path: "trace/manifest.json".to_string(),
            contents: "{\"ok\":true}".to_string(),
        }];
        let result = write_export_archive(archive.to_string_lossy().to_string(), files);
        assert!(result.is_ok());

        let bytes = fs::read(&archive).expect("read test archive");
        let mut reader = ZipArchive::new(std::io::Cursor::new(bytes)).expect("open test archive");
        let mut manifest = String::new();
        reader
            .by_name("trace/manifest.json")
            .expect("manifest entry")
            .read_to_string(&mut manifest)
            .expect("read manifest entry");
        assert_eq!(manifest, "{\"ok\":true}");

        let rejected = write_export_archive(
            directory.join("rejected.zip").to_string_lossy().to_string(),
            vec![ExportFileInput {
                path: "../outside.json".to_string(),
                contents: "no".to_string(),
            }],
        );
        assert!(rejected.is_err());
        fs::remove_dir_all(directory).expect("remove test directory");
    }
}
