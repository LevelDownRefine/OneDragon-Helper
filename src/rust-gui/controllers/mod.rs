use crate::icons::Assets;
pub(crate) mod background;
pub(crate) mod backup;
pub(crate) mod daily_plan;
pub(crate) mod game_list;
pub(crate) mod launch;
pub(crate) mod links;
pub(crate) mod task_card;
pub(crate) mod update;
pub(crate) mod window;

use crate::theme::*;
use eframe::egui::{self, Id, Rect, Sense, Ui, Vec2, pos2, vec2};
use onedragon_rust_gui::{
    backend::Request,
    model::{Script, ScriptView},
};
use serde_json::json;
use std::collections::HashSet;
use std::time::{Duration, Instant};

pub enum Action {
    Select(String),
    Request(Request),
    Refresh,
    Diagnostics,
    AddScript,
    RemoveScript(String),
}

pub struct Presentation<'a> {
    pub scripts: &'a [Script],
    pub selected: Option<&'a str>,
    pub view: Option<&'a ScriptView>,
    pub busy: bool,
    pub block_close: bool,
    pub status: &'a str,
    pub demo: bool,
}

#[derive(Clone, Debug, PartialEq)]
enum MenuKind {
    Daily(String),
    Weekly(String),
    Start(String),
}

#[derive(Clone)]
struct Menu {
    kind: MenuKind,
    anchor: Rect,
    parent: Option<usize>,
}

pub struct View {
    assets: Assets,
    pub wallpaper: crate::main_window::controllers::background::Backdrop,
    icons: crate::icons::Icons,
    default_icon_path: Option<std::path::PathBuf>,
    game_icon: Option<(String, Option<std::path::PathBuf>)>,
    game_hover: Option<String>,
    #[cfg(feature = "capture")]
    pub capture_game_icon: bool,
    #[cfg(feature = "capture")]
    pub capture_icon_ready: bool,
    menu: Option<Menu>,
    toast: Option<(String, Instant)>,
    pub diagnostics_open: bool,
    control_mode: bool,
    disabled: HashSet<String>,
    dragging: Option<String>,
}

impl View {
    pub fn new(ctx: &egui::Context) -> Self {
        Self {
            assets: Assets::new(ctx),
            wallpaper: crate::main_window::controllers::background::Backdrop::new(ctx.clone()),
            icons: crate::icons::Icons::new(ctx.clone()),
            default_icon_path: None,
            game_icon: None,
            game_hover: None,
            #[cfg(feature = "capture")]
            capture_game_icon: false,
            #[cfg(feature = "capture")]
            capture_icon_ready: false,
            menu: None,
            toast: None,
            diagnostics_open: false,
            control_mode: false,
            disabled: HashSet::new(),
            dragging: None,
        }
    }

    pub fn close_menu(&mut self) {
        self.menu = None;
        self.control_mode = false;
        self.dragging = None;
    }

    #[cfg(feature = "capture")]
    pub fn open_manual_menu(&mut self) {
        self.control_mode = true;
    }

    pub fn toast(&mut self, message: impl Into<String>) {
        self.toast = Some((message.into(), Instant::now()));
    }

    pub fn show(&mut self, ui: &mut Ui, data: Presentation<'_>) -> Vec<Action> {
        if let Some(error) = self.wallpaper.poll(ui.ctx()) {
            log::warn!("{error}");
            self.toast(error);
        }
        self.icons.poll(ui.ctx());
        let mut actions = Vec::new();
        let screen = ui.max_rect();
        self.background(ui, screen);
        // Register background drag first so every foreground control wins the hit test.
        let drag = ui.interact(screen, Id::new("window-drag"), Sense::drag());
        if drag.drag_started() {
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::StartDrag);
        }
        self.window_controls(ui, screen, &data, &mut actions);
        self.toolbar(ui, screen, &data, &mut actions);
        self.launch_button(ui, screen, &data, &mut actions);
        self.card(ui, &data, &mut actions);
        self.sidebar(ui, &data, &mut actions);
        if data.busy {
            self.menu = None;
        }
        if let Some(view) = data.view {
            self.popup(ui.ctx(), view, &mut actions);
        } else {
            self.menu = None;
        }
        if let Some((message, started)) = &self.toast
            && started.elapsed() < Duration::from_secs(4)
        {
            let position = pos2(screen.center().x, screen.bottom() - 26.0);
            egui::Area::new(Id::new("toast"))
                .order(egui::Order::Tooltip)
                .pivot(egui::Align2::CENTER_BOTTOM)
                .fixed_pos(position)
                .show(ui.ctx(), |ui| {
                    egui::Frame::new()
                        .fill(PANEL)
                        .stroke(egui::Stroke::new(1.0, BORDER))
                        .corner_radius(12)
                        .inner_margin(14)
                        .show(ui, |ui| {
                            ui.set_max_width(620.0);
                            ui.label(message);
                        });
                });
            ui.ctx()
                .request_repaint_after(Duration::from_secs(4).saturating_sub(started.elapsed()));
        }
        actions
    }

    fn icon_button(&self, ui: &mut Ui, icon: &str, bounds: Rect, hint: &str, hover: bool) -> bool {
        let response = ui.interact(bounds, Id::new(("icon", hint)), Sense::click());
        if response.hovered() && hover {
            ui.painter().rect_filled(bounds, 9, HOVER);
        }
        let size = if bounds.width() > 40.0 { 32.0 } else { 26.0 };
        self.assets.icon(
            ui,
            icon,
            Rect::from_center_size(bounds.center(), vec2(size, size)),
        );
        response.on_hover_text(hint).clicked()
    }
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/controllers/mod.rs"]
mod tests;
