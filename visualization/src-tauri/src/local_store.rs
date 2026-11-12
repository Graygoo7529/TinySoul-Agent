//! Frontend local store: a user-chosen directory holding the frontend's
//! device-local data (connection profile, UI state). Every file access is
//! constrained to the configured directory, key names are validated, and
//! writes are atomic (tmp + rename). The chosen directory itself is kept in
//! the app config directory (`local-store.json`).

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::Manager;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LocalStoreState {
    pub dir: Option<String>,
}

const STATE_FILE: &str = "local-store.json";
const KEY_SUFFIX: &str = ".json";
const MAX_KEY_LEN: usize = 64;

fn state_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|dir| dir.join(STATE_FILE))
        .map_err(|error| format!("Cannot resolve the app config directory: {error}"))
}

fn read_configured_dir(app: &tauri::AppHandle) -> Result<Option<PathBuf>, String> {
    let path = state_path(app)?;
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path)
        .map_err(|error| format!("Cannot read the local store state: {error}"))?;
    let dir = raw.trim();
    Ok(if dir.is_empty() {
        None
    } else {
        Some(PathBuf::from(dir))
    })
}

fn validate_key(key: &str) -> Result<(), String> {
    let valid = !key.is_empty()
        && key.len() <= MAX_KEY_LEN
        && key
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-');
    if valid {
        Ok(())
    } else {
        Err(format!("Invalid local store key: {key}"))
    }
}

fn key_path(dir: &Path, key: &str) -> Result<PathBuf, String> {
    validate_key(key)?;
    Ok(dir.join(format!("{key}{KEY_SUFFIX}")))
}

fn atomic_write(path: &Path, payload: &str) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, payload)
        .map_err(|error| format!("Cannot write local store data: {error}"))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("Cannot replace local store data: {error}"))?;
    }
    fs::rename(&temporary, path)
        .map_err(|error| format!("Cannot finalize local store data: {error}"))
}

fn require_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    match read_configured_dir(app)? {
        Some(dir) if dir.is_dir() => Ok(dir),
        _ => Err("No local data directory is configured".to_string()),
    }
}

#[tauri::command]
pub fn local_store_state(app: tauri::AppHandle) -> Result<LocalStoreState, String> {
    Ok(LocalStoreState {
        dir: read_configured_dir(&app)?.map(|dir| dir.to_string_lossy().to_string()),
    })
}

#[tauri::command]
pub fn local_store_set_dir(app: tauri::AppHandle, dir: String) -> Result<LocalStoreState, String> {
    let dir = dir.trim().to_string();
    if dir.is_empty() {
        return Err("The chosen data directory is empty".to_string());
    }
    let path = PathBuf::from(&dir);
    fs::create_dir_all(&path)
        .map_err(|error| format!("Cannot create the chosen data directory: {error}"))?;
    let state = state_path(&app)?;
    if let Some(parent) = state.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Cannot create the app config directory: {error}"))?;
    }
    atomic_write(&state, &dir)?;
    Ok(LocalStoreState { dir: Some(dir) })
}

#[tauri::command]
pub fn local_store_read(app: tauri::AppHandle, key: String) -> Result<Option<String>, String> {
    let dir = require_dir(&app)?;
    let path = key_path(&dir, &key)?;
    if !path.is_file() {
        return Ok(None);
    }
    fs::read_to_string(&path)
        .map(Some)
        .map_err(|error| format!("Cannot read local store data: {error}"))
}

#[tauri::command]
pub fn local_store_write(app: tauri::AppHandle, key: String, payload: String) -> Result<(), String> {
    let dir = require_dir(&app)?;
    let path = key_path(&dir, &key)?;
    atomic_write(&path, &payload)
}

#[tauri::command]
pub fn local_store_list(app: tauri::AppHandle) -> Result<Vec<String>, String> {
    let dir = require_dir(&app)?;
    let mut keys = Vec::new();
    let entries =
        fs::read_dir(&dir).map_err(|error| format!("Cannot list local store data: {error}"))?;
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if let Some(key) = name.strip_suffix(KEY_SUFFIX) {
            if validate_key(key).is_ok() {
                keys.push(key.to_string());
            }
        }
    }
    keys.sort();
    Ok(keys)
}

#[tauri::command]
pub fn local_store_remove(app: tauri::AppHandle, key: String) -> Result<(), String> {
    let dir = require_dir(&app)?;
    let path = key_path(&dir, &key)?;
    if path.exists() {
        fs::remove_file(&path)
            .map_err(|error| format!("Cannot remove local store data: {error}"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{atomic_write, key_path, validate_key};
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn key_validation_rejects_separators_and_traversal() {
        assert!(validate_key("connection").is_ok());
        assert!(validate_key("ui-state.v2").is_ok());
        assert!(validate_key("../escape").is_err());
        assert!(validate_key("a/b").is_err());
        assert!(validate_key("a\\b").is_err());
        assert!(validate_key("").is_err());
    }

    #[test]
    fn atomic_write_replaces_atomically() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock before unix epoch")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("tinysoul-local-store-{stamp}"));
        fs::create_dir_all(&dir).expect("create test directory");
        let file = key_path(&dir, "connection").expect("key path");
        atomic_write(&file, "one").expect("first write");
        atomic_write(&file, "two").expect("replace write");
        assert_eq!(fs::read_to_string(&file).expect("read back"), "two");
        assert!(!dir.join("connection.tmp").exists());
        fs::remove_dir_all(&dir).expect("remove test directory");
    }
}
