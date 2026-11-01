use std::collections::HashSet;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

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
        .invoke_handler(tauri::generate_handler![write_export_archive])
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
