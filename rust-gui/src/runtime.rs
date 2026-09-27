//! Resolve the development interpreter or the backend shipped beside the GUI.
use serde::Deserialize;
use std::{
    path::{Path, PathBuf},
    process::Command,
};

const GUI_EXE: &str = "OneDragon-Helper.exe";
const CLI_EXE: &str = "OneDragon-Helper-CLI.exe";

pub enum BackendProgram {
    Source(PathBuf),
    Bundled(PathBuf),
}

impl BackendProgram {
    pub fn command(&self, root: &Path) -> Command {
        let mut command = match self {
            Self::Source(python) => {
                let mut command = Command::new(python);
                command.args(["-m", "src.headless"]);
                command
            }
            Self::Bundled(executable) => Command::new(executable),
        };
        command
            .args(["serve", "--stdio"])
            .current_dir(root)
            .env("PYTHONUTF8", "1");
        command
    }
}

pub fn resolve(
    project: Option<PathBuf>,
    python: Option<PathBuf>,
    executable: &Path,
    cwd: &Path,
    virtual_env: Option<PathBuf>,
) -> Result<(PathBuf, BackendProgram), String> {
    let directory = executable.parent().ok_or("无法定位助手目录")?;
    if project.is_none()
        && (executable
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.eq_ignore_ascii_case(GUI_EXE))
            || directory.join(CLI_EXE).is_file()
            || directory.join("version.json").is_file())
    {
        if python.is_some() {
            return Err("发布版使用随附 CLI；源码调试请同时指定 --project-root".into());
        }
        let root = directory
            .canonicalize()
            .map_err(|error| error.to_string())?;
        #[derive(Deserialize)]
        struct Version {
            frontend: String,
            version: String,
        }
        let metadata = std::fs::read(root.join("version.json"))
            .map_err(|error| format!("发布包缺少或无法读取 version.json：{error}"))?;
        let metadata: Version = serde_json::from_slice(&metadata)
            .map_err(|error| format!("发布包版本信息无效：{error}"))?;
        if metadata.frontend != "rust" || metadata.version.trim().is_empty() {
            return Err("此目录不是有效的 Rust 发布包".into());
        }
        let backend = root.join(CLI_EXE);
        if !backend.is_file() || !root.join("_internal").is_dir() {
            return Err("Rust 发布包不完整：缺少 OneDragon-Helper-CLI.exe 或 _internal，请重新解压完整发布包".into());
        }
        return Ok((root, BackendProgram::Bundled(backend)));
    }
    let root = cwd.join(project.unwrap_or_else(|| cwd.to_path_buf()));
    if !root.join("src/headless.py").is_file() {
        return Err("请从项目根运行，或用 --project-root 指定含 src/headless.py 的目录".into());
    }
    let root = root.canonicalize().map_err(|error| error.to_string())?;
    let suffix = if cfg!(windows) {
        "Scripts/python.exe"
    } else {
        "bin/python"
    };
    let python = python.unwrap_or_else(|| {
        if let Some(environment) = virtual_env {
            environment.join(suffix)
        } else {
            let local = root.join(".venv").join(suffix);
            if local.is_file() {
                local
            } else {
                PathBuf::from("python")
            }
        }
    });
    let python = if python.components().count() > 1 {
        cwd.join(python)
            .canonicalize()
            .map_err(|error| format!("Python 路径无效：{error}"))?
    } else {
        python
    };
    Ok((root, BackendProgram::Source(python)))
}

pub fn startup_error(message: &str) {
    log::error!("{message}");
    #[cfg(windows)]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{MB_ICONERROR, MB_OK, MessageBoxW};
        let message: Vec<u16> = message.encode_utf16().chain(Some(0)).collect();
        let title: Vec<u16> = "OneDragon Helper · 启动失败"
            .encode_utf16()
            .chain(Some(0))
            .collect();
        // Release GUI has no console; expose startup failures before an egui window exists.
        unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                message.as_ptr(),
                title.as_ptr(),
                MB_ICONERROR | MB_OK,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    fn package(root: &Path) -> PathBuf {
        std::fs::write(
            root.join("version.json"),
            r#"{"frontend":"rust","version":"1.0.0"}"#,
        )
        .unwrap();
        std::fs::write(root.join(CLI_EXE), []).unwrap();
        std::fs::create_dir(root.join("_internal")).unwrap();
        root.join(GUI_EXE)
    }

    #[test]
    fn bundled_backend_ignores_cwd_and_virtual_environment() {
        let temp = tempfile::tempdir().unwrap();
        let executable = package(temp.path());
        let cwd = tempfile::tempdir().unwrap();
        let (root, backend) = resolve(
            None,
            None,
            &executable,
            cwd.path(),
            Some("missing-env".into()),
        )
        .unwrap();
        assert_eq!(root, temp.path().canonicalize().unwrap());
        let command = backend.command(&root);
        assert_eq!(command.get_program(), root.join(CLI_EXE).as_os_str());
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            [OsStr::new("serve"), OsStr::new("--stdio")]
        );
        assert_eq!(command.get_current_dir(), Some(root.as_path()));
        assert!(!root.join("src").exists());
    }

    #[test]
    fn broken_package_does_not_fall_back_to_python() {
        for missing in ["version.json", CLI_EXE, "_internal"] {
            let temp = tempfile::tempdir().unwrap();
            let executable = package(temp.path());
            let path = temp.path().join(missing);
            if path.is_dir() {
                std::fs::remove_dir(path).unwrap();
            } else {
                std::fs::remove_file(path).unwrap();
            }
            assert!(resolve(None, None, &executable, temp.path(), None).is_err());
            assert!(
                resolve(
                    None,
                    None,
                    &temp.path().join(GUI_EXE.to_lowercase()),
                    temp.path(),
                    None
                )
                .is_err()
            );
        }
        for metadata in [
            r#"{"version":"1.0.0"}"#,
            r#"{"version":"1.0.0","frontend":"qt"}"#,
            r#"{"version":"","frontend":"rust"}"#,
        ] {
            let temp = tempfile::tempdir().unwrap();
            let executable = package(temp.path());
            std::fs::write(temp.path().join("version.json"), metadata).unwrap();
            assert!(resolve(None, None, &executable, temp.path(), None).is_err());
        }
    }

    #[test]
    fn explicit_source_root_retains_development_arguments() {
        let temp = tempfile::tempdir().unwrap();
        let executable = package(temp.path());
        let source = temp.path().join("source project");
        std::fs::create_dir_all(source.join("src")).unwrap();
        std::fs::write(source.join("src/headless.py"), []).unwrap();
        let interpreter = temp.path().join("python.exe");
        std::fs::write(&interpreter, []).unwrap();
        assert!(
            resolve(
                None,
                Some(interpreter.clone()),
                &executable,
                temp.path(),
                None
            )
            .is_err()
        );
        let (root, backend) = resolve(
            Some("source project".into()),
            Some(interpreter.clone()),
            &executable,
            temp.path(),
            None,
        )
        .unwrap();
        let command = backend.command(&root);
        assert_eq!(
            command.get_program(),
            interpreter.canonicalize().unwrap().as_os_str()
        );
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            ["-m", "src.headless", "serve", "--stdio"].map(OsStr::new)
        );
    }
}
