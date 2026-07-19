use notify::{RecursiveMode, Watcher};
use serde::Serialize;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::mpsc::channel;
use tauri::{Emitter, Manager};
use walkdir::WalkDir;

#[derive(Serialize)]
struct VaultFile {
    path: String,
    content: String,
    modified_ms: u128,
}

fn safe_join(root: &str, relative: &str) -> Result<PathBuf, String> {
    let relative_path = Path::new(relative);
    if relative_path.is_absolute()
        || relative_path
            .components()
            .any(|part| matches!(part, Component::ParentDir | Component::RootDir | Component::Prefix(_)))
    {
        return Err("Unsafe vault path".into());
    }
    Ok(Path::new(root).join(relative_path))
}

#[tauri::command]
fn save_secret(api_url: String, value: String) -> Result<(), String> {
    keyring::Entry::new("Taskman", &api_url)
        .map_err(|error| error.to_string())?
        .set_password(&value)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn load_secret(api_url: String) -> Result<Option<String>, String> {
    let entry = keyring::Entry::new("Taskman", &api_url).map_err(|error| error.to_string())?;
    match entry.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn scan_vault(root: String) -> Result<Vec<VaultFile>, String> {
    let root_path = Path::new(&root);
    if !root_path.exists() {
        fs::create_dir_all(root_path).map_err(|error| error.to_string())?;
    }
    let mut files = Vec::new();
    for entry in WalkDir::new(root_path).into_iter().filter_map(Result::ok) {
        if !entry.file_type().is_file() || entry.path().extension().and_then(|value| value.to_str()) != Some("md") {
            continue;
        }
        if entry.path().components().any(|part| part.as_os_str() == ".taskman") {
            continue;
        }
        let relative = entry.path().strip_prefix(root_path).map_err(|error| error.to_string())?;
        let metadata = entry.metadata().map_err(|error| error.to_string())?;
        let modified_ms = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|duration| duration.as_millis())
            .unwrap_or_default();
        files.push(VaultFile {
            path: relative.to_string_lossy().replace('\\', "/"),
            content: fs::read_to_string(entry.path()).map_err(|error| error.to_string())?,
            modified_ms,
        });
    }
    Ok(files)
}

#[tauri::command]
fn write_vault_file(root: String, path: String, content: String) -> Result<(), String> {
    let destination = safe_join(&root, &path)?;
    if destination.extension().and_then(|value| value.to_str()) != Some("md") {
        return Err("Only Markdown files can be written".into());
    }
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temporary = destination.with_extension("md.tmp");
    fs::write(&temporary, content).map_err(|error| error.to_string())?;
    fs::rename(temporary, destination).map_err(|error| error.to_string())
}

#[tauri::command]
fn trash_vault_file(root: String, path: String) -> Result<(), String> {
    let source = safe_join(&root, &path)?;
    if !source.exists() {
        return Ok(());
    }
    let trash = Path::new(&root).join(".taskman").join("trash");
    fs::create_dir_all(&trash).map_err(|error| error.to_string())?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_secs();
    let filename = source.file_name().and_then(|value| value.to_str()).unwrap_or("note.md");
    fs::rename(source, trash.join(format!("{}-{}", stamp, filename))).map_err(|error| error.to_string())
}

#[tauri::command]
fn watch_vault(app: tauri::AppHandle, root: String) -> Result<(), String> {
    let root_path = PathBuf::from(root);
    std::thread::spawn(move || {
        let (sender, receiver) = channel();
        let Ok(mut watcher) = notify::recommended_watcher(sender) else { return; };
        if watcher.watch(&root_path, RecursiveMode::Recursive).is_err() {
            return;
        }
        while let Ok(event) = receiver.recv() {
            if let Ok(event) = event {
                let paths: Vec<String> = event
                    .paths
                    .iter()
                    .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("md"))
                    .map(|path| path.to_string_lossy().to_string())
                    .collect();
                if !paths.is_empty() {
                    let _ = app.emit("vault-changed", paths);
                }
            }
        }
    });
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let _ = tauri::tray::TrayIconBuilder::new()
                .tooltip("Taskman")
                .build(app);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            save_secret,
            load_secret,
            scan_vault,
            write_vault_file,
            trash_vault_file,
            watch_vault
        ])
        .run(tauri::generate_context!())
        .expect("error while running Taskman");
}
