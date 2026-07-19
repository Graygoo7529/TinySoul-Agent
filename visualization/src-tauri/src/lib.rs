use std::process::Stdio;

use serde::Deserialize;
use tauri::State;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{oneshot, Mutex};
use tokio::time::{timeout, Duration};

#[derive(serde::Serialize, Clone, Debug)]
pub struct BackendReady {
    pub host: String,
    pub port: u16,
    pub token: String,
    pub protocol_version: i64,
}

#[derive(Deserialize, Debug)]
struct ReadyLine {
    #[serde(rename = "type")]
    pub ty: String,
    pub protocol_version: Option<i64>,
    pub host: String,
    pub port: u16,
    pub token: String,
}

pub struct BackendProcess {
    inner: Mutex<Option<Child>>,
}

impl BackendProcess {
    fn new() -> Self {
        Self {
            inner: Mutex::new(None),
        }
    }
}

fn tinysoul_executable() -> String {
    if cfg!(windows) {
        "tinysoul.exe".to_string()
    } else {
        "tinysoul".to_string()
    }
}

#[tauri::command]
async fn start_backend(
    project_root: String,
    state: State<'_, BackendProcess>,
) -> Result<BackendReady, String> {
    {
        let guard = state.inner.lock().await;
        if guard.is_some() {
            return Err("Backend is already running".to_string());
        }
    }

    let (tx, rx) = oneshot::channel::<Result<BackendReady, String>>();
    let tx = Mutex::new(Some(tx));

    let mut cmd = Command::new(tinysoul_executable());
    cmd.args([
        "serve",
        "--root",
        &project_root,
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--mode",
        "model",
    ])
    .stdout(Stdio::piped())
    .stderr(Stdio::piped())
    .kill_on_drop(true);

    let mut child = cmd.spawn().map_err(|e| {
        format!(
            "Failed to spawn TinySoul backend ({}): {}. Is tinysoul on PATH?",
            tinysoul_executable(),
            e
        )
    })?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Failed to capture backend stdout".to_string())?;

    tokio::spawn(async move {
        let mut reader = BufReader::new(stdout).lines();
        let mut ready: Option<BackendReady> = None;
        while let Ok(Some(line)) = reader.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<ReadyLine>(&line) {
                Ok(parsed) if parsed.ty == "endpoint.ready" => {
                    ready = Some(BackendReady {
                        host: parsed.host,
                        port: parsed.port,
                        token: parsed.token,
                        protocol_version: parsed.protocol_version.unwrap_or(1),
                    });
                    break;
                }
                _ => {
                    // Keep scanning until we find the ready line. In headless mode the
                    // first non-empty line should be the ready JSON; log anything else
                    // to stderr for diagnostics.
                    eprintln!("[tinysoul stdout] {}", line);
                }
            }
        }

        if let Some(sender) = tx.lock().await.take() {
            let result = ready
                .ok_or_else(|| "Did not receive endpoint.ready from TinySoul backend".to_string());
            let _ = sender.send(result);
        }
    });

    let result = timeout(Duration::from_secs(30), rx)
        .await
        .map_err(|_| "Timed out waiting for TinySoul backend ready signal".to_string())?
        .map_err(|_| "Backend ready channel closed unexpectedly".to_string())?;

    match result {
        Ok(info) => {
            let mut guard = state.inner.lock().await;
            *guard = Some(child);
            Ok(info)
        }
        Err(e) => {
            let _ = child.kill().await;
            Err(e)
        }
    }
}

#[tauri::command]
async fn stop_backend(force: bool, state: State<'_, BackendProcess>) -> Result<(), String> {
    let mut guard = state.inner.lock().await;
    let Some(mut child) = guard.take() else {
        return Err("No backend is running".to_string());
    };

    if force {
        let _ = child.kill().await;
    } else {
        let _ = child.wait().await;
    }
    Ok(())
}

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(BackendProcess::new())
        .invoke_handler(tauri::generate_handler![greet, start_backend, stop_backend])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
