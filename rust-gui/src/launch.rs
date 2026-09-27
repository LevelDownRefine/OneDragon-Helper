//! Start resolved targets independently of the backend and GUI lifetimes.
use serde::Deserialize;
use std::{
    collections::HashMap,
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc::{self, Receiver, TryRecvError},
};

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LaunchTarget {
    Association {
        path: String,
    },
    Command {
        program: String,
        args: Vec<String>,
        cwd: String,
        env: HashMap<String, String>,
    },
    Unavailable {
        reason: String,
    },
}

fn absolute_path(value: &str) -> Result<(), String> {
    if !Path::new(value).is_absolute() || value.contains('\0') {
        Err("启动路径无效".into())
    } else {
        Ok(())
    }
}

impl LaunchTarget {
    fn start(self) -> Result<Option<Child>, String> {
        match self {
            Self::Unavailable { reason } => Err(reason),
            Self::Association { path } => {
                absolute_path(&path)?;
                crate::opener::open(&path)?;
                Ok(None)
            }
            Self::Command {
                program,
                args,
                cwd,
                env,
            } => {
                absolute_path(&program)?;
                absolute_path(&cwd)?;
                if args.iter().any(|arg| arg.contains('\0'))
                    || env.iter().any(|(key, value)| {
                        key.is_empty() || key.contains(['\0', '=']) || value.contains('\0')
                    })
                {
                    return Err("启动参数无效".into());
                }
                let mut command = Command::new(program);
                command
                    .args(args)
                    .current_dir(cwd)
                    .envs(env)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    command.creation_flags(0x0800_0000); // Runner writes its existing log files.
                }
                command
                    .spawn()
                    .map(Some)
                    .map_err(|error| format!("启动失败：{error}"))
            }
        }
    }
}

pub struct LaunchJob(Receiver<Result<Option<Child>, String>>);

pub fn reap_in_background(mut child: Child) {
    std::thread::spawn(move || {
        if let Err(error) = child.wait() {
            log::error!("回收运行进程失败：{error}");
        }
    });
}

impl LaunchJob {
    pub fn start(target: LaunchTarget, ctx: eframe::egui::Context) -> Self {
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            if let Err(mpsc::SendError(Ok(Some(child)))) = sender.send(target.start()) {
                reap_in_background(child);
            }
            ctx.request_repaint();
        });
        Self(receiver)
    }

    pub fn poll(&self) -> Option<Result<Option<Child>, String>> {
        match self.0.try_recv() {
            Ok(result) => Some(result),
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => Some(Err("启动任务意外退出".into())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runner_launch_preserves_arguments_and_survives_gui_owner_drop() {
        let root = tempfile::tempdir().unwrap();
        let marker = root.path().join("中文 & marker.txt");
        let python = std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into());
        let python = Path::new(&python)
            .canonicalize()
            .expect("absolute test Python");
        let target=LaunchTarget::Command {program:python.to_string_lossy().into(),
            args:vec!["-c".into(),"import sys,time,os;from pathlib import Path;time.sleep(.3);Path(sys.argv[1]).write_text(sys.argv[2]+os.environ['ODH_LAUNCH_TEST'],encoding='utf-8')".into(),marker.to_string_lossy().into(),"原样 & 空格".into()],
            cwd:root.path().to_string_lossy().into(),env:HashMap::from([("ODH_LAUNCH_TEST".into(),"环境".into())])};
        let job = LaunchJob::start(target, eframe::egui::Context::default());
        let child = job
            .0
            .recv_timeout(std::time::Duration::from_secs(10))
            .unwrap()
            .unwrap()
            .unwrap();
        drop(job);
        drop(child); // GUI exit drops handles; it must not terminate external work.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while !marker.exists() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        assert_eq!(std::fs::read_to_string(marker).unwrap(), "原样 & 空格环境");
    }

    #[test]
    fn unavailable_and_invalid_targets_fail_before_launch() {
        assert!(
            LaunchTarget::Association {
                path: "relative.exe".into()
            }
            .start()
            .is_err()
        );
        assert!(
            LaunchTarget::Unavailable {
                reason: "未安装".into()
            }
            .start()
            .is_err()
        );
        assert!(absolute_path("C:/invalid\0file").is_err());
    }
}
