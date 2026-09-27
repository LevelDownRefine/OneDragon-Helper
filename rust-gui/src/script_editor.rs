use crate::{file_picker::FilePicker, skin};
use eframe::egui::{self, Id};
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
        let modal = egui::Modal::new(Id::new("script-editor"))
            .frame(
                egui::Frame::new()
                    .fill(skin::PANEL)
                    .stroke(egui::Stroke::new(1.0, skin::BORDER))
                    .corner_radius(16)
                    .inner_margin(20),
            )
            .show(ctx, |ui| {
                ui.set_width(590.0);
                ui.heading(format!("配置 {}", self.data.script.display_name));
                ui.add_space(12.0);
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                    egui::ScrollArea::vertical()
                        .max_height(440.0)
                        .show(ui, |ui| {
                            egui::Grid::new("script-fields")
                                .num_columns(2)
                                .spacing([12.0, 10.0])
                                .show(ui, |ui| {
                                    let fields = &mut self.data.script;
                                    ui.label("脚本名称");
                                    ui.text_edit_singleline(&mut fields.display_name);
                                    ui.end_row();
                                    ui.label("脚本路径");
                                    ui.horizontal(|ui| {
                                        ui.add(
                                            egui::TextEdit::singleline(&mut fields.script_path)
                                                .desired_width(325.0),
                                        );
                                        if ui.button("浏览…").clicked() {
                                            self.picker =
                                                Some(FilePicker::start(ctx.clone(), false));
                                        }
                                    });
                                    ui.end_row();
                                    ui.label("脚本类型");
                                    egui::ComboBox::from_id_salt("script-type")
                                        .selected_text(&fields.script_type)
                                        .show_ui(ui, |ui| {
                                            for choice in ["external", "python"] {
                                                ui.selectable_value(
                                                    &mut fields.script_type,
                                                    choice.into(),
                                                    choice,
                                                );
                                            }
                                        });
                                    ui.end_row();
                                    ui.label("启动参数");
                                    ui.text_edit_singleline(&mut fields.script_arguments);
                                    ui.end_row();
                                    ui.label("完成检测");
                                    egui::ComboBox::from_id_salt("check-done")
                                        .selected_text(&fields.check_done)
                                        .show_ui(ui, |ui| {
                                            for choice in [
                                                "game_or_script_closed",
                                                "script_closed",
                                                "game_closed",
                                            ] {
                                                ui.selectable_value(
                                                    &mut fields.check_done,
                                                    choice.into(),
                                                    choice,
                                                );
                                            }
                                        });
                                    ui.end_row();
                                    ui.label("运行行为");
                                    ui.horizontal(|ui| {
                                        ui.checkbox(
                                            &mut fields.kill_script_after_done,
                                            "结束后关闭脚本",
                                        );
                                        ui.checkbox(
                                            &mut fields.kill_game_after_done,
                                            "结束后关闭游戏",
                                        );
                                        ui.checkbox(&mut fields.block, "阻塞运行");
                                    });
                                    ui.end_row();
                                    ui.label("游戏进程");
                                    ui.text_edit_singleline(&mut fields.game_process_name);
                                    ui.end_row();
                                    ui.label("游戏路径");
                                    ui.text_edit_singleline(&mut fields.game_path);
                                    ui.end_row();
                                    ui.label("每周超时（秒）");
                                    egui::Grid::new("weekly-timeouts").num_columns(8).show(
                                        ui,
                                        |ui| {
                                            for (index, name) in
                                                ["一", "二", "三", "四", "五", "六", "日"]
                                                    .iter()
                                                    .enumerate()
                                            {
                                                ui.label(format!("周{name}"));
                                                ui.add(
                                                    egui::TextEdit::singleline(
                                                        &mut self.timeouts[index],
                                                    )
                                                    .desired_width(48.0),
                                                );
                                                if index == 3 {
                                                    ui.end_row();
                                                }
                                            }
                                        },
                                    );
                                    ui.end_row();
                                });
                            if self.data.script.kill_game_after_done
                                && self.data.script.game_process_name.trim().is_empty()
                            {
                                ui.colored_label(
                                    skin::MUTED,
                                    "未填写游戏进程名，保存时将取消“结束后关闭游戏”",
                                );
                            }
                            if !self.data.switches.is_empty() {
                                ui.separator();
                                ui.label("任务开关");
                                for row in &mut self.data.switches {
                                    ui.checkbox(&mut row.enabled, &row.name);
                                }
                            }
                        });
                });
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                if self.needs_reload {
                    ui.label("配置可能已部分保存，请重新读取后核对；不会自动重试保存。");
                }
                ui.add_space(12.0);
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(!blocked, egui::Button::new("取消"))
                        .clicked()
                    {
                        action = Some(EditAction::Cancel);
                    }
                    if ui
                        .add_enabled(!blocked, egui::Button::new("重新读取"))
                        .clicked()
                    {
                        action = Some(EditAction::Reload);
                    }
                    if ui
                        .add_enabled(!blocked && !self.needs_reload, egui::Button::new("保存"))
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
                    if blocked {
                        ui.spinner();
                    }
                });
            });
        if !blocked && modal.should_close() {
            action = Some(EditAction::Cancel);
        }
        action
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn editor() -> ScriptEditor {
        ScriptEditor::new(serde_json::from_value(json!({
            "script_name": "demo", "script": {"display_name": "示例", "script_path": "demo.exe"},
            "weekly_timeouts": [60,60,60,60,60,60,60], "switches": [{"name": "任务", "enabled": true}],
        })).unwrap())
    }

    #[test]
    fn form_preserves_null_timeouts_and_boolean_switches() {
        let mut editor = editor();
        editor.timeouts[0].clear();
        editor.timeouts[6] = "86400".into();
        let request = editor.request().unwrap();
        assert_eq!(request.method, "script.edit_save");
        assert_eq!(
            request.params["weekly_timeouts"],
            json!([null, 60, 60, 60, 60, 60, 86400])
        );
        assert_eq!(request.params["switches"]["任务"], true);
        assert_eq!(request.params["config_patch"]["block"], true);
        editor.timeouts[0] = "86401".into();
        assert!(editor.request().is_err());
        editor.timeouts[0] = "1.5".into();
        assert!(editor.request().is_err());
    }

    #[test]
    fn escape_cancels_without_emitting_save() {
        let ctx = egui::Context::default();
        let mut editor = editor();
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(editor.show(ui.ctx(), false).is_none());
            });
            output.textures_delta.clear();
        }
        let mut cancelled = false;
        let mut output = ctx.run_ui(
            egui::RawInput {
                events: vec![egui::Event::Key {
                    key: egui::Key::Escape,
                    physical_key: None,
                    pressed: true,
                    repeat: false,
                    modifiers: Default::default(),
                }],
                ..Default::default()
            },
            |ui| {
                cancelled = matches!(editor.show(ui.ctx(), false), Some(EditAction::Cancel));
            },
        );
        output.textures_delta.clear();
        assert!(cancelled);
    }
}
