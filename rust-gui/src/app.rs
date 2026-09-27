use crate::opener::{OpenJob, Target};
use crate::script_editor::{EditAction, EditView, ScriptEditor};
use crate::view::{Action, Presentation, View};
use eframe::egui;
use onedragon_rust_gui::{
    backend::{Backend, Failure, Reply, Request},
    model::{Script, ScriptView, Snapshot},
};
use serde_json::{Value, json};
use std::{path::PathBuf, process::Command, time::Instant};

pub struct Settings {
    pub project_root: PathBuf,
    pub python: PathBuf,
    pub font: Option<PathBuf>,
    pub demo: bool,
    #[cfg(feature = "capture")]
    pub capture: Option<PathBuf>,
    #[cfg(feature = "capture")]
    pub capture_editor: bool,
}

impl Settings {
    fn command(&self) -> Command {
        let mut command = Command::new(&self.python);
        command
            .args(["-m", "src.headless", "serve", "--stdio"])
            .current_dir(&self.project_root)
            .env("PYTHONUTF8", "1");
        command
    }
}

pub struct App {
    settings: Settings,
    backend: Option<Backend>,
    scripts: Vec<Script>,
    selected: Option<String>,
    view: Option<ScriptView>,
    busy: bool,
    status: String,
    error: Option<String>,
    diagnostics: String,
    pid: u32,
    started: Instant,
    first_ui: bool,
    ready_logged: bool,
    write_confirmed: bool,
    ctx: egui::Context,
    ui: View,
    open_job: Option<OpenJob>,
    editor: Option<ScriptEditor>,
    open_editor_after_snapshot: bool,
    #[cfg(feature = "capture")]
    capture_requested: bool,
    #[cfg(feature = "capture")]
    capture_ready_at: Option<Instant>,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, settings: Settings, started: Instant) -> Self {
        crate::skin::configure(&cc.egui_ctx);
        let font_error = install_font(&cc.egui_ctx, settings.font.as_ref()).err();
        let mut app = Self {
            settings,
            backend: None,
            scripts: Vec::new(),
            selected: None,
            view: None,
            busy: false,
            status: "连接中".into(),
            error: font_error,
            diagnostics: String::new(),
            pid: 0,
            started,
            first_ui: true,
            ready_logged: false,
            write_confirmed: false,
            ctx: cc.egui_ctx.clone(),
            ui: View::new(&cc.egui_ctx),
            open_job: None,
            editor: None,
            open_editor_after_snapshot: false,
            #[cfg(feature = "capture")]
            capture_requested: false,
            #[cfg(feature = "capture")]
            capture_ready_at: None,
        };
        app.connect();
        app
    }

    fn connect(&mut self) {
        let ctx = self.ctx.clone();
        self.backend = Some(Backend::start(self.settings.command(), move || {
            ctx.request_repaint()
        }));
        self.request("app.snapshot", json!({}));
    }

    fn request(&mut self, method: &str, params: Value) {
        assert!(!self.busy, "only one request may be outstanding");
        self.ui.close_menu();
        let request = Request {
            method: method.into(),
            params,
        };
        let sent = self
            .backend
            .as_ref()
            .is_some_and(|backend| backend.requests.send(request).is_ok());
        if sent {
            self.busy = true;
            self.status = if matches!(
                method,
                "app.snapshot" | "script.view" | "script.target" | "script.edit_view"
            ) {
                "读取中"
            } else {
                "保存中"
            }
            .into();
        } else {
            self.fail(Failure::transport("连接已关闭，请刷新重连"));
        }
    }

    fn refresh_view(&mut self) {
        self.view = None;
        if let Some(name) = self.selected.clone() {
            self.request("script.view", json!({"script_name": name}));
        }
    }

    fn fail(&mut self, mut failure: Failure) {
        if self.write_confirmed {
            failure.message = format!("已保存，但刷新失败：{}", failure.message);
        }
        self.write_confirmed = false;
        self.open_job = None;
        self.busy = false;
        self.view = None;
        self.status = "操作失败 · 请刷新".into();
        self.ui.toast(&failure.message);
        if let Some(editor) = &mut self.editor {
            editor.failure(failure.message.clone(), true);
        }
        self.error = Some(failure.message);
        if failure.code == "transport_failed" {
            self.backend = None;
        }
    }

    fn receive(&mut self, reply: Reply) {
        self.busy = false;
        self.pid = reply.pid;
        self.diagnostics = reply.diagnostics;
        let result = match reply.result {
            Ok(value) => value,
            Err(failure) => {
                if matches!(
                    reply.method.as_str(),
                    "script.edit_view" | "script.edit_save"
                ) {
                    let needs_reload =
                        failure.refresh_required || failure.code == "transport_failed";
                    let message = failure.message.clone();
                    self.fail(failure);
                    if let Some(editor) = &mut self.editor {
                        editor.failure(message, needs_reload);
                    }
                    if reply.method == "script.edit_save" && needs_reload && self.backend.is_some()
                    {
                        self.request("app.snapshot", json!({}));
                    }
                    return;
                }
                let reread = failure.refresh_required
                    && failure.code != "transport_failed"
                    && reply.method != "script.view"
                    && reply.method != "app.snapshot";
                self.fail(failure);
                if reread {
                    self.refresh_view();
                }
                return;
            }
        };
        if reply.method == "app.snapshot" {
            match serde_json::from_value::<Snapshot>(result) {
                Ok(snapshot) => {
                    self.scripts = snapshot.scripts;
                    if let Some(editor) = &self.editor
                        && editor.needs_reload
                        && let Some(script) = self
                            .scripts
                            .iter()
                            .find(|script| editor.matches_saved(script))
                    {
                        self.selected = Some(script.script_name.clone());
                    }
                    if !self
                        .scripts
                        .iter()
                        .any(|script| Some(&script.script_name) == self.selected.as_ref())
                    {
                        self.selected = self
                            .scripts
                            .first()
                            .map(|script| script.script_name.clone());
                    }
                    self.status = "已同步".into();
                    if std::mem::take(&mut self.open_editor_after_snapshot) {
                        if let Some(name) = self.selected.clone() {
                            self.request("script.edit_view", json!({"script_name": name}));
                        } else {
                            self.editor = None;
                            self.ui.toast("脚本已不存在");
                        }
                    } else {
                        self.refresh_view();
                    }
                }
                Err(err) => self.fail(Failure::transport(format!("脚本列表数据无效：{err}"))),
            }
        } else if reply.method == "script.edit_view" {
            match serde_json::from_value::<EditView>(result) {
                Ok(data) if Some(&data.script_name) == self.selected.as_ref() => {
                    self.editor = Some(ScriptEditor::new(data));
                    self.status = "已同步".into();
                }
                _ => self.fail(Failure::transport("脚本配置数据无效")),
            }
        } else if reply.method == "script.edit_save" {
            #[derive(serde::Deserialize)]
            struct Saved {
                script_name: String,
            }
            match serde_json::from_value::<Saved>(result) {
                Ok(saved) if !saved.script_name.is_empty() => {
                    self.selected = Some(saved.script_name);
                    self.editor = None;
                    self.view = None;
                    self.write_confirmed = true;
                    self.ui.toast("配置已保存");
                    self.request("app.snapshot", json!({}));
                }
                _ => self.fail(Failure::transport("脚本保存响应无效，请刷新核对")),
            }
        } else if reply.method == "script.target" {
            match serde_json::from_value::<Target>(result) {
                Ok(Target::Unavailable { reason }) => {
                    self.ui.toast(reason);
                    self.status = "资源不可用".into();
                }
                Ok(target) => {
                    let ctx = self.ctx.clone();
                    self.open_job = Some(OpenJob::start(target, move || ctx.request_repaint()));
                    self.busy = true;
                    self.status = "打开中".into();
                }
                Err(error) => self.fail(Failure::transport(format!("资源响应无效：{error}"))),
            }
        } else if reply.method == "script.view" {
            match serde_json::from_value::<ScriptView>(result) {
                Ok(view)
                    if Some(&view.script.script_name) == self.selected.as_ref()
                        && view
                            .weeklies
                            .iter()
                            .all(|weekly| weekly.start_day.is_none_or(|day| day <= 7)) =>
                {
                    self.view = Some(view);
                    self.write_confirmed = false;
                    self.status = "已同步".into();
                    if !self.ready_logged {
                        self.ready_logged = true;
                        log::info!(
                            "[startup] first task ready {:.2} ms",
                            self.started.elapsed().as_secs_f64() * 1000.0
                        );
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && self.settings.capture_editor {
                            self.request("script.edit_view", json!({"script_name": self.selected}));
                        }
                    }
                }
                Ok(_) => self.fail(Failure::transport("任务卡身份或起始日无效")),
                Err(err) => self.fail(Failure::transport(format!("任务卡数据无效：{err}"))),
            }
        } else if matches!(
            reply.method.as_str(),
            "daily.select" | "daily.enable" | "weekly.select" | "weekly.start"
        ) && result.is_null()
        {
            self.write_confirmed = true;
            self.refresh_view();
        } else {
            self.fail(Failure::transport("写操作响应无效"));
        }
    }
}

impl eframe::App for App {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if let Some(result) = self.open_job.as_ref().and_then(OpenJob::poll) {
            self.open_job = None;
            self.busy = false;
            match result {
                Ok(()) => {
                    self.status = "已同步".into();
                    self.ui.toast("已打开");
                }
                Err(error) => {
                    self.status = "打开失败".into();
                    self.ui.toast(error);
                }
            }
        }
        let reply = self
            .backend
            .as_ref()
            .and_then(|backend| backend.replies.try_recv().ok());
        if let Some(reply) = reply {
            self.receive(reply);
        }
        #[cfg(feature = "capture")]
        if let Some(path) = &self.settings.capture {
            for event in ctx.input(|input| input.events.clone()) {
                if let egui::Event::Screenshot { image, .. } = event {
                    let bytes: Vec<u8> = image
                        .pixels
                        .iter()
                        .flat_map(|pixel| pixel.to_array())
                        .collect();
                    if let Err(error) = image::save_buffer(
                        path,
                        &bytes,
                        image.size[0] as u32,
                        image.size[1] as u32,
                        image::ColorType::Rgba8,
                    ) {
                        log::error!("保存截图失败：{error}");
                    }
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
        }
        #[cfg(not(feature = "capture"))]
        let _ = ctx;
    }

    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        [0.0; 4]
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if self.first_ui {
            self.first_ui = false;
            log::info!(
                "[startup] first UI callback {:.2} ms",
                self.started.elapsed().as_secs_f64() * 1000.0
            );
        }
        let actions = self.ui.show(
            ui,
            Presentation {
                scripts: &self.scripts,
                selected: self.selected.as_deref(),
                view: self.view.as_ref(),
                busy: self.busy,
                status: &self.status,
                demo: self.settings.demo,
            },
        );
        for action in actions {
            match action {
                Action::Select(name) => {
                    self.selected = Some(name);
                    self.error = None;
                    if self.backend.is_some() {
                        self.refresh_view();
                    } else {
                        self.connect();
                    }
                }
                Action::Request(request) => {
                    self.error = None;
                    self.request(&request.method, request.params);
                }
                Action::Refresh => {
                    self.error = None;
                    self.view = None;
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    } else {
                        self.connect();
                    }
                }
                Action::Diagnostics => self.ui.diagnostics_open = !self.ui.diagnostics_open,
            }
        }
        if let Some(action) = self
            .editor
            .as_mut()
            .and_then(|editor| editor.show(ui.ctx(), self.busy))
        {
            match action {
                EditAction::Cancel => {
                    self.editor = None;
                    self.open_editor_after_snapshot = false;
                    if self.view.is_none() && self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                }
                EditAction::Reload => {
                    self.open_editor_after_snapshot = true;
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    } else {
                        self.connect();
                    }
                }
                EditAction::Save(request) => {
                    self.error = None;
                    self.request(&request.method, request.params);
                }
            }
        }
        egui::Window::new("连接诊断")
            .open(&mut self.ui.diagnostics_open)
            .default_width(520.0)
            .show(ui.ctx(), |ui| {
                ui.label(format!("Python CLI PID: {}", self.pid));
                ui.label(self.settings.project_root.display().to_string());
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                egui::ScrollArea::vertical()
                    .max_height(260.0)
                    .show(ui, |ui| {
                        ui.label(&self.diagnostics);
                    });
            });
        #[cfg(feature = "capture")]
        if self.settings.capture.is_some()
            && self.ready_logged
            && !self.capture_requested
            && (!self.settings.capture_editor || self.editor.is_some())
        {
            let ready = self.capture_ready_at.get_or_insert_with(Instant::now);
            if ready.elapsed() >= std::time::Duration::from_millis(250) {
                self.capture_requested = true;
                ui.ctx()
                    .send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
            } else {
                ui.ctx()
                    .request_repaint_after(std::time::Duration::from_millis(50));
            }
        }
    }
}

fn install_font(ctx: &egui::Context, explicit: Option<&PathBuf>) -> Result<(), String> {
    let candidates = if let Some(path) = explicit {
        vec![path.clone()]
    } else {
        vec![
            PathBuf::from("C:/Windows/Fonts/msyh.ttc"),
            PathBuf::from("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            PathBuf::from("/System/Library/Fonts/PingFang.ttc"),
        ]
    };
    for path in candidates {
        if path.is_file() {
            let bytes = std::fs::read(&path).map_err(|err| format!("无法读取中文字体：{err}"))?;
            let mut fonts = egui::FontDefinitions::default();
            fonts
                .font_data
                .insert("cjk".into(), egui::FontData::from_owned(bytes).into());
            for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
                fonts
                    .families
                    .entry(family)
                    .or_default()
                    .insert(0, "cjk".into());
            }
            ctx.set_fonts(fonts);
            return Ok(());
        }
    }
    Err("Chinese font missing. Start with --font <path-to-font>.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn test_app(command: Command, root: &std::path::Path, python: PathBuf) -> App {
        let ctx = egui::Context::default();
        App {
            settings: Settings {
                project_root: root.into(),
                python,
                font: None,
                demo: true,
                #[cfg(feature = "capture")]
                capture: None,
                #[cfg(feature = "capture")]
                capture_editor: false,
            },
            backend: Some(Backend::start(command, || {})),
            scripts: Vec::new(),
            selected: Some("test".into()),
            view: None,
            busy: false,
            status: String::new(),
            error: None,
            diagnostics: String::new(),
            pid: 0,
            started: Instant::now(),
            first_ui: true,
            ready_logged: false,
            write_confirmed: false,
            ui: View::new(&ctx),
            open_job: None,
            editor: None,
            open_editor_after_snapshot: false,
            ctx,
            #[cfg(feature = "capture")]
            capture_requested: false,
            #[cfg(feature = "capture")]
            capture_ready_at: None,
        }
    }

    #[test]
    fn editor_failures_keep_draft_and_never_repeat_save() {
        for code in ["invalid_params", "operation_failed", "transport_failed"] {
            let root = tempfile::tempdir().unwrap();
            let history = root.path().join("requests.jsonl");
            let python =
                PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
            let mut command = Command::new(&python);
            command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[1], 'a', encoding='utf-8') as history:
        history.write(json.dumps(request) + '\n')
    result = {'scripts': [{'script_name':'renamed', 'display_name':'renamed', 'script_path':'new.py', 'adapted':False}]} if request['method'] == 'app.snapshot' else {'script': {'script_name':'renamed','display_name':'renamed','script_path':'new.py','adapted':False}, 'dailies':[], 'weeklies':[]}
    print(json.dumps({'protocol_version':1,'id':request['id'],'result':result}), flush=True)
"#]).arg(&history);
            let mut app = test_app(command, root.path(), python);
            app.editor = Some(ScriptEditor::new(serde_json::from_value(json!({
                "script_name":"test", "script":{"display_name":"renamed", "script_path":"new.py"},
                "weekly_timeouts":[60,60,60,60,60,60,60], "switches":[]
            })).unwrap()));
            app.receive(Reply {
                method: "script.edit_save".into(),
                pid: 0,
                diagnostics: String::new(),
                result: Err(Failure {
                    code: code.into(),
                    message: "save failed".into(),
                    refresh_required: code == "operation_failed",
                }),
            });
            assert_eq!(
                app.editor.as_ref().unwrap().needs_reload,
                code != "invalid_params"
            );
            if code == "operation_failed" {
                for _ in 0..2 {
                    let reply = app
                        .backend
                        .as_ref()
                        .unwrap()
                        .replies
                        .recv_timeout(Duration::from_secs(10))
                        .unwrap();
                    app.receive(reply);
                }
                assert_eq!(app.selected.as_deref(), Some("renamed"));
                assert!(app.editor.as_ref().unwrap().needs_reload);
                assert!(app.error.as_ref().unwrap().contains("save failed"));
            }
            drop(app);
            if code == "operation_failed" {
                let requests: Vec<Value> = std::fs::read_to_string(history)
                    .unwrap()
                    .lines()
                    .map(|line| serde_json::from_str(line).unwrap())
                    .collect();
                assert_eq!(requests.len(), 2);
                assert_eq!(requests[0]["method"], "app.snapshot");
                assert_eq!(requests[1]["method"], "script.view");
            } else {
                assert!(!history.exists());
            }
        }
    }

    #[test]
    fn acknowledged_write_refreshes_once_without_replay_on_read_failure() {
        for scenario in ["ok", "error", "malformed"] {
            let root = tempfile::tempdir().unwrap();
            let history = root.path().join("requests.jsonl");
            let python =
                PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
            let mut command = Command::new(&python);
            command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[1], 'a', encoding='utf-8') as history:
        history.write(json.dumps(request) + '\n')
    response = {'protocol_version': 1, 'id': request['id']}
    if request['method'] == 'daily.select':
        response['result'] = None
    elif sys.argv[2] == 'error':
        response['error'] = {'code': 'operation_failed', 'message': 'read failed', 'refresh_required': False}
    elif sys.argv[2] == 'malformed':
        response['result'] = None
    else:
        response['result'] = {'script': {'script_name': 'test', 'display_name': 'Test', 'script_path': 'test.exe', 'adapted': True}, 'dailies': [], 'weeklies': []}
    print(json.dumps(response), flush=True)
"#]);
            command.arg(&history).arg(scenario);
            let mut app = test_app(command, root.path(), python);
            app.request("daily.select", json!({"script_name": "test"}));
            for _ in 0..2 {
                let reply = app
                    .backend
                    .as_ref()
                    .unwrap()
                    .replies
                    .recv_timeout(Duration::from_secs(10))
                    .unwrap();
                app.receive(reply);
            }
            assert!(!app.busy);
            assert!(!app.write_confirmed);
            if scenario == "ok" {
                assert!(app.view.is_some());
                assert!(app.error.is_none());
            } else {
                assert!(app.view.is_none());
                assert!(
                    app.error
                        .as_ref()
                        .unwrap()
                        .starts_with("已保存，但刷新失败")
                );
            }
            drop(app);
            let requests: Vec<Value> = std::fs::read_to_string(history)
                .unwrap()
                .lines()
                .map(|line| serde_json::from_str(line).unwrap())
                .collect();
            assert_eq!(requests.len(), 2, "{scenario}: do not replay or retry");
            assert_eq!(requests[0]["method"], "daily.select");
            assert_eq!(requests[1]["method"], "script.view");
            assert_eq!(requests[1]["params"]["script_name"], "test");
        }
    }
}
