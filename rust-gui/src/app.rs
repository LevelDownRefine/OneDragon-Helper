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
    ctx: egui::Context,
    ui: View,
    #[cfg(feature = "capture")]
    capture_requested: bool,
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
            ctx: cc.egui_ctx.clone(),
            ui: View::new(&cc.egui_ctx),
            #[cfg(feature = "capture")]
            capture_requested: false,
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
            self.status = if method == "app.snapshot" || method == "script.view" {
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

    fn fail(&mut self, failure: Failure) {
        self.busy = false;
        self.view = None;
        self.status = "操作失败 · 请刷新".into();
        self.ui.toast(&failure.message);
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
                    self.refresh_view();
                }
                Err(err) => self.fail(Failure::transport(format!("脚本列表数据无效：{err}"))),
            }
        } else {
            match serde_json::from_value::<ScriptView>(result) {
                Ok(view)
                    if Some(&view.script.script_name) == self.selected.as_ref()
                        && view
                            .weeklies
                            .iter()
                            .all(|weekly| weekly.start_day.is_none_or(|day| day <= 7)) =>
                {
                    self.view = Some(view);
                    self.status = "已同步".into();
                    if !self.ready_logged {
                        self.ready_logged = true;
                        log::info!(
                            "[startup] first task ready {:.2} ms",
                            self.started.elapsed().as_secs_f64() * 1000.0
                        );
                    }
                }
                Ok(_) => self.fail(Failure::transport("任务卡身份或起始日无效")),
                Err(err) => self.fail(Failure::transport(format!("任务卡数据无效：{err}"))),
            }
        }
    }
}

impl eframe::App for App {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
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
        if self.settings.capture.is_some() && self.ready_logged && !self.capture_requested {
            self.capture_requested = true;
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
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
