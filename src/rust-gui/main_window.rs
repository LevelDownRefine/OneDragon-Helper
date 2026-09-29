use crate::dialogs::backup_dialog::{BackupAction, BackupDialog};
use crate::dialogs::config_dialog::{SettingsAction, SettingsDialog, SettingsView};
use crate::dialogs::daily_plan_dialog::DailyView;
use crate::dialogs::drop_dialog::DropDialog;
use crate::dialogs::list_dialog::{ListAction, ListDialog};
use crate::dialogs::run_confirm_dialog::{RunAction, RunDialog, RunView};
use crate::dialogs::script_config_dialog::{EditAction, EditView, ScriptEditor};
use crate::dialogs::startup_dialog::StartupDialog;
use crate::dialogs::update_dialog::{UpdateAction, UpdateDialog, UpdateView};
use crate::file_drop::FileDrop;
use crate::main_window::controllers::launch::LaunchJob;
use crate::main_window::controllers::links::{OpenJob, Target};
use crate::runtime::BackendProgram;
#[path = "controllers/mod.rs"]
pub(crate) mod controllers;
use crate::dialogs::wallpaper_dialog::{WallpaperAction, WallpaperDialog};
use controllers::{Action, Presentation, View};
use eframe::egui;
use onedragon_rust_gui::{
    backend::{Backend, Failure, Reply, Request},
    model::{Script, ScriptView, Snapshot},
};
use serde_json::{Value, json};
use std::{path::PathBuf, process::Command, time::Instant};

pub struct Settings {
    pub project_root: PathBuf,
    pub backend: BackendProgram,
    pub font: Option<PathBuf>,
    pub demo: bool,
    pub skip_startup: bool,
    #[cfg(feature = "capture")]
    pub capture: Option<PathBuf>,
    #[cfg(feature = "capture")]
    pub capture_editor: bool,
    #[cfg(feature = "capture")]
    pub capture_list: bool,
    #[cfg(feature = "capture")]
    pub capture_run: bool,
    #[cfg(feature = "capture")]
    pub capture_settings: bool,
    #[cfg(feature = "capture")]
    pub capture_plan: bool,
    #[cfg(feature = "capture")]
    pub capture_restore: bool,
    #[cfg(feature = "capture")]
    pub capture_drop: Vec<PathBuf>,
    #[cfg(feature = "capture")]
    pub capture_game_icon: bool,
    #[cfg(feature = "capture")]
    pub capture_wallpaper: bool,
    #[cfg(feature = "capture")]
    pub capture_update: bool,
}

impl Settings {
    fn command(&self) -> Command {
        let mut command = self.backend.command(&self.project_root);
        command.env(
            "ODH_SHUTDOWN_UI",
            std::env::current_exe().expect("current executable path"),
        );
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
    launch_job: Option<LaunchJob>,
    launched: Vec<std::process::Child>,
    editor: Option<ScriptEditor>,
    list_dialog: Option<ListDialog>,
    run_dialog: Option<RunDialog>,
    settings_dialog: Option<SettingsDialog>,
    backup_dialog: Option<BackupDialog>,
    update_dialog: Option<UpdateDialog>,
    open_update_after_snapshot: bool,
    startup_dialog: Option<StartupDialog>,
    file_drop: Option<FileDrop>,
    drop_dialog: Option<DropDialog>,
    wallpaper_dialog: Option<WallpaperDialog>,
    wallpaper_pending: Option<String>,
    open_wallpaper_after_snapshot: bool,
    refresh_settings_run: bool,
    open_settings_after_snapshot: bool,
    open_editor_after_snapshot: bool,
    #[cfg(feature = "capture")]
    capture_requested: bool,
    #[cfg(feature = "capture")]
    capture_ready_at: Option<Instant>,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, settings: Settings, started: Instant) -> Self {
        #[cfg(windows)]
        if let Some(window) = cc.winit_window() {
            use winit::platform::windows::{CornerPreference, WindowExtWindows};
            // eframe enables a native shadow that leaves a 1px non-client edge.
            // The transparent main window draws its own rounded outline.
            window.set_undecorated_shadow(false);
            window.set_border_color(None);
            window.set_corner_preference(CornerPreference::DoNotRound);
        }
        crate::theme::configure(&cc.egui_ctx);
        let font_error = install_font(&cc.egui_ctx, settings.font.as_ref()).err();
        let file_drop = FileDrop::new(cc).map_err(|error| {
            log::warn!("原生拖放不可用，将使用框架拖放：{error}");
            error
        });
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
            launch_job: None,
            launched: Vec::new(),
            editor: None,
            list_dialog: None,
            run_dialog: None,
            settings_dialog: None,
            backup_dialog: None,
            update_dialog: None,
            open_update_after_snapshot: false,
            startup_dialog: None,
            file_drop: file_drop.ok(),
            drop_dialog: None,
            wallpaper_dialog: None,
            wallpaper_pending: None,
            open_wallpaper_after_snapshot: false,
            refresh_settings_run: false,
            open_settings_after_snapshot: false,
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
                "app.snapshot"
                    | "script.view"
                    | "script.target"
                    | "script.icon_path"
                    | "wallpaper.current"
                    | "wallpaper.view"
                    | "script.edit_view"
                    | "script.launch_target"
                    | "run.view"
                    | "settings.view"
                    | "plan.view"
                    | "job.poll"
                    | "update.view"
                    | "startup.view"
                    | "run.saved"
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
        } else {
            self.write_confirmed = false;
        }
    }

    fn fail(&mut self, mut failure: Failure) {
        if self.drop_dialog.as_ref().is_some_and(DropDialog::awaiting) {
            self.busy = false;
            self.receive_drop(Err(failure));
            return;
        }
        if self.write_confirmed {
            failure.message = format!("已保存，但刷新失败：{}", failure.message);
        }
        self.write_confirmed = false;
        self.open_job = None;
        self.launch_job = None;
        self.busy = false;
        self.view = None;
        self.status = "操作失败 · 请刷新".into();
        self.ui.toast(&failure.message);
        if let Some(editor) = &mut self.editor {
            editor.failure(failure.message.clone(), true);
        }
        if let Some(dialog) = &mut self.list_dialog {
            dialog.failure(failure.message.clone(), true);
        }
        if let Some(dialog) = &mut self.run_dialog {
            dialog.failure(failure.message.clone(), true);
        }
        if let Some(dialog) = &mut self.settings_dialog {
            dialog.failure(failure.message.clone(), true);
        }
        if let Some(dialog) = &mut self.backup_dialog {
            dialog.failure(failure.message.clone());
        }
        if let Some(dialog) = &mut self.update_dialog {
            dialog.failure(failure.message.clone(), true);
        }
        if let Some(dialog) = &mut self.wallpaper_dialog {
            dialog.failure(failure.message.clone(), true);
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
        if reply.method.starts_with("wallpaper.") {
            self.receive_wallpaper(&reply.method, reply.result);
            return;
        }
        if reply.method.starts_with("update.")
            || (self.update_dialog.is_some()
                && matches!(reply.method.as_str(), "job.poll" | "job.cancel"))
        {
            self.receive_update(&reply.method, reply.result);
            return;
        }
        if reply.method == "script.icon_path" {
            #[derive(serde::Deserialize)]
            struct IconPath {
                script_name: String,
                path: Option<PathBuf>,
            }
            match reply.result.and_then(|value| {
                serde_json::from_value::<IconPath>(value)
                    .map_err(|error| Failure::transport(error.to_string()))
            }) {
                Ok(icon) => self.ui.set_game_icon(icon.script_name, icon.path),
                Err(failure) => {
                    log::warn!("游戏图标路径不可用：{}", failure.message);
                    if failure.code == "transport_failed" {
                        self.backend = None;
                    }
                    if let Some(name) = &self.selected {
                        self.ui.set_game_icon(name.clone(), None);
                    }
                }
            }
            self.status = if self.backend.is_some() {
                "已同步"
            } else {
                "连接中断 · 请刷新"
            }
            .into();
            return;
        }
        if reply.method == "script.add" && self.drop_dialog.is_some() {
            self.receive_drop(reply.result);
            return;
        }
        let result = match reply.result {
            Ok(value) => value,
            Err(failure) => {
                if reply.method.starts_with("settings.") || reply.method.starts_with("plan.") {
                    let reload = failure.refresh_required
                        || failure.code == "transport_failed"
                        || self.write_confirmed;
                    self.fail(failure);
                    if let Some(dialog) = &mut self.settings_dialog {
                        dialog.failure(self.error.clone().unwrap(), reload);
                    }
                    self.refresh_settings_run = false;
                    return;
                }
                if matches!(reply.method.as_str(), "run.view" | "run.prepare") {
                    let reload = failure.refresh_required || failure.code == "transport_failed";
                    let message = failure.message.clone();
                    self.fail(failure);
                    if let Some(dialog) = &mut self.run_dialog {
                        dialog.failure(message, reload);
                    }
                    return;
                }
                if matches!(
                    reply.method.as_str(),
                    "script.add" | "script.remove" | "script.reorder"
                ) {
                    let needs_reload =
                        failure.refresh_required || failure.code == "transport_failed";
                    let message = failure.message.clone();
                    self.fail(failure);
                    if let Some(dialog) = &mut self.list_dialog {
                        dialog.failure(message, needs_reload);
                    }
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                    return;
                }
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
                    let previous = self.selected.clone();
                    self.ui.refresh_icons(snapshot.default_icon_path);
                    self.scripts = snapshot.scripts;
                    self.ui.reconcile_scripts(&self.scripts);
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
                    self.wallpaper_pending = self.selected.clone();
                    if previous != self.selected {
                        self.select_wallpaper();
                    }
                    if std::mem::take(&mut self.open_settings_after_snapshot) {
                        self.request("settings.view", json!({}));
                    } else if std::mem::take(&mut self.open_editor_after_snapshot) {
                        if let Some(name) = self.selected.clone() {
                            self.request("script.edit_view", json!({"script_name": name}));
                        } else {
                            self.editor = None;
                            self.ui.toast("脚本已不存在");
                        }
                    } else if std::mem::take(&mut self.open_update_after_snapshot) {
                        self.request("update.view", json!({}));
                    } else if std::mem::take(&mut self.open_wallpaper_after_snapshot) {
                        if let Some(name) = self.selected.clone() {
                            self.request("wallpaper.view", json!({"script_name":name}));
                        }
                    } else {
                        self.refresh_view();
                    }
                }
                Err(err) => self.fail(Failure::transport(format!("脚本列表数据无效：{err}"))),
            }
        } else if matches!(
            reply.method.as_str(),
            "script.edit_view"
                | "script.edit_save"
                | "script.add"
                | "script.remove"
                | "script.reorder"
        ) {
            self.receive_script_edit(&reply.method, result);
        } else if matches!(
            reply.method.as_str(),
            "backup.start" | "restore.start" | "job.poll"
        ) {
            self.receive_backup(&reply.method, result);
        } else if matches!(reply.method.as_str(), "plan.view" | "plan.save") {
            self.receive_plan(&reply.method, result);
        } else if matches!(
            reply.method.as_str(),
            "settings.view" | "startup.view" | "settings.run_save" | "settings.startup_save"
        ) {
            self.receive_config(&reply.method, result);
        } else if matches!(
            reply.method.as_str(),
            "run.view" | "script.launch_target" | "run.prepare" | "run.saved"
        ) {
            self.receive_launch(&reply.method, result);
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
                        #[cfg(feature = "capture")]
                        {
                            self.ui.capture_game_icon =
                                self.settings.capture.is_some() && self.settings.capture_game_icon;
                        }
                        self.ready_logged = true;
                        log::info!(
                            "[startup] first task ready {:.2} ms",
                            self.started.elapsed().as_secs_f64() * 1000.0
                        );
                        if !self.settings.skip_startup
                            && !self.ui.enabled_names(&self.scripts).is_empty()
                        {
                            self.request("startup.view", json!({}));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some()
                            && self.settings.capture_settings
                            && !self.busy
                        {
                            self.request("settings.view", json!({}));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && self.settings.capture_editor {
                            self.request("script.edit_view", json!({"script_name": self.selected}));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && self.settings.capture_list {
                            self.ui.open_manual_menu();
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some()
                            && self.settings.capture_wallpaper
                            && !self.busy
                        {
                            self.request("wallpaper.view", json!({"script_name":self.selected}));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some()
                            && self.settings.capture_update
                            && !self.busy
                        {
                            self.request("update.view", json!({}));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && !self.settings.capture_drop.is_empty()
                        {
                            self.start_drop(Ok(self.settings.capture_drop.clone()));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some()
                            && self.settings.capture_run
                            && !self.busy
                        {
                            self.request("run.view",json!({"script_names":self.scripts.iter().map(|script|script.script_name.clone()).collect::<Vec<_>>()}));
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

    fn operation_active(&self) -> bool {
        self.backup_dialog
            .as_ref()
            .is_some_and(BackupDialog::active)
            || self.drop_dialog.as_ref().is_some_and(DropDialog::active)
            || self
                .update_dialog
                .as_ref()
                .is_some_and(UpdateDialog::active)
    }
}

impl Drop for App {
    fn drop(&mut self) {
        for child in self.launched.drain(..) {
            crate::main_window::controllers::launch::reap_in_background(child);
        }
    }
}

impl eframe::App for App {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let dropped = if let Some(handler) = &self.file_drop {
            handler.poll(ctx)
        } else {
            crate::file_drop::fallback(ctx)
        };
        if let Some(paths) = dropped {
            self.start_drop(paths);
        }
        if self.operation_active() {
            ctx.request_repaint_after(std::time::Duration::from_millis(200));
        }
        if self.operation_active() && ctx.input(|input| input.viewport().close_requested()) {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.ui.toast("操作进行中，请等待完成后关闭");
        }
        if let Some(result) = self.launch_job.as_ref().and_then(LaunchJob::poll) {
            self.launch_job = None;
            self.busy = false;
            match result {
                Ok(child) => {
                    if let Some(child) = child {
                        self.launched.push(child);
                    }
                    self.status = "已同步".into();
                    self.ui.toast("已发起启动");
                }
                Err(error) => {
                    self.status = "启动失败".into();
                    self.ui.toast(error);
                }
            }
        }
        for index in (0..self.launched.len()).rev() {
            match self.launched[index].try_wait() {
                Ok(Some(status)) => {
                    drop(self.launched.swap_remove(index)); // try_wait already reaped it.
                    if !status.success() {
                        self.ui
                            .toast(format!("脚本退出异常（{status}），请查看运行日志"));
                    }
                }
                Err(error) => {
                    crate::main_window::controllers::launch::reap_in_background(
                        self.launched.swap_remove(index),
                    );
                    self.ui.toast(format!("无法读取脚本状态：{error}"));
                }
                Ok(None) => {}
            }
        }
        if !self.launched.is_empty() {
            ctx.request_repaint_after(std::time::Duration::from_millis(250));
        }
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
        if self.update_dialog.as_ref().is_some_and(UpdateDialog::ready) {
            // Ready is acknowledged before releasing the CLI runtime lease and closing the GUI.
            self.backend = None;
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            return;
        }
        if !self.busy
            && let Some(request) = self.drop_dialog.as_mut().and_then(DropDialog::next)
        {
            self.request(&request.method, request.params);
        }
        if !self.busy
            && let Some(request) = self.backup_dialog.as_mut().and_then(BackupDialog::poll)
        {
            self.request(&request.method, request.params);
        }
        if self.can_drop() {
            if let Some(name) = self.wallpaper_pending.take() {
                self.request("wallpaper.current", json!({"script_name":name}));
            } else if let Some(request) = self.ui.wallpaper.take_cache() {
                self.request(&request.method, request.params);
            }
        } else if !self.busy
            && self.backend.is_some()
            && self.wallpaper_dialog.is_some()
            && let Some(request) = self.ui.wallpaper.take_cache()
        {
            self.request(&request.method, request.params);
        }
        if !self.busy
            && let Some(request) = self.update_dialog.as_mut().and_then(UpdateDialog::poll)
        {
            self.request(&request.method, request.params);
        }
        #[cfg(feature = "capture")]
        if let Some(path) = &self.settings.capture {
            for event in ctx.input(|input| input.events.clone()) {
                if let egui::Event::Screenshot { image, .. } = event {
                    log::info!(
                        "[startup] task frame captured {:.2} ms",
                        self.started.elapsed().as_secs_f64() * 1000.0
                    );
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
        if let Some(handler) = &self.file_drop {
            handler.set_enabled(self.can_drop());
        }
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
                busy: self.busy || self.operation_active(),
                block_close: self.operation_active(),
                status: &self.status,
                demo: self.settings.demo,
            },
        );
        for action in actions {
            match action {
                Action::Select(name) => {
                    self.selected = Some(name);
                    self.wallpaper_pending = self.selected.clone();
                    self.select_wallpaper();
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
                Action::AddScript => {
                    self.ui.close_menu();
                    self.list_dialog = Some(ListDialog::add());
                }
                Action::RemoveScript(name) => {
                    self.ui.close_menu();
                    if self.scripts.len() <= 1 {
                        self.ui.toast("至少保留一个脚本，无法删除");
                    } else if let Some(script) = self
                        .scripts
                        .iter()
                        .find(|script| script.script_name == name)
                    {
                        self.list_dialog =
                            Some(ListDialog::remove(name, script.display_name.clone()));
                    }
                }
            }
        }
        self.show_config(ui);
        self.show_backup(ui);
        self.show_update(ui);
        self.show_startup(ui);
        self.show_script_config(ui);
        self.show_script_list(ui);
        self.show_run_confirm(ui);
        self.show_wallpaper(ui);
        if self
            .drop_dialog
            .as_mut()
            .is_some_and(|dialog| dialog.show(ui.ctx(), self.busy))
        {
            self.drop_dialog = None;
        }
        if let Some(handler) = &self.file_drop {
            handler.set_enabled(self.can_drop());
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
            && (!self.settings.capture_game_icon || self.ui.capture_icon_ready)
            && (!self.settings.capture_wallpaper
                || (self.wallpaper_dialog.is_some() && self.ui.wallpaper.ready && !self.busy))
            && (!self.settings.capture_editor || self.editor.is_some())
            && (!self.settings.capture_run || self.run_dialog.is_some())
            && (!self.settings.capture_settings || self.settings_dialog.is_some())
            && (!self.settings.capture_restore || self.backup_dialog.is_some())
            && (!self.settings.capture_update || self.update_dialog.is_some())
            && (self.settings.capture_drop.is_empty()
                || (self
                    .drop_dialog
                    .as_ref()
                    .is_some_and(|dialog| !dialog.active())
                    && !self.busy))
            && (!self.settings.capture_plan
                || self
                    .settings_dialog
                    .as_ref()
                    .is_some_and(SettingsDialog::is_daily))
        {
            let ready = self.capture_ready_at.get_or_insert_with(Instant::now);
            let settling = if std::env::var_os("ODH_GUI_MEASURE_STARTUP").as_deref()
                == Some(std::ffi::OsStr::new("1"))
            {
                std::time::Duration::ZERO
            } else {
                std::time::Duration::from_millis(250)
            };
            if ready.elapsed() >= settling {
                self.capture_requested = true;
                ui.ctx()
                    .send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
            } else {
                ui.ctx()
                    .request_repaint_after(std::time::Duration::from_millis(50));
            }
        }
        #[cfg(feature = "capture")]
        if self.settings.capture.is_some() && self.capture_requested {
            // wgpu map callbacks need further queue submissions while the UI is idle.
            ui.ctx()
                .request_repaint_after(std::time::Duration::from_millis(16));
        }
    }
}

pub(crate) fn install_font(ctx: &egui::Context, explicit: Option<&PathBuf>) -> Result<(), String> {
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
#[path = "../../tests/rust-gui/main_window.rs"]
mod tests;
