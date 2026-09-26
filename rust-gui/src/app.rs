use eframe::egui::{self, Color32, RichText};
use onedragon_rust_gui::{
    backend::{Backend, Failure, Reply, Request},
    model::{Daily, Script, ScriptView, Snapshot, Weekly, start_label},
};
use serde_json::{Value, json};
use std::{path::PathBuf, process::Command, time::Instant};

const ACCENT: Color32 = Color32::from_rgb(117, 216, 178);
const CARD: Color32 = Color32::from_rgb(31, 39, 48);

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
    #[cfg(feature = "capture")]
    capture_requested: bool,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, settings: Settings, started: Instant) -> Self {
        cc.egui_ctx.set_theme(egui::Theme::Dark);
        cc.egui_ctx
            .set_visuals_of(egui::Theme::Dark, egui::Visuals::dark());
        cc.egui_ctx.style_mut_of(egui::Theme::Dark, |style| {
            style.spacing.item_spacing = egui::vec2(12.0, 12.0);
            style.spacing.button_padding = egui::vec2(14.0, 9.0);
            style.visuals.selection.bg_fill = Color32::from_rgb(41, 91, 75);
            style.visuals.selection.stroke.color = ACCENT;
            style.visuals.panel_fill = Color32::from_rgb(21, 27, 34);
            style
                .text_styles
                .insert(egui::TextStyle::Body, egui::FontId::proportional(16.0));
            style
                .text_styles
                .insert(egui::TextStyle::Button, egui::FontId::proportional(15.0));
            style
                .text_styles
                .insert(egui::TextStyle::Heading, egui::FontId::proportional(26.0));
        });
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

    fn header(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("OneDragon").size(24.0).strong());
            ui.label(RichText::new("RUST PREVIEW").small().color(ACCENT));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui
                    .add_enabled(!self.busy, egui::Button::new("刷新 / 重连"))
                    .clicked()
                {
                    self.error = None;
                    self.view = None;
                    if self.backend.is_none() {
                        self.connect();
                    } else {
                        self.request("app.snapshot", json!({}));
                    }
                }
                ui.label(RichText::new(&self.status).color(ACCENT));
                if self.busy {
                    ui.spinner();
                }
            });
        });
    }

    fn sidebar(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("脚本").small().color(Color32::GRAY));
        ui.add_space(8.0);
        let mut selected = None;
        egui::ScrollArea::vertical()
            .id_salt("scripts")
            .show(ui, |ui| {
                for script in &self.scripts {
                    let active = self.selected.as_ref() == Some(&script.script_name);
                    if ui
                        .add_enabled(
                            !self.busy,
                            egui::Button::new(&script.display_name)
                                .selected(active)
                                .min_size(egui::vec2(ui.available_width(), 48.0)),
                        )
                        .clicked()
                    {
                        selected = Some(script.script_name.clone());
                    }
                }
            });
        if let Some(name) = selected {
            self.selected = Some(name);
            self.error = None;
            if self.backend.is_some() {
                self.refresh_view();
            } else {
                self.connect();
            }
        }
    }

    fn content(&mut self, ui: &mut egui::Ui) {
        if let Some(error) = &self.error {
            egui::Frame::new()
                .fill(Color32::from_rgb(72, 42, 39))
                .inner_margin(12)
                .corner_radius(8)
                .show(ui, |ui| {
                    ui.label(error);
                    ui.small("写入可能已完成，请先刷新确认状态，再决定是否重试。");
                });
            ui.add_space(8.0);
        }
        let Some(view) = self.view.clone() else {
            ui.add_space(40.0);
            if self.busy {
                ui.heading("正在读取任务…");
            } else if self.scripts.is_empty() {
                ui.heading("还没有配置脚本");
                ui.label("请先在原版助手中添加脚本，然后点击刷新。");
            } else {
                ui.heading("请刷新以读取实际配置");
            }
            return;
        };
        ui.heading(&view.script.display_name);
        ui.label(
            RichText::new(&view.script.script_path)
                .small()
                .color(Color32::GRAY),
        );
        ui.add_space(18.0);
        if !view.script.adapted {
            ui.label("此脚本尚未提供任务卡配置接口。");
            return;
        }
        let mut action = None;
        ui.add_enabled_ui(!self.busy, |ui| {
            ui.label(RichText::new("日常任务").strong().size(18.0));
            for daily in &view.dailies {
                ui.push_id((&view.script.script_name, &daily.daily_name), |ui| {
                    if let Some(request) = daily_row(ui, &view.script.script_name, daily) {
                        action = Some(request);
                    }
                });
            }
            if view.dailies.is_empty() {
                ui.label("暂无可配置日常");
            }
            if !view.weeklies.is_empty() {
                ui.add_space(16.0);
                ui.label(RichText::new("周常任务").strong().size(18.0));
                for weekly in &view.weeklies {
                    ui.push_id((&view.script.script_name, &weekly.weekly_name), |ui| {
                        if let Some(request) = weekly_row(ui, &view.script.script_name, weekly) {
                            action = Some(request);
                        }
                    });
                }
            }
        });
        if let Some(request) = action {
            self.error = None;
            self.request(&request.method, request.params);
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

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if self.first_ui {
            self.first_ui = false;
            log::info!(
                "[startup] first UI callback {:.2} ms",
                self.started.elapsed().as_secs_f64() * 1000.0
            );
        }
        egui::Panel::top("header")
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(26, 33, 41))
                    .inner_margin(18),
            )
            .show(ui, |ui| self.header(ui));
        egui::Panel::bottom("footer")
            .frame(egui::Frame::new().inner_margin(12))
            .show(ui, |ui| {
                ui.small(if self.settings.demo {
                    "演示配置 · 修改仅写入临时目录"
                } else {
                    "任务卡预览 · 修改会保存到脚本配置；启动、设置等功能请使用原版助手"
                });
                ui.collapsing("连接诊断", |ui| {
                    ui.small(format!("Python CLI PID: {}", self.pid));
                    ui.small(self.settings.project_root.display().to_string());
                    egui::ScrollArea::vertical()
                        .max_height(120.0)
                        .show(ui, |ui| {
                            ui.small(&self.diagnostics);
                        });
                });
            });
        egui::Panel::left("sidebar")
            .exact_size(210.0)
            .resizable(false)
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(26, 33, 41))
                    .inner_margin(16),
            )
            .show(ui, |ui| self.sidebar(ui));
        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(21, 27, 34))
                    .inner_margin(28),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.content(ui));
            });
        #[cfg(feature = "capture")]
        if self.settings.capture.is_some() && self.ready_logged && !self.capture_requested {
            self.capture_requested = true;
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
        }
    }
}

fn daily_row(ui: &mut egui::Ui, script: &str, daily: &Daily) -> Option<Request> {
    let mut action = None;
    egui::Frame::new()
        .fill(CARD)
        .inner_margin(16)
        .corner_radius(10)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
            ui.label(RichText::new(&daily.daily_name).strong());
            if let Some(mut enabled) = daily.enabled
                && ui.checkbox(&mut enabled, "启用").changed() {
                    action = Some(Request { method: "daily.enable".into(), params: json!({
                        "script_name": script, "daily_name": daily.daily_name, "enabled": enabled
                    }) });
            }
        });
            egui::ComboBox::from_id_salt("choice")
                .width((ui.available_width() - 24.0).max(160.0))
                .height(310.0)
                .selected_text(daily.label())
                .show_ui(ui, |ui| {
                    for choice in daily.choices() {
                        let selected = daily.selected.task_name.as_ref() == Some(&choice.task_name)
                            && daily.selected.sequence == choice.sequence;
                        if ui.selectable_label(selected, &choice.label).clicked() {
                            action = Some(Request {
                                method: "daily.select".into(),
                                params: json!({
                                    "script_name": script, "daily_name": daily.daily_name,
                                    "task_name": choice.task_name, "sequence": choice.sequence
                                }),
                            });
                        }
                    }
                });
        });
    action
}

fn weekly_row(ui: &mut egui::Ui, script: &str, weekly: &Weekly) -> Option<Request> {
    let mut action = None;
    egui::Frame::new().fill(CARD).inner_margin(16).corner_radius(10).show(ui, |ui| {
        ui.set_width(ui.available_width());
        ui.horizontal(|ui| {
            ui.label(RichText::new(&weekly.weekly_name).strong());
            egui::ComboBox::from_id_salt("start").selected_text(start_label(weekly.start_day)).show_ui(ui, |ui| {
                for day in 0..=7 {
                    if ui.selectable_label(weekly.start_day == Some(day), start_label(Some(day))).clicked() {
                        action = Some(Request { method: "weekly.start".into(), params: json!({
                            "script_name": script, "weekly_name": weekly.weekly_name, "start_day": day
                        }) });
                    }
                }
            });
        });
        if let Some(options) = &weekly.options {
            egui::ComboBox::from_id_salt("task").width((ui.available_width() - 24.0).max(160.0))
                .selected_text(weekly.selected.as_deref().unwrap_or("选择副本")).show_ui(ui, |ui| {
                    for choice in &options.values {
                        if ui.selectable_label(weekly.selected.as_ref() == Some(&choice.display_name), &choice.display_name).clicked() {
                            action = Some(Request { method: "weekly.select".into(), params: json!({
                                "script_name": script, "weekly_name": weekly.weekly_name, "task_name": choice.display_name
                            }) });
                        }
                    }
                });
        }
    });
    action
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
                fonts.families.entry(family).or_default().push("cjk".into());
            }
            ctx.set_fonts(fonts);
            return Ok(());
        }
    }
    Err("Chinese font missing. Start with --font <path-to-font>.".into())
}
