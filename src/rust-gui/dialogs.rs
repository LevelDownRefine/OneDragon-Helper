use crate::theme::*;
use crate::{file_picker::FilePicker, theme};
use eframe::egui::{self, Color32, FontId, vec2};
use onedragon_rust_gui::{backend::Request, model::Script};
use serde::Deserialize;
use serde_json::{Value, json};

fn enabled() -> bool {
    true
}
fn external() -> String {
    "external".into()
}
fn script_closed() -> String {
    "script_closed".into()
}

#[derive(Debug, Deserialize)]
pub struct Fields {
    pub display_name: String,
    pub script_path: String,
    #[serde(default = "external")]
    script_type: String,
    #[serde(default)]
    script_arguments: String,
    #[serde(default = "script_closed")]
    check_done: String,
    #[serde(default = "enabled")]
    kill_script_after_done: bool,
    #[serde(default)]
    kill_game_after_done: bool,
    #[serde(default = "enabled")]
    block: bool,
    #[serde(default)]
    game_process_name: String,
    #[serde(default)]
    game_path: String,
}

#[derive(Debug, Deserialize)]
pub struct TaskSwitch {
    name: String,
    enabled: bool,
}

#[derive(Debug, Deserialize)]
pub struct EditView {
    pub script_name: String,
    script: Fields,
    weekly_timeouts: [u32; 7],
    switches: Vec<TaskSwitch>,
}

pub enum EditAction {
    Save(Request),
    Cancel,
    Reload,
}

pub struct ScriptEditor {
    data: EditView,
    timeouts: [String; 7],
    error: Option<String>,
    pub needs_reload: bool,
    picker: Option<FilePicker>,
}

impl ScriptEditor {
    pub fn new(data: EditView) -> Self {
        let timeouts = data.weekly_timeouts.map(|value| value.to_string());
        Self {
            data,
            timeouts,
            error: None,
            needs_reload: false,
            picker: None,
        }
    }

    pub fn failure(&mut self, message: String, needs_reload: bool) {
        self.error = Some(message);
        self.needs_reload = needs_reload;
    }

    pub fn matches_saved(&self, script: &Script) -> bool {
        script.display_name == self.data.script.display_name.trim()
            && script.script_path == self.data.script.script_path.trim()
    }

    fn request(&self) -> Result<Request, String> {
        let fields = &self.data.script;
        if fields.display_name.trim().is_empty() || fields.script_path.trim().is_empty() {
            return Err("脚本名称和路径不能为空".into());
        }
        let mut timeouts = Vec::new();
        for value in &self.timeouts {
            let value = value.trim();
            if value.is_empty() {
                timeouts.push(None);
            } else {
                let seconds = value
                    .parse::<u32>()
                    .map_err(|_| "超时须为 0～86400 秒，留空使用默认值")?;
                if seconds > 86400 {
                    return Err("超时不能超过 86400 秒".into());
                }
                timeouts.push(Some(seconds));
            }
        }
        let switches: serde_json::Map<String, Value> = self
            .data
            .switches
            .iter()
            .map(|row| (row.name.clone(), json!(row.enabled)))
            .collect();
        Ok(Request {
            method: "script.edit_save".into(),
            params: json!({
                "script_name": self.data.script_name,
                "display_name": fields.display_name.trim(),
                "config_patch": {
                    "script_path": fields.script_path.trim(), "script_type": fields.script_type,
                    "script_arguments": fields.script_arguments.trim(), "check_done": fields.check_done,
                    "kill_script_after_done": fields.kill_script_after_done,
                    "kill_game_after_done": fields.kill_game_after_done, "block": fields.block,
                    "game_process_name": fields.game_process_name.trim(), "game_path": fields.game_path.trim(),
                },
                "weekly_timeouts": timeouts, "switches": switches,
            }),
        })
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<EditAction> {
        if let Some(result) = self.picker.as_ref().and_then(FilePicker::poll) {
            self.picker = None;
            match result {
                Ok(Some(path)) => self.data.script.script_path = path,
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = busy || self.picker.is_some();
        let mut action = None;
        let close = crate::dialogs::Dialog::new(
            "script-editor",
            &format!("配置 {}", self.data.script.display_name),
        )
        .width(590.0)
        .description("设置脚本入口、运行行为与任务开关")
        .show(ctx, !blocked, |ui| {
            crate::dialogs::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| self.fields_ui(ui));
            });
            crate::dialogs::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("配置可能已部分保存，请刷新后核对；不会自动重试保存。"),
            );
            crate::dialogs::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !blocked && !self.needs_reload,
                        crate::dialogs::primary_button("保存"),
                    )
                    .clicked()
                {
                    match self.request() {
                        Ok(request) => {
                            self.error = None;
                            action = Some(EditAction::Save(request));
                        }
                        Err(error) => self.error = Some(error),
                    }
                }
                if ui
                    .add_enabled(!blocked, crate::dialogs::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(EditAction::Cancel);
                }
                if blocked {
                    ui.spinner();
                }
                ui.with_layout(egui::Layout::left_to_right(egui::Align::Center), |ui| {
                    if ui
                        .add_enabled(!blocked, crate::dialogs::secondary_button("刷新"))
                        .clicked()
                    {
                        action = Some(EditAction::Reload);
                    }
                });
            });
        });
        if close {
            action = Some(EditAction::Cancel);
        }
        action
    }

    fn fields_ui(&mut self, ui: &mut egui::Ui) {
        let fields = &mut self.data.script;
        crate::dialogs::form_section(ui, "基本信息", |ui| {
            crate::dialogs::form_grid(ui, "script-fields", |ui| {
                ui.label("脚本名称");
                ui.add(crate::dialogs::text_input(&mut fields.display_name));
                ui.end_row();
                ui.label("脚本路径");
                if crate::dialogs::path_input(ui, &mut fields.script_path).1 {
                    self.picker = Some(FilePicker::start(
                        ui.ctx().clone(),
                        crate::file_picker::FileKind::Script,
                    ));
                }
                ui.end_row();
                ui.label("脚本类型");
                let label = match fields.script_type.as_str() {
                    "external" => "外部程序",
                    "python" => "Python 脚本",
                    value => value,
                };
                egui::ComboBox::from_id_salt("script-type")
                    .selected_text(label)
                    .show_ui(ui, |ui| {
                        for (value, label) in [("external", "外部程序"), ("python", "Python 脚本")]
                        {
                            ui.selectable_value(&mut fields.script_type, value.into(), label);
                        }
                    });
                ui.end_row();
                ui.label("启动参数");
                ui.add(crate::dialogs::text_input(&mut fields.script_arguments).hint_text("可选"));
                ui.end_row();
            });
        });
        crate::dialogs::form_section(ui, "运行行为", |ui| {
            crate::dialogs::form_grid(ui, "script-behavior", |ui| {
                ui.label("完成检测");
                let label = match fields.check_done.as_str() {
                    "game_or_script_closed" => "游戏或脚本退出",
                    "script_closed" => "脚本退出",
                    "game_closed" => "游戏退出",
                    value => value,
                };
                egui::ComboBox::from_id_salt("check-done")
                    .selected_text(label)
                    .show_ui(ui, |ui| {
                        for (value, label) in [
                            ("game_or_script_closed", "游戏或脚本退出"),
                            ("script_closed", "脚本退出"),
                            ("game_closed", "游戏退出"),
                        ] {
                            ui.selectable_value(&mut fields.check_done, value.into(), label);
                        }
                    });
                ui.end_row();
                ui.label("游戏进程");
                ui.add(
                    crate::dialogs::text_input(&mut fields.game_process_name)
                        .hint_text("例如 Game.exe"),
                );
                ui.end_row();
                ui.label("游戏路径");
                ui.add(crate::dialogs::text_input(&mut fields.game_path));
                ui.end_row();
            });
            ui.horizontal_wrapped(|ui| {
                ui.checkbox(&mut fields.kill_script_after_done, "结束后关闭脚本");
                ui.checkbox(&mut fields.kill_game_after_done, "结束后关闭游戏");
            });
            ui.checkbox(&mut fields.block, "等待此脚本完成后再运行下一个");
            if fields.kill_game_after_done && fields.game_process_name.trim().is_empty() {
                ui.colored_label(
                    theme::MUTED,
                    "未填写游戏进程名，保存时将取消“结束后关闭游戏”",
                );
            }
        });
        crate::dialogs::form_section(ui, "每周超时", |ui| {
            ui.label(
                egui::RichText::new("单位为秒，留空使用默认值")
                    .size(12.0)
                    .color(theme::MUTED),
            );
            ui.columns(7, |columns| {
                for (index, day) in ["一", "二", "三", "四", "五", "六", "日"]
                    .iter()
                    .enumerate()
                {
                    columns[index].label(format!("周{day}"));
                    columns[index].add(
                        crate::dialogs::text_input(&mut self.timeouts[index])
                            .desired_width(f32::INFINITY),
                    );
                }
            });
        });
        if !self.data.switches.is_empty() {
            crate::dialogs::form_section(ui, "任务开关", |ui| {
                for row in &mut self.data.switches {
                    ui.checkbox(&mut row.enabled, &row.name);
                }
            });
        }
    }
}

fn dialog_style(ui: &mut egui::Ui) {
    let style = ui.style_mut();
    style.spacing.item_spacing = vec2(10.0, 8.0);
    style.spacing.button_padding = vec2(14.0, 7.0);
    style.spacing.interact_size.y = 30.0;
    style.visuals.text_edit_bg_color = Some(Color32::from_rgb(13, 23, 38));
    style.visuals.widgets.inactive.bg_fill = CONTROL;
    style.visuals.widgets.inactive.weak_bg_fill = CONTROL;
    style.visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.0, BORDER);
    style.visuals.widgets.inactive.corner_radius = 7.into();
    style.visuals.widgets.hovered.bg_fill = HOVER;
    style.visuals.widgets.hovered.weak_bg_fill = HOVER;
    style.visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.0, ACCENT);
    style.visuals.widgets.hovered.corner_radius = 7.into();
    style.visuals.widgets.active.bg_fill = ACCENT_SOFT;
    style.visuals.widgets.active.weak_bg_fill = ACCENT_SOFT;
    style.visuals.widgets.active.corner_radius = 7.into();
    style
        .text_styles
        .insert(egui::TextStyle::Body, FontId::proportional(14.0));
    style
        .text_styles
        .insert(egui::TextStyle::Button, FontId::proportional(14.0));
}

fn dialog_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(Color32::from_rgb(17, 27, 42))
        .stroke(egui::Stroke::new(1.0, BORDER))
        .corner_radius(18)
        .inner_margin(22)
}

/// Shared shell; each caller retains its own save and cancellation semantics.
pub struct Dialog<'a> {
    id: egui::Id,
    title: &'a str,
    description: &'a str,
    width: f32,
}

impl<'a> Dialog<'a> {
    pub fn new(id: &str, title: &'a str) -> Self {
        Self {
            id: egui::Id::new(id),
            title,
            description: "",
            width: 520.0,
        }
    }

    pub fn description(mut self, description: &'a str) -> Self {
        self.description = description;
        self
    }

    pub fn width(mut self, width: f32) -> Self {
        self.width = width;
        self
    }

    /// Returns a close intent only when closing is allowed by the caller.
    pub fn show(
        self,
        ctx: &egui::Context,
        closable: bool,
        contents: impl FnOnce(&mut egui::Ui),
    ) -> bool {
        let mut close = false;
        let modal = egui::Modal::new(self.id)
            .frame(dialog_frame())
            .show(ctx, |ui| {
                ui.set_width(
                    self.width
                        .min((ctx.content_rect().width() - 80.0).max(280.0)),
                );
                dialog_style(ui);
                ui.horizontal(|ui| {
                    let title_width = ui.available_width() - 44.0;
                    ui.allocate_ui_with_layout(
                        vec2(title_width, 32.0),
                        egui::Layout::left_to_right(egui::Align::Center),
                        |ui| {
                            ui.set_min_width(title_width);
                            ui.add(
                                egui::Label::new(
                                    egui::RichText::new(self.title).size(22.0).strong(),
                                )
                                .truncate(),
                            )
                            .on_hover_text(self.title);
                        },
                    );
                    close = ui
                        .add_enabled(closable, egui::Button::new("×").frame(false))
                        .on_hover_text("关闭")
                        .clicked();
                });
                if !self.description.is_empty() {
                    ui.label(
                        egui::RichText::new(self.description)
                            .size(12.0)
                            .color(MUTED),
                    );
                }
                ui.add_space(6.0);
                contents(ui);
            });
        closable && (close || modal.should_close())
    }
}

/// Only the body scrolls, keeping the title and actions visible.
pub fn dialog_body(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui)) {
    egui::ScrollArea::vertical()
        .max_height((ui.ctx().content_rect().height() - 230.0).clamp(140.0, 490.0))
        .auto_shrink([false, true])
        .show(ui, contents);
}

/// Actions are ordered from the primary action at the right edge.
pub fn dialog_footer(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui)) {
    ui.add_space(4.0);
    ui.separator();
    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
        ui.set_min_height(34.0);
        contents(ui);
    });
}

pub fn dialog_status(ui: &mut egui::Ui, error: Option<&str>, notice: Option<&str>) {
    if error.is_some() || notice.is_some() {
        egui::ScrollArea::vertical()
            .id_salt("dialog-status")
            .max_height(40.0)
            .min_scrolled_height(0.0)
            .show(ui, |ui| {
                if let Some(error) = error {
                    ui.colored_label(Color32::LIGHT_RED, error);
                }
                if let Some(notice) = notice {
                    ui.label(notice);
                }
            });
    }
}

pub fn text_input(text: &mut String) -> egui::TextEdit<'_> {
    egui::TextEdit::singleline(text).margin(vec2(8.0, 6.0))
}

pub fn secondary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(text).min_size(vec2(78.0, 34.0))
}

/// Equal-width label and input columns within a section.
pub fn form_grid(ui: &mut egui::Ui, id: &str, contents: impl FnOnce(&mut egui::Ui)) {
    let input_width = (ui.available_width() - 104.0).max(120.0);
    ui.scope(|ui| {
        ui.spacing_mut().text_edit_width = input_width;
        ui.spacing_mut().combo_width = input_width;
        egui::Grid::new(id)
            .num_columns(2)
            .min_col_width(92.0)
            .spacing([12.0, 10.0])
            .show(ui, contents);
    });
}

pub fn path_input(ui: &mut egui::Ui, path: &mut String) -> (bool, bool) {
    ui.horizontal(|ui| {
        let changed = ui
            .add(text_input(path).desired_width((ui.available_width() - 86.0).max(80.0)))
            .changed();
        (
            changed,
            ui.add_sized([76.0, 32.0], egui::Button::new("浏览…"))
                .clicked(),
        )
    })
    .inner
}

pub fn form_section(ui: &mut egui::Ui, title: &str, content: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(Color32::from_rgb(22, 34, 51))
        .stroke(egui::Stroke::new(1.0, DIVIDER))
        .corner_radius(10)
        .inner_margin(14)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(egui::RichText::new(title).size(14.0).strong().color(ACCENT));
            content(ui);
        });
}

pub fn primary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).color(TEXT).strong())
        .fill(PRIMARY)
        .stroke(egui::Stroke::new(1.0, Color32::from_rgb(80, 122, 174)))
        .min_size(vec2(92.0, 34.0))
}

#[cfg(test)]
#[path = "../../tests/rust-gui/dialogs.rs"]
mod tests;
