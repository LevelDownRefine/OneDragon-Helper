//! Start resolved targets independently of the backend and GUI lifetimes.
use super::super::*;
use super::*;
use serde::Deserialize;
use std::{
    collections::HashMap,
    io::Write,
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc::{self, Receiver, TryRecvError},
};

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LaunchTarget {
    Association {
        path: String,
        #[serde(default)]
        arguments: String,
    },
    Command {
        program: String,
        args: Vec<String>,
        cwd: String,
        env: HashMap<String, String>,
        #[serde(default)]
        input: Option<String>,
        #[serde(default)]
        console: bool,
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
            Self::Association { path, arguments } => {
                absolute_path(&path)?;
                if arguments.contains('\0') {
                    return Err("游戏启动参数无效".into());
                }
                crate::main_window::controllers::links::open_with_arguments(&path, &arguments)?;
                Ok(None)
            }
            Self::Command {
                program,
                args,
                cwd,
                env,
                input,
                console,
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
                    .stdin(if input.is_some() {
                        Stdio::piped()
                    } else {
                        Stdio::null()
                    })
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    command.creation_flags(if console { 0x0000_0010 } else { 0x0800_0000 });
                }
                #[cfg(not(windows))]
                let _ = console;
                let mut child = command
                    .spawn()
                    .map_err(|error| format!("启动失败：{error}"))?;
                if let Some(input) = input {
                    let result = child
                        .stdin
                        .take()
                        .expect("piped bootstrap")
                        .write_all(input.as_bytes());
                    if let Err(error) = result {
                        reap_in_background(child);
                        return Err(format!("传递运行配置失败：{error}"));
                    }
                }
                Ok(Some(child))
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

impl View {
    pub(super) fn launch_button(
        &mut self,
        ui: &mut Ui,
        screen: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) {
        let dx = screen.width() - SIZE.x;
        let dy = screen.height() - SIZE.y;
        let launch = rect(960.0 + dx, 636.0 + dy, 236.0, 60.0);
        panel(ui, launch, 18, PRIMARY);
        self.assets.icon(
            ui,
            "play",
            rect(launch.left() + 16.0, launch.top() + 14.0, 32.0, 32.0),
        );
        label(
            ui,
            rect(launch.left() + 54.0, launch.top() + 7.0, 117.0, 28.0),
            "启动脚本",
            17.0,
            TEXT,
        );
        label(
            ui,
            rect(launch.left() + 54.0, launch.top() + 35.0, 117.0, 18.0),
            "启动当前脚本",
            10.0,
            MUTED,
        );
        let response = ui.interact(
            rect(launch.left(), launch.top(), 180.0, 60.0),
            Id::new("launch"),
            Sense::click(),
        );
        if response.on_hover_text("启动当前脚本").clicked() && !data.busy {
            if let Some(name) = data.selected {
                actions.push(Action::Request(Request {
                    method: "script.launch_target".into(),
                    params: json!({"script_name":name,"target":"script"}),
                }));
            } else {
                self.toast("尚无脚本");
            }
        }
        ui.painter().line_segment(
            [
                launch.min + vec2(180.0, 16.0),
                launch.min + vec2(180.0, 44.0),
            ],
            egui::Stroke::new(1.0, BORDER),
        );
        if self.icon_button(
            ui,
            "settings",
            rect(launch.left() + 186.0, launch.top() + 6.0, 44.0, 48.0),
            "脚本配置",
            true,
        ) && !data.busy
        {
            if let Some(script) = data.selected {
                actions.push(Action::Request(Request {
                    method: "script.edit_view".into(),
                    params: json!({"script_name": script}),
                }));
            } else {
                self.toast("尚无脚本");
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_startup(&mut self, ui: &mut Ui) {
        if let Some(confirmed) = self
            .startup_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx()))
        {
            self.startup_dialog = None;
            if confirmed && !self.busy {
                self.request(
                    "run.saved",
                    json!({"script_names":self.ui.enabled_names(&self.scripts)}),
                );
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_run_confirm(&mut self, ui: &mut Ui) {
        if let Some(action) = self
            .run_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx(), self.busy))
        {
            match action {
                RunAction::Request(request) => {
                    self.error = None;
                    self.request(&request.method, request.params);
                }
                RunAction::Cancel => {
                    self.run_dialog = None;
                    if self.view.is_none() && self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "../../tests/controllers/launch.rs"]
mod tests;

impl App {
    pub(in crate::main_window) fn receive_launch(&mut self, method: &str, result: Value) {
        if method == "run.view" {
            match serde_json::from_value::<RunView>(result) {
                Ok(data) => {
                    self.run_dialog = Some(RunDialog::new(data));
                    self.status = "已同步".into();
                }
                Err(error) => self.fail(Failure::transport(format!("运行选项无效：{error}"))),
            }
        } else if matches!(method, "script.launch_target" | "run.prepare" | "run.saved") {
            match serde_json::from_value::<LaunchTarget>(result) {
                Ok(LaunchTarget::Unavailable { reason }) => {
                    self.ui.toast(reason);
                    self.status = "无法启动".into();
                }
                Ok(target) => {
                    if method == "run.prepare" {
                        self.run_dialog = None;
                    }
                    self.launch_job = Some(LaunchJob::start(target, self.ctx.clone()));
                    self.busy = true;
                    self.status = "启动中".into();
                }
                Err(error) => self.fail(Failure::transport(format!("启动信息无效：{error}"))),
            }
        } else {
            self.fail(Failure::transport("写操作响应无效"));
        }
    }
}
