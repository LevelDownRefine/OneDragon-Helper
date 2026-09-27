//! Open resolved resources with their system association, without a command shell.
use serde::Deserialize;
use std::sync::mpsc::{self, Receiver, TryRecvError};

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Target {
    Url { value: String },
    Path { value: String },
    Unavailable { reason: String },
}

impl Target {
    fn value(&self) -> Result<&str, String> {
        let value = match self {
            Self::Url { value }
                if value.starts_with("https://") || value.starts_with("http://") =>
            {
                value
            }
            Self::Path { value } if std::path::Path::new(value).is_absolute() => value,
            Self::Unavailable { reason } => return Err(reason.clone()),
            _ => return Err("资源目标无效".into()),
        };
        if value.contains('\0') {
            return Err("资源目标含无效字符".into());
        }
        Ok(value)
    }
}

pub struct OpenJob(Receiver<Result<(), String>>);

impl OpenJob {
    pub fn start(target: Target, repaint: impl FnOnce() + Send + 'static) -> Self {
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let result = target.value().and_then(open);
            let _ = sender.send(result);
            repaint();
        });
        Self(receiver)
    }

    pub fn poll(&self) -> Option<Result<(), String>> {
        match self.0.try_recv() {
            Ok(result) => Some(result),
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => Some(Err("打开资源的任务意外退出".into())),
        }
    }
}

#[cfg(windows)]
fn open(value: &str) -> Result<(), String> {
    use windows_sys::Win32::{
        System::Com::{
            COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE, CoInitializeEx, CoUninitialize,
        },
        UI::Shell::ShellExecuteW,
    };
    let path: Vec<u16> = value.encode_utf16().chain(Some(0)).collect();
    let verb: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
    // This worker owns its COM apartment; the strings remain alive for the call.
    unsafe {
        let initialized = CoInitializeEx(
            std::ptr::null(),
            (COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) as u32,
        );
        if initialized < 0 {
            return Err(format!("无法初始化系统文件关联：{initialized:#x}"));
        }
        let result = ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            path.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        ) as isize;
        CoUninitialize();
        if result <= 32 {
            return Err(format!(
                "无法打开资源（系统错误 {result}），请检查文件与默认关联程序"
            ));
        }
    }
    Ok(())
}

#[cfg(not(windows))]
fn open(value: &str) -> Result<(), String> {
    let executable = if cfg!(target_os = "macos") {
        "open"
    } else {
        "xdg-open"
    };
    let status = std::process::Command::new(executable)
        .arg(value)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|error| format!("无法打开资源：{error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("系统关联程序退出：{status}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn targets_keep_path_characters_and_reject_other_schemes() {
        let root = tempfile::tempdir().unwrap();
        let value = root
            .path()
            .join("中文 & test config.yml")
            .to_string_lossy()
            .into_owned();
        assert_eq!(
            Target::Path {
                value: value.clone()
            }
            .value()
            .unwrap(),
            value
        );
        assert!(
            Target::Path {
                value: "relative.yml".into()
            }
            .value()
            .is_err()
        );
        for value in [
            "file:///run.exe",
            "javascript:alert(1)",
            "https://example.org/\0x",
        ] {
            assert!(
                Target::Url {
                    value: value.into()
                }
                .value()
                .is_err()
            );
        }
        assert_eq!(
            Target::Url {
                value: "https://example.org/?a=1&b=2".into()
            }
            .value()
            .unwrap(),
            "https://example.org/?a=1&b=2"
        );
    }

    #[test]
    fn unavailable_target_completes_without_opening_a_program() {
        let job = OpenJob::start(
            Target::Unavailable {
                reason: "未安装".into(),
            },
            || {},
        );
        let result = job
            .0
            .recv_timeout(std::time::Duration::from_secs(2))
            .unwrap();
        assert_eq!(result.unwrap_err(), "未安装");
    }
}
