use crate::skin::*;
use eframe::egui::{self, Id, Rect, Sense, Ui, Vec2, pos2, vec2};
use onedragon_rust_gui::{
    backend::Request,
    model::{Daily, Script, ScriptView, Weekly, start_label},
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
    pub wallpaper: crate::wallpaper::Backdrop,
    icons: crate::native_icons::Icons,
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
    pub fn enabled_names(&self, scripts: &[Script]) -> Vec<String> {
        scripts
            .iter()
            .filter(|script| !self.disabled.contains(&script.script_name))
            .map(|script| script.script_name.clone())
            .collect()
    }

    pub fn new(ctx: &egui::Context) -> Self {
        Self {
            assets: Assets::new(ctx),
            wallpaper: crate::wallpaper::Backdrop::new(ctx.clone()),
            icons: crate::native_icons::Icons::new(ctx.clone()),
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

    pub fn refresh_icons(&mut self, default_path: Option<std::path::PathBuf>) {
        self.default_icon_path = default_path;
        self.icons.invalidate();
        self.game_icon = None;
        self.game_hover = None;
    }

    pub fn set_game_icon(&mut self, name: String, path: Option<std::path::PathBuf>) {
        self.game_icon = Some((name, path));
    }

    pub fn reconcile_scripts(&mut self, scripts: &[Script]) {
        self.disabled
            .retain(|name| scripts.iter().any(|script| &script.script_name == name));
    }

    #[cfg(feature = "capture")]
    pub fn open_manual_menu(&mut self) {
        self.control_mode = true;
    }

    pub fn rename_script(&mut self, old: &str, new: &str) {
        if self.disabled.remove(old) {
            self.disabled.insert(new.into());
        }
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
        self.controls(ui, screen, &data, &mut actions);
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

    fn background(&self, ui: &mut Ui, screen: Rect) {
        let image = self.wallpaper.texture.as_ref().or_else(|| {
            self.wallpaper
                .placeholder
                .is_none()
                .then_some(&self.assets.background)
        });
        if let Some(image) = image {
            let aspect = image.size_vec2().x / image.size_vec2().y;
            let target = screen.aspect_ratio();
            let uv_size = if aspect > target {
                vec2(target / aspect, 1.0)
            } else {
                vec2(1.0, aspect / target)
            };
            let uv = Rect::from_center_size(pos2(0.5, 0.5), uv_size);
            egui::Image::new((image.id(), screen.size()))
                .uv(uv)
                .corner_radius(16)
                .paint_at(ui, screen);
        } else {
            egui::Image::new((self.assets.gradient.id(), screen.size()))
                .corner_radius(16)
                .paint_at(ui, screen);
            if let Some(character) = &self.wallpaper.placeholder {
                ui.painter().text(
                    screen.center(),
                    egui::Align2::CENTER_CENTER,
                    character,
                    egui::FontId::proportional(320.0),
                    egui::Color32::from_white_alpha(15),
                );
            }
        }
        let mut mesh = egui::Mesh::default();
        for (fraction, alpha) in [(0.0, 31), (0.48, 0), (1.0, 77)] {
            let y = screen.top() + screen.height() * fraction;
            let color = egui::Color32::from_rgba_unmultiplied(11, 18, 32, alpha);
            mesh.colored_vertex(pos2(screen.left(), y), color);
            mesh.colored_vertex(pos2(screen.right(), y), color);
        }
        mesh.indices = vec![0, 1, 2, 1, 3, 2, 2, 3, 4, 3, 5, 4];
        ui.painter().add(egui::Shape::mesh(mesh));
    }

    fn sidebar(&mut self, ui: &mut Ui, data: &Presentation<'_>, actions: &mut Vec<Action>) {
        let height = ui.max_rect().height();
        let mut drop_index = None;
        if ui.input(|input| input.key_pressed(egui::Key::Escape)) {
            self.dragging = None;
        }
        ui.painter().rect_filled(
            rect(0.0, 0.0, 80.0, height),
            egui::CornerRadius {
                nw: 16,
                sw: 16,
                ne: 0,
                se: 0,
            },
            egui::Color32::from_rgba_unmultiplied(16, 25, 41, 230),
        );
        ui.painter().line_segment(
            [pos2(79.0, 0.0), pos2(79.0, height)],
            egui::Stroke::new(1.0, BORDER),
        );
        ui.scope_builder(
            egui::UiBuilder::new().max_rect(rect(0.0, 20.0, 80.0, height - 160.0)),
            |ui| {
                ui.spacing_mut().item_spacing.y = 0.0;
                egui::ScrollArea::vertical()
                    .id_salt("script-list")
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for (index, script) in data.scripts.iter().enumerate() {
                            let (row, _) = ui.allocate_exact_size(vec2(80.0, 64.0), Sense::hover());
                            let button =
                                Rect::from_min_size(row.min + vec2(12.0, 0.0), vec2(56.0, 56.0));
                            let active = data.selected == Some(script.script_name.as_str());
                            let response = ui.interact(
                                button,
                                Id::new(("script", &script.script_name)),
                                Sense::click_and_drag(),
                            );
                            if active {
                                ui.painter().rect_filled(
                                    rect(3.0, button.top() + 16.0, 3.0, 24.0),
                                    2,
                                    ACCENT,
                                );
                                panel(ui, button, 16, ACCENT_SOFT);
                                ui.painter().rect_stroke(
                                    button,
                                    16,
                                    egui::Stroke::new(1.0, ACCENT),
                                    egui::StrokeKind::Inside,
                                );
                            } else if response.hovered() {
                                ui.painter().rect_filled(button, 16, CONTROL);
                            }
                            let bounds = Rect::from_center_size(button.center(), vec2(40.0, 40.0));
                            if ui.is_rect_visible(button) {
                                let size = if ui.ctx().pixels_per_point() > 1.6 {
                                    256
                                } else {
                                    64
                                };
                                let texture =
                                    self.icons.get(script.icon_path.as_deref(), size).or_else(
                                        || self.icons.get(self.default_icon_path.as_deref(), size),
                                    );
                                if let Some(texture) = texture {
                                    egui::Image::new(&texture).paint_at(ui, bounds);
                                } else {
                                    self.assets.icon(ui, "script", bounds);
                                }
                            }
                            if self.disabled.contains(&script.script_name) {
                                ui.painter().rect_filled(
                                    button.shrink(4.0),
                                    10,
                                    egui::Color32::from_black_alpha(150),
                                );
                            }
                            if response.drag_started() && !data.busy {
                                self.dragging = Some(script.script_name.clone());
                                self.menu = None;
                            }
                            if self.dragging.is_some()
                                && ui.input(|input| {
                                    input.pointer.interact_pos().is_some_and(|pos| {
                                        button.contains(pos) && ui.clip_rect().contains(pos)
                                    })
                                })
                            {
                                drop_index = Some(index);
                                ui.painter().rect_stroke(
                                    button,
                                    16,
                                    egui::Stroke::new(2.0, ACCENT),
                                    egui::StrokeKind::Inside,
                                );
                            }
                            if response.clicked() && !data.busy {
                                self.menu = None;
                                if self.control_mode {
                                    if !self.disabled.remove(&script.script_name) {
                                        self.disabled.insert(script.script_name.clone());
                                    }
                                } else {
                                    actions.push(Action::Select(script.script_name.clone()));
                                }
                            }
                            response.on_hover_text(&script.display_name);
                        }
                    });
            },
        );
        let base = height - 120.0;
        ui.painter().line_segment(
            [pos2(12.0, base), pos2(68.0, base)],
            egui::Stroke::new(1.0, DIVIDER),
        );
        let grid = rect(16.0, base + 8.0, 48.0, 48.0);
        panel(
            ui,
            grid,
            14,
            if self.control_mode {
                ACCENT_SOFT
            } else {
                CONTROL
            },
        );
        if self.dragging.is_some() {
            centered(ui, grid, "删除", 14.0, egui::Color32::LIGHT_RED);
            if ui.input(|input| input.pointer.any_released()) {
                let name = self.dragging.take().expect("active drag");
                if !data.busy {
                    if ui.input(|input| {
                        input
                            .pointer
                            .interact_pos()
                            .is_some_and(|pos| grid.contains(pos))
                    }) {
                        actions.push(Action::RemoveScript(name));
                    } else if let Some(index) = drop_index {
                        let mut names: Vec<String> = data
                            .scripts
                            .iter()
                            .map(|script| script.script_name.clone())
                            .collect();
                        if let Some(source) = names.iter().position(|candidate| candidate == &name)
                            && source != index
                        {
                            names.remove(source);
                            names.insert(index, name);
                            actions.push(Action::Request(Request {
                                method: "script.reorder".into(),
                                params: json!({"script_names":names}),
                            }));
                        }
                    }
                }
            }
        } else if self.icon_button(ui, "grid", grid, "选择手动运行的脚本", true) && !data.busy
        {
            self.control_mode = !self.control_mode;
            self.menu = None;
            if self.control_mode {
                self.toast("手动选择：点击图标勾选，不影响每日计划");
            }
        }
        let bubble = rect(92.0, base + 2.0, 156.0, 60.0);
        if self.control_mode && self.dragging.is_none() {
            panel(ui, bubble, 16, PANEL);
            for (index, text) in ["全", "清", "＋"].iter().enumerate() {
                let bounds = rect(
                    bubble.left() + 16.0 + 44.0 * index as f32,
                    bubble.top() + 12.0,
                    36.0,
                    36.0,
                );
                panel(ui, bounds, 10, CONTROL);
                centered(ui, bounds, text, 16.0, TEXT);
                if ui
                    .interact(bounds, Id::new(("manual-action", index)), Sense::click())
                    .clicked()
                    && !data.busy
                {
                    match index {
                        0 => self.disabled.clear(),
                        1 => {
                            self.disabled = data
                                .scripts
                                .iter()
                                .map(|script| script.script_name.clone())
                                .collect()
                        }
                        2 => {
                            self.control_mode = false;
                            actions.push(Action::AddScript);
                        }
                        _ => unreachable!(),
                    }
                }
            }
            if ui.input(|input| {
                input.key_pressed(egui::Key::Escape)
                    || (input.pointer.any_click()
                        && input
                            .pointer
                            .interact_pos()
                            .is_some_and(|pos| pos.x > 80.0 && !bubble.contains(pos)))
            }) {
                self.control_mode = false;
            }
        }
        let batch = rect(16.0, base + 64.0, 48.0, 48.0);
        ui.painter().circle_filled(batch.center(), 24.0, BATCH);
        if self.icon_button(ui, "play_all", batch, "启动手动勾选的脚本", false) && !data.busy
        {
            let names = self.enabled_names(data.scripts);
            if names.is_empty() {
                self.toast("没有勾选手动运行的脚本");
            } else {
                actions.push(Action::Request(Request {
                    method: "run.view".into(),
                    params: json!({"script_names":names}),
                }));
            }
        }
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

    fn game_button(
        &mut self,
        ui: &mut Ui,
        bounds: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) -> bool {
        let response = ui.interact(bounds, Id::new(("icon", "启动游戏")), Sense::click());
        self.assets.icon(
            ui,
            "game",
            Rect::from_center_size(bounds.center(), vec2(26.0, 26.0)),
        );
        let hovered = response.hovered();
        #[cfg(feature = "capture")]
        let hovered = hovered || self.capture_game_icon;
        if hovered {
            ui.painter().rect_filled(bounds, 9, HOVER);
            self.assets.icon(
                ui,
                "game",
                Rect::from_center_size(bounds.center(), vec2(26.0, 26.0)),
            );
            if !data.busy
                && let Some(name) = data.selected
                && self.game_hover.as_deref() != Some(name)
            {
                self.game_hover = Some(name.into());
                actions.push(Action::Request(Request {
                    method: "script.icon_path".into(),
                    params: json!({"script_name":name}),
                }));
            }
            let path = self
                .game_icon
                .as_ref()
                .filter(|(name, _)| Some(name.as_str()) == data.selected)
                .and_then(|(_, path)| path.as_deref());
            if let Some(texture) = self.icons.get(path, 256) {
                #[cfg(feature = "capture")]
                {
                    self.capture_icon_ready = true;
                }
                egui::Area::new(Id::new("game-icon-preview"))
                    .order(egui::Order::Tooltip)
                    .fixed_pos(pos2(
                        bounds.left() - 18.0 - 144.0,
                        (bounds.center().y - 72.0).max(4.0),
                    ))
                    .interactable(false)
                    .show(ui.ctx(), |ui| {
                        egui::Frame::new()
                            .fill(CONTROL)
                            .stroke(egui::Stroke::new(1.0, BORDER))
                            .corner_radius(24)
                            .inner_margin(8)
                            .show(ui, |ui| {
                                ui.add(
                                    egui::Image::new(&texture)
                                        .fit_to_exact_size(vec2(128.0, 128.0))
                                        .corner_radius(16),
                                );
                            });
                    });
                return response.clicked();
            }
        } else {
            self.game_hover = None;
        }
        response.on_hover_text("启动游戏").clicked()
    }

    fn controls(
        &mut self,
        ui: &mut Ui,
        screen: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) {
        let dx = screen.width() - SIZE.x;
        let dy = screen.height() - SIZE.y;
        let window = rect(1136.0 + dx, 16.0, 128.0, 44.0);
        panel(ui, window, 14, PANEL);
        for (index, (icon, hint)) in [("settings", "配置"), ("min", "最小化"), ("close", "关闭")]
            .iter()
            .enumerate()
        {
            let bounds = rect(window.left() + 6.0 + index as f32 * 40.0, 22.0, 36.0, 32.0);
            if self.icon_button(ui, icon, bounds, hint, true) && (index != 0 || !data.busy) {
                match index {
                    0 => actions.push(Action::Request(Request {
                        method: "settings.view".into(),
                        params: json!({}),
                    })),
                    1 => ui
                        .ctx()
                        .send_viewport_cmd(egui::ViewportCommand::Minimized(true)),
                    _ if data.block_close => self.toast("操作进行中，请等待完成后关闭"),
                    _ => ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close),
                }
            }
        }
        let toolbar = rect(1212.0 + dx, 88.0, 52.0, 396.0);
        panel(ui, toolbar, 18, PANEL);
        for (index, (icon, name)) in [
            ("home", "游戏官网"),
            ("game", "启动游戏"),
            ("folder", "脚本目录"),
            ("log", "运行日志"),
            ("configfile", "脚本配置文件"),
            ("bili", "哔哩哔哩"),
            ("github", "GitHub"),
            ("wallpaper", "更换壁纸"),
        ]
        .iter()
        .enumerate()
        {
            let bounds = rect(
                toolbar.left() + 8.0,
                100.0 + index as f32 * 48.0,
                36.0,
                36.0,
            );
            let hint = (*name).to_owned();
            let clicked = if *icon == "game" {
                self.game_button(ui, bounds, data, actions)
            } else {
                self.icon_button(ui, icon, bounds, &hint, true)
            };
            if clicked {
                // A click wins over the optional hover read; only one CLI request per frame.
                actions.retain(|action| !matches!(action, Action::Request(request) if request.method == "script.icon_path"));
                if !data.busy {
                    if let Some(script) = data.selected {
                        actions.push(Action::Request(Request {
                            method: match *icon {
                                "game" => "script.launch_target",
                                "wallpaper" => "wallpaper.view",
                                _ => "script.target",
                            }
                            .into(),
                            params: if *icon == "wallpaper" {
                                json!({"script_name":script})
                            } else {
                                json!({"script_name": script, "target": icon})
                            },
                        }));
                    } else {
                        self.toast("尚无脚本");
                    }
                }
            }
        }
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
        let badge = rect(128.0, 24.0, if data.demo { 186.0 } else { 154.0 }, 28.0);
        panel(ui, badge, 9, PANEL);
        centered(
            ui,
            badge,
            if data.demo {
                "Rust 预览 · 演示配置"
            } else {
                "Rust 界面预览"
            },
            11.0,
            MUTED,
        );
        if ui
            .interact(badge, Id::new("diagnostics"), Sense::click())
            .on_hover_text("连接诊断")
            .clicked()
        {
            actions.push(Action::Diagnostics);
        }
    }

    fn toggle(&mut self, kind: MenuKind, anchor: Rect) {
        if self.menu.as_ref().is_some_and(|menu| menu.kind == kind) {
            self.menu = None;
        } else {
            self.menu = Some(Menu {
                kind,
                anchor,
                parent: None,
            });
        }
    }

    fn card(&mut self, ui: &mut Ui, data: &Presentation<'_>, actions: &mut Vec<Action>) {
        let count = data
            .view
            .map_or(0, |view| view.dailies.len() + view.weeklies.len());
        let height =
            (84.0 + count as f32 * ROW_HEIGHT).min(ui.max_rect().bottom() - CARD_ORIGIN.y - 16.0);
        let card = Rect::from_min_size(CARD_ORIGIN, vec2(480.0, height));
        ui.painter().rect_filled(
            card.translate(vec2(0.0, 5.0)),
            20,
            egui::Color32::from_black_alpha(40),
        );
        panel(ui, card, 20, PANEL);
        let badge = rect(card.left() + 32.0, card.top() + 18.0, 36.0, 36.0);
        ui.painter().rect_filled(badge, 10, ACCENT_SOFT);
        self.assets.icon(
            ui,
            "game",
            Rect::from_center_size(badge.center(), vec2(28.0, 28.0)),
        );
        let title = data
            .scripts
            .iter()
            .find(|script| Some(script.script_name.as_str()) == data.selected)
            .map_or("暂无脚本", |script| script.display_name.as_str());
        label(
            ui,
            rect(card.left() + 78.0, card.top() + 23.0, 164.0, 26.0),
            title,
            18.0,
            TEXT,
        );
        let refresh = rect(card.right() - 207.0, card.top() + 23.0, 175.0, 26.0);
        let response = ui.interact(refresh, Id::new("refresh"), Sense::click());
        label(
            ui,
            refresh,
            &format!("{} · 刷新", data.status),
            11.0,
            if response.hovered() { ACCENT } else { MUTED },
        );
        if response.clicked() && !data.busy {
            self.menu = None;
            actions.push(Action::Refresh);
        }
        if count == 0 {
            return;
        }
        ui.painter().line_segment(
            [card.min + vec2(20.0, 56.0), card.min + vec2(460.0, 56.0)],
            egui::Stroke::new(1.0, DIVIDER),
        );
        let rows = rect(card.left() + 20.0, card.top() + 68.0, 440.0, height - 84.0);
        if let Some(view) = data.view {
            ui.scope_builder(egui::UiBuilder::new().max_rect(rows), |ui| {
                ui.spacing_mut().item_spacing.y = 0.0;
                egui::ScrollArea::vertical()
                    .id_salt(("task-rows", data.selected))
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for daily in &view.dailies {
                            let (row, _) =
                                ui.allocate_exact_size(vec2(440.0, ROW_HEIGHT), Sense::hover());
                            self.row_heading(ui, row, "日", &daily.name);
                            let chip = Rect::from_min_size(
                                row.min + vec2(181.0, 10.0),
                                vec2(CHIP_WIDTH, 36.0),
                            );
                            let response = self.chip(
                                ui,
                                chip,
                                &daily.label(),
                                Id::new(("daily", &daily.name)),
                                daily.enabled != Some(false),
                            );
                            if response.clicked() && !data.busy {
                                self.toggle(MenuKind::Daily(daily.name.clone()), chip);
                            }
                        }
                        for weekly in &view.weeklies {
                            let (row, _) =
                                ui.allocate_exact_size(vec2(440.0, ROW_HEIGHT), Sense::hover());
                            self.row_heading(ui, row, "周", &weekly.name);
                            let has_choices = weekly
                                .options
                                .as_ref()
                                .is_some_and(|options| !options.values.is_empty());
                            let start_width = if has_choices { 106.0 } else { CHIP_WIDTH };
                            let chip = Rect::from_min_size(
                                row.min + vec2(181.0, 10.0),
                                vec2(start_width, 36.0),
                            );
                            let response = self.chip(
                                ui,
                                chip,
                                start_label(weekly.start_day),
                                Id::new(("start", &weekly.name)),
                                true,
                            );
                            if response.clicked() && !data.busy {
                                self.toggle(MenuKind::Start(weekly.name.clone()), chip);
                            }
                            if has_choices {
                                let chip = Rect::from_min_size(
                                    row.min + vec2(295.0, 10.0),
                                    vec2(106.0, 36.0),
                                );
                                let response = self.chip(
                                    ui,
                                    chip,
                                    weekly.task.as_deref().unwrap_or("选择副本"),
                                    Id::new(("weekly", &weekly.name)),
                                    true,
                                );
                                if response.clicked() && !data.busy {
                                    self.toggle(MenuKind::Weekly(weekly.name.clone()), chip);
                                }
                            }
                        }
                    });
            });
        }
    }

    fn row_heading(&self, ui: &Ui, row: Rect, badge: &str, name: &str) {
        let icon = Rect::from_min_size(row.min + vec2(12.0, 10.0), vec2(36.0, 36.0));
        ui.painter().rect_filled(icon, 10, ACCENT_SOFT);
        centered(ui, icon, badge, 13.0, ACCENT);
        label(
            ui,
            Rect::from_min_size(row.min + vec2(58.0, 15.0), vec2(112.0, 26.0)),
            name,
            14.0,
            TEXT,
        );
    }

    fn chip(&self, ui: &mut Ui, bounds: Rect, text: &str, id: Id, active: bool) -> egui::Response {
        let response = ui.interact(bounds, id, Sense::click());
        panel(
            ui,
            bounds,
            10,
            if response.hovered() { HOVER } else { CONTROL },
        );
        label(
            ui,
            rect(
                bounds.left() + 12.0,
                bounds.top(),
                bounds.width() - 36.0,
                bounds.height(),
            ),
            text,
            13.0,
            if active { ACCENT } else { MUTED },
        );
        self.assets.icon(
            ui,
            "chevron_down",
            rect(bounds.right() - 24.0, bounds.top() + 10.0, 16.0, 16.0),
        );
        response.on_hover_text(text)
    }

    fn popup(&mut self, ctx: &egui::Context, view: &ScriptView, actions: &mut Vec<Action>) {
        let Some(mut menu) = self.menu.clone() else {
            return;
        };
        let entries = menu_entries(view, &menu.kind);
        if entries.is_empty() {
            self.menu = None;
            return;
        }
        let left_width = (entries
            .iter()
            .map(|entry| {
                ctx.fonts_mut(|fonts| {
                    fonts
                        .layout_no_wrap(entry.label.clone(), egui::FontId::proportional(13.0), TEXT)
                        .size()
                        .x
                })
            })
            .fold(60.0, f32::max)
            + 34.0)
            .min(240.0);
        let children = menu
            .parent
            .and_then(|index| entries.get(index))
            .map(|entry| entry.children.as_slice())
            .unwrap_or(&[]);
        let width = left_width + 8.0 + if children.is_empty() { 0.0 } else { 204.0 };
        let desired = (entries.len() as f32 * 32.0 + 8.0).min(360.0);
        let screen = ctx.content_rect();
        let bounds = popup_bounds(menu.anchor, vec2(width, desired), screen);
        let outside = ctx.input(|input| {
            input.key_pressed(egui::Key::Escape)
                || (input.pointer.any_pressed()
                    && input
                        .pointer
                        .interact_pos()
                        .is_some_and(|pos| !bounds.contains(pos) && !menu.anchor.contains(pos)))
        });
        if outside {
            self.menu = None;
            return;
        }
        let mut selected = None;
        let before = menu.parent;
        egui::Area::new(Id::new("task-popup"))
            .order(egui::Order::Foreground)
            .fixed_pos(bounds.min)
            .default_size(bounds.size())
            .constrain(false)
            .show(ctx, |ui| {
                egui::Frame::new()
                    .fill(CONTROL)
                    .stroke(egui::Stroke::new(1.0, BORDER))
                    .corner_radius(10)
                    .inner_margin(4)
                    .show(ui, |ui| {
                        ui.spacing_mut().item_spacing = vec2(4.0, 2.0);
                        ui.horizontal_top(|ui| {
                            egui::ScrollArea::vertical()
                                .id_salt("menu-primary")
                                .max_width(left_width)
                                .max_height(bounds.height() - 8.0)
                                .min_scrolled_height(0.0)
                                .show(ui, |ui| {
                                    ui.with_layout(
                                        egui::Layout::top_down(egui::Align::Min),
                                        |ui| {
                                            for (index, entry) in entries.iter().enumerate() {
                                                let response = menu_item(
                                                    ui,
                                                    &entry.label,
                                                    left_width,
                                                    Id::new(("primary", index)),
                                                    menu.parent == Some(index),
                                                    !entry.children.is_empty(),
                                                );
                                                if response.hovered() && !entry.children.is_empty()
                                                {
                                                    menu.parent = Some(index);
                                                }
                                                if response.clicked() {
                                                    if entry.children.is_empty() {
                                                        selected = Some(entry);
                                                    } else {
                                                        menu.parent = Some(index);
                                                    }
                                                }
                                            }
                                        },
                                    );
                                });
                            if !children.is_empty() {
                                egui::ScrollArea::vertical()
                                    .id_salt(("menu-children", before))
                                    .max_width(200.0)
                                    .max_height(bounds.height() - 8.0)
                                    .min_scrolled_height(0.0)
                                    .show(ui, |ui| {
                                        ui.with_layout(
                                            egui::Layout::top_down(egui::Align::Min),
                                            |ui| {
                                                for (index, entry) in children.iter().enumerate() {
                                                    if menu_item(
                                                        ui,
                                                        &entry.label,
                                                        200.0,
                                                        Id::new(("child", index)),
                                                        false,
                                                        false,
                                                    )
                                                    .clicked()
                                                    {
                                                        selected = Some(entry);
                                                    }
                                                }
                                            },
                                        );
                                    });
                            }
                        });
                    });
            });
        if let Some(entry) = selected {
            if let Some(request) = &entry.request {
                actions.push(Action::Request(Request {
                    method: request.method.clone(),
                    params: request.params.clone(),
                }));
            }
            self.menu = None;
        } else {
            if before != menu.parent {
                ctx.request_repaint();
            }
            self.menu = Some(menu);
        }
    }
}

fn menu_item(
    ui: &mut Ui,
    text: &str,
    width: f32,
    id: Id,
    selected: bool,
    children: bool,
) -> egui::Response {
    let (bounds, _) = ui.allocate_exact_size(vec2(width, 30.0), Sense::hover());
    let response = ui.interact(bounds, id, Sense::click());
    if response.hovered() || selected {
        ui.painter().rect_filled(bounds, 6, ACCENT_SOFT);
    }
    label(ui, bounds.shrink2(vec2(10.0, 0.0)), text, 13.0, TEXT);
    if children {
        centered(
            ui,
            rect(bounds.right() - 22.0, bounds.top(), 16.0, 30.0),
            "›",
            18.0,
            MUTED,
        );
    }
    response
}

fn popup_bounds(anchor: Rect, desired: Vec2, screen: Rect) -> Rect {
    let below = screen.bottom() - anchor.bottom() - 12.0;
    let above = anchor.top() - screen.top() - 12.0;
    let down = desired.y <= below || below >= above;
    let height = desired.y.min(if down { below } else { above }).max(0.0);
    let width = desired.x.min(screen.width() - 16.0);
    let x = anchor
        .left()
        .min(screen.right() - width - 8.0)
        .max(screen.left() + 8.0);
    let y = if down {
        anchor.bottom() + 4.0
    } else {
        anchor.top() - height - 4.0
    };
    Rect::from_min_size(pos2(x, y), vec2(width, height))
}

struct Entry {
    label: String,
    children: Vec<Entry>,
    request: Option<Request>,
}

fn leaf(label: String, method: &str, params: serde_json::Value) -> Entry {
    Entry {
        label,
        children: Vec::new(),
        request: Some(Request {
            method: method.into(),
            params,
        }),
    }
}

fn daily_entries(script: &str, daily: &Daily) -> Vec<Entry> {
    let mut entries = Vec::new();
    for choice in &daily.options.values {
        let params = |sequence| json!({"script_name": script, "daily_name": daily.name, "task_name": choice.display_name, "sequence": sequence});
        if let Some(options) = &choice.options {
            let children = options
                .values
                .iter()
                .map(|child| {
                    leaf(
                        child.display_name.clone(),
                        "daily.select",
                        params(child.physical_name.clone()),
                    )
                })
                .collect();
            entries.push(Entry {
                label: choice.display_name.clone(),
                children,
                request: None,
            });
        } else {
            entries.push(leaf(
                choice.display_name.clone(),
                "daily.select",
                params(serde_json::Value::Null),
            ));
        }
    }
    if daily.enabled.is_some() {
        entries.push(leaf(
            "不启用".into(),
            "daily.enable",
            json!({"script_name": script, "daily_name": daily.name, "enabled": false}),
        ));
    }
    entries
}

fn weekly_entries(script: &str, weekly: &Weekly, start: bool) -> Vec<Entry> {
    if start {
        (0..=7)
            .map(|day| {
                leaf(
                    start_label(Some(day)).into(),
                    "weekly.start",
                    json!({
                        "script_name": script, "weekly_name": weekly.name, "start_day": day
                    }),
                )
            })
            .collect()
    } else {
        weekly
            .options
            .as_ref()
            .map(|options| {
                options.values.iter().map(|choice|
            leaf(choice.display_name.clone(), "weekly.select", json!({
                "script_name": script, "weekly_name": weekly.name, "task_name": choice.display_name
            }))
        ).collect()
            })
            .unwrap_or_default()
    }
}

fn menu_entries(view: &ScriptView, kind: &MenuKind) -> Vec<Entry> {
    match kind {
        MenuKind::Daily(name) => view
            .dailies
            .iter()
            .find(|daily| &daily.name == name)
            .map(|daily| daily_entries(&view.script.script_name, daily))
            .unwrap_or_default(),
        MenuKind::Weekly(name) | MenuKind::Start(name) => view
            .weeklies
            .iter()
            .find(|weekly| &weekly.name == name)
            .map(|weekly| {
                weekly_entries(
                    &view.script.script_name,
                    weekly,
                    matches!(kind, MenuKind::Start(_)),
                )
            })
            .unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Scene {
        ctx: egui::Context,
        ui: View,
        view: ScriptView,
        scripts: Vec<Script>,
        time: f64,
        busy: bool,
    }

    impl Scene {
        fn new() -> Self {
            let ctx = egui::Context::default();
            crate::skin::configure(&ctx);
            let ui = View::new(&ctx);
            let view: ScriptView = serde_json::from_value(json!({
                "script": {"script_name": "test", "display_name": "演示", "script_path": "test.exe", "adapted": true},
                "dailies": [{"name": "每日任务", "enabled": true,
                    "task": "材料", "sequence": 1,
                    "options": {"values": [
                        {"display_name": "材料", "physical_name": "material", "options": {"values":
                            (1..=40).map(|i| json!({"display_name": format!("副本 {i}"), "physical_name": i})).collect::<Vec<_>>() }},
                        {"display_name": "布尔", "physical_name": "boolean", "options": {"values": [
                            {"display_name": "开启", "physical_name": true}, {"display_name": "关闭", "physical_name": false}]}},
                        {"display_name": "单项", "physical_name": "single"}
                    ]}}
                ],
                "weeklies": [{"name": "周常", "options": null, "task": null, "start_day": null}]
            })).unwrap();
            let scripts = vec![view.script.clone()];
            let mut scene = Self {
                ctx,
                ui,
                view,
                scripts,
                time: 0.0,
                busy: false,
            };
            scene.frame(vec![]);
            scene.frame(vec![]);
            scene
        }

        fn frame(&mut self, events: Vec<egui::Event>) -> Vec<Action> {
            self.time += 0.1;
            let input = egui::RawInput {
                screen_rect: Some(Rect::from_min_size(egui::Pos2::ZERO, SIZE)),
                time: Some(self.time),
                events,
                ..Default::default()
            };
            let mut actions = Vec::new();
            let mut output = self.ctx.run_ui(input, |ui| {
                actions.extend(self.ui.show(
                    ui,
                    Presentation {
                        scripts: &self.scripts,
                        selected: Some("test"),
                        view: Some(&self.view),
                        busy: self.busy,
                        block_close: false,
                        status: "已同步",
                        demo: true,
                    },
                ))
            });
            // The input-only harness does not upload textures to a GPU.
            output.textures_delta.clear();
            actions
        }

        fn click(&mut self, id: Id) -> Vec<Action> {
            let pos = self
                .ctx
                .read_response(id)
                .expect("visible control")
                .rect
                .center();
            self.frame(vec![
                egui::Event::PointerMoved(pos),
                egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: Default::default(),
                },
            ]);
            self.frame(vec![egui::Event::PointerButton {
                pos,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: Default::default(),
            }])
        }

        fn daily(&mut self, parent: usize) {
            assert!(self.click(Id::new(("daily", "每日任务"))).is_empty());
            self.frame(vec![]);
            let pos = self
                .ctx
                .read_response(Id::new(("primary", parent)))
                .unwrap()
                .rect
                .center();
            self.frame(vec![egui::Event::PointerMoved(pos)]);
            self.frame(vec![]);
            assert_eq!(
                self.ui.menu.as_ref().unwrap().parent,
                Some(parent),
                "pointer {pos:?}, response {:?}, layer {:?}",
                self.ctx.read_response(Id::new(("primary", parent))),
                self.ctx.layer_id_at(pos),
            );
        }
    }

    fn only_request(actions: Vec<Action>) -> Request {
        assert_eq!(actions.len(), 1, "one click must emit one action");
        match actions.into_iter().next().unwrap() {
            Action::Request(request) => request,
            _ => panic!("expected backend request"),
        }
    }

    #[test]
    fn real_menu_click_preserves_boolean_and_disable_semantics() {
        let mut scene = Scene::new();
        scene.daily(1);
        let request = only_request(scene.click(Id::new(("child", 0_usize))));
        assert_eq!(request.method, "daily.select");
        assert_eq!(request.params["task_name"], "布尔");
        assert_eq!(request.params["sequence"], json!(true));
        assert!(scene.ui.menu.is_none());
        scene.click(Id::new(("daily", "每日任务")));
        scene.frame(vec![]);
        let request = only_request(scene.click(Id::new(("primary", 3_usize))));
        assert_eq!(request.method, "daily.enable");
        assert_eq!(request.params["enabled"], json!(false));
    }

    #[test]
    fn long_submenu_can_scroll_to_last_integer_choice() {
        let mut scene = Scene::new();
        scene.daily(0);
        let pos = scene
            .ctx
            .read_response(Id::new(("child", 0_usize)))
            .unwrap()
            .rect
            .center();
        for _ in 0..12 {
            scene.frame(vec![
                egui::Event::PointerMoved(pos),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    delta: vec2(0.0, -240.0),
                    phase: egui::TouchPhase::Move,
                    modifiers: Default::default(),
                },
            ]);
        }
        let request = only_request(scene.click(Id::new(("child", 39_usize))));
        assert_eq!(request.params["sequence"], json!(40));
    }

    #[test]
    fn weekly_zero_and_current_launch_are_distinct_actions() {
        let mut scene = Scene::new();
        scene.click(Id::new(("start", "周常")));
        scene.frame(vec![]);
        let request = only_request(scene.click(Id::new(("primary", 0_usize))));
        assert_eq!(request.method, "weekly.start");
        assert_eq!(request.params["start_day"], json!(0));
        let request = only_request(scene.click(Id::new("launch")));
        assert_eq!(request.method, "script.launch_target");
        assert_eq!(
            request.params,
            json!({"script_name":"test","target":"script"})
        );
    }

    #[test]
    fn tall_popups_flip_up_and_remain_inside_window() {
        let screen = Rect::from_min_size(egui::Pos2::ZERO, SIZE);
        for y in [100.0, 460.0, 650.0] {
            let anchor = rect(1180.0, y, 80.0, 36.0);
            let popup = popup_bounds(anchor, vec2(444.0, 360.0), screen);
            assert!(screen.contains_rect(popup));
            assert!(popup.bottom() <= anchor.top() || popup.top() >= anchor.bottom());
        }
    }

    #[test]
    fn hovering_game_only_queries_icon_once_per_entry() {
        let mut scene = Scene::new();
        let pos = scene
            .ctx
            .read_response(Id::new(("icon", "启动游戏")))
            .unwrap()
            .rect
            .center();
        let actions = scene.frame(vec![egui::Event::PointerMoved(pos)]);
        assert_eq!(only_request(actions).method, "script.icon_path");
        assert!(scene.frame(vec![]).is_empty());
        scene.ui.set_game_icon("test".into(), None);
        assert!(scene.frame(vec![]).is_empty());
        scene.frame(vec![egui::Event::PointerMoved(pos2(500.0, 100.0))]);
        scene.busy = true;
        assert!(scene.frame(vec![egui::Event::PointerMoved(pos)]).is_empty());
        scene.busy = false;
        assert_eq!(only_request(scene.frame(vec![])).method, "script.icon_path");
    }

    #[test]
    fn navigation_buttons_request_current_script_targets() {
        let mut scene = Scene::new();
        for (label, target) in [
            ("游戏官网", "home"),
            ("脚本目录", "folder"),
            ("运行日志", "log"),
            ("脚本配置文件", "configfile"),
            ("哔哩哔哩", "bili"),
            ("GitHub", "github"),
        ] {
            let request = only_request(scene.click(Id::new(("icon", label))));
            assert_eq!(request.method, "script.target");
            assert_eq!(
                request.params,
                json!({"script_name": "test", "target": target})
            );
        }
        let request = only_request(scene.click(Id::new(("icon", "启动游戏"))));
        assert_eq!(request.method, "script.launch_target");
        assert_eq!(
            request.params,
            json!({"script_name":"test","target":"game"})
        );
        let request = only_request(scene.click(Id::new(("icon", "更换壁纸"))));
        assert_eq!(request.method, "wallpaper.view");
        assert_eq!(request.params, json!({"script_name":"test"}));
    }

    #[test]
    fn script_settings_opens_edit_form_for_current_script() {
        let mut scene = Scene::new();
        let request = only_request(scene.click(Id::new(("icon", "脚本配置"))));
        assert_eq!(request.method, "script.edit_view");
        assert_eq!(request.params, json!({"script_name": "test"}));
        let request = only_request(scene.click(Id::new(("icon", "配置"))));
        assert_eq!(request.method, "settings.view");
        assert_eq!(request.params, json!({}));
        scene.busy = true;
        assert!(scene.click(Id::new(("icon", "配置"))).is_empty());
    }

    #[test]
    fn batch_button_uses_only_manual_selection_and_empty_is_local() {
        let mut scene = Scene::new();
        let request = only_request(scene.click(Id::new(("icon", "启动手动勾选的脚本"))));
        assert_eq!(request.method, "run.view");
        assert_eq!(request.params, json!({"script_names":["test"]}));
        scene.ui.disabled.insert("test".into());
        assert!(
            scene
                .click(Id::new(("icon", "启动手动勾选的脚本")))
                .is_empty()
        );
        assert!(scene.ui.toast.as_ref().unwrap().0.contains("没有勾选"));
    }

    #[test]
    fn manual_selection_is_local_and_follows_identity() {
        let mut scene = Scene::new();
        assert!(
            scene
                .click(Id::new(("icon", "选择手动运行的脚本")))
                .is_empty()
        );
        scene.frame(vec![]);
        assert!(scene.click(Id::new(("script", "test"))).is_empty());
        assert!(scene.ui.disabled.contains("test"));
        assert!(scene.click(Id::new(("manual-action", 0_usize))).is_empty());
        assert!(scene.ui.disabled.is_empty());
        assert!(scene.click(Id::new(("manual-action", 1_usize))).is_empty());
        scene.ui.rename_script("test", "new");
        assert_eq!(scene.ui.disabled, HashSet::from(["new".into()]));
        scene.ui.reconcile_scripts(&scene.scripts);
        assert!(scene.ui.disabled.is_empty());
        let actions = scene.click(Id::new(("manual-action", 2_usize)));
        assert!(matches!(actions.as_slice(), [Action::AddScript]));
        assert!(!scene.ui.control_mode);
        assert!(Scene::new().ui.disabled.is_empty());
    }

    #[test]
    fn drag_reorders_or_requests_delete_confirmation() {
        for delete in [false, true] {
            let mut scene = Scene::new();
            let mut second = scene.scripts[0].clone();
            second.script_name = "second".into();
            scene.scripts.push(second);
            scene.frame(vec![]);
            let start = scene
                .ctx
                .read_response(Id::new(("script", "test")))
                .unwrap()
                .rect
                .center();
            let end = if delete {
                pos2(40.0, 632.0)
            } else {
                scene
                    .ctx
                    .read_response(Id::new(("script", "second")))
                    .unwrap()
                    .rect
                    .center()
            };
            scene.frame(vec![
                egui::Event::PointerMoved(start),
                egui::Event::PointerButton {
                    pos: start,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: Default::default(),
                },
            ]);
            scene.frame(vec![egui::Event::PointerMoved(end)]);
            let actions = scene.frame(vec![egui::Event::PointerButton {
                pos: end,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: Default::default(),
            }]);
            if delete {
                assert!(
                    matches!(actions.as_slice(),[Action::RemoveScript(name)] if name == "test")
                );
            } else {
                let request = only_request(actions);
                assert_eq!(request.method, "script.reorder");
                assert_eq!(request.params, json!({"script_names":["second","test"]}));
            }
            assert!(scene.ui.dragging.is_none());
        }
    }
}
