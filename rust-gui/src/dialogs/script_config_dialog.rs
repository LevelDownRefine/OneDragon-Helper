use crate::dialogs::file_picker::FilePicker;
use crate::theme;
use eframe::egui;
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
    #[serde(default)]
    game_arguments: String,
}

#[derive(Debug, Deserialize)]
pub struct TaskSwitch {
    name: String,
    enabled: bool,
}

#[derive(Debug, Deserialize)]
pub struct OptionChoice {
    display_name: String,
    physical_name: String,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", content = "value")]
pub enum OptionValue {
    #[serde(rename = "bool")]
    Bool(bool),
    #[serde(rename = "choice")]
    Choice(String),
    #[serde(rename = "multi")]
    Multi(Vec<String>),
}

impl OptionValue {
    fn json(&self) -> Value {
        match self {
            Self::Bool(value) => json!(value),
            Self::Choice(value) => json!(value),
            Self::Multi(value) => json!(value),
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct TaskOption {
    id: String,
    group: String,
    #[serde(default)]
    tasks: Vec<String>,
    display_name: String,
    #[serde(flatten)]
    value: OptionValue,
    choices: Vec<OptionChoice>,
}

#[derive(Debug, Deserialize)]
pub struct EditView {
    pub script_name: String,
    script: Fields,
    weekly_timeouts: [u32; 7],
    switches: Vec<TaskSwitch>,
    #[serde(default)]
    task_options: Vec<TaskOption>,
}

struct TaskGroup {
    name: String,
    switches: Vec<usize>,
    options: Vec<usize>,
}

fn task_groups(data: &EditView) -> Vec<TaskGroup> {
    let mut groups: Vec<TaskGroup> = Vec::new();
    for (index, row) in data.task_options.iter().enumerate() {
        if let Some(group) = groups.iter_mut().find(|group| group.name == row.group) {
            group.options.push(index);
        } else {
            groups.push(TaskGroup {
                name: row.group.clone(),
                switches: Vec::new(),
                options: vec![index],
            });
        }
    }
    let mut order = Vec::new();
    let mut seen = Vec::new();
    for (index, switch) in data.switches.iter().enumerate() {
        let matched = groups.iter().position(|group| {
            let option = &data.task_options[group.options[0]];
            option.tasks.contains(&switch.name)
                || (option.tasks.is_empty() && option.group == switch.name)
        });
        if let Some(group_index) = matched {
            groups[group_index].switches.push(index);
            if !seen.contains(&group_index) {
                seen.push(group_index);
                order.push((true, group_index));
            }
        } else {
            order.push((false, index));
        }
    }
    order.extend(
        (0..groups.len())
            .filter(|index| !seen.contains(index))
            .map(|index| (true, index)),
    );
    order
        .into_iter()
        .map(|(grouped, index)| {
            if grouped {
                TaskGroup {
                    name: groups[index].name.clone(),
                    switches: groups[index].switches.clone(),
                    options: groups[index].options.clone(),
                }
            } else {
                TaskGroup {
                    name: data.switches[index].name.clone(),
                    switches: vec![index],
                    options: Vec::new(),
                }
            }
        })
        .collect()
}

fn task_option_ui(ui: &mut egui::Ui, row: &mut TaskOption) {
    ui.push_id(&row.id, |ui| match &mut row.value {
        OptionValue::Bool(value) => {
            ui.checkbox(value, &row.display_name);
        }
        OptionValue::Choice(value) => {
            ui.horizontal_wrapped(|ui| {
                ui.label(&row.display_name);
                let label = row
                    .choices
                    .iter()
                    .find(|choice| choice.physical_name == *value)
                    .map_or(value.as_str(), |choice| choice.display_name.as_str());
                egui::ComboBox::from_id_salt("choice")
                    .selected_text(label)
                    .show_ui(ui, |ui| {
                        for choice in &row.choices {
                            ui.selectable_value(
                                value,
                                choice.physical_name.clone(),
                                &choice.display_name,
                            );
                        }
                    });
            });
        }
        OptionValue::Multi(values) => {
            ui.label(&row.display_name);
            for choice in &row.choices {
                let mut selected = values.contains(&choice.physical_name);
                if ui.checkbox(&mut selected, &choice.display_name).changed() {
                    if selected {
                        values.push(choice.physical_name.clone());
                    } else {
                        values.retain(|value| *value != choice.physical_name);
                    }
                }
            }
        }
    });
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
    original_options: serde_json::Map<String, Value>,
}

impl ScriptEditor {
    pub fn new(data: EditView) -> Self {
        let timeouts = data.weekly_timeouts.map(|value| value.to_string());
        let original_options = data
            .task_options
            .iter()
            .map(|row| (row.id.clone(), row.value.json()))
            .collect();
        Self {
            data,
            timeouts,
            error: None,
            needs_reload: false,
            picker: None,
            original_options,
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
        let task_options: serde_json::Map<String, Value> = self
            .data
            .task_options
            .iter()
            .filter_map(|row| {
                let mut value = row.value.json();
                if let (OptionValue::Multi(selected), Some(Value::Array(original))) =
                    (&row.value, self.original_options.get(&row.id))
                {
                    let mut ordered: Vec<String> = original
                        .iter()
                        .filter_map(Value::as_str)
                        .filter(|name| selected.iter().any(|item| item == name))
                        .map(str::to_owned)
                        .collect();
                    for name in selected {
                        if !ordered.contains(name) {
                            ordered.push(name.clone());
                        }
                    }
                    value = json!(ordered);
                }
                (self.original_options.get(&row.id) != Some(&value))
                    .then(|| (row.id.clone(), value))
            })
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
                    "game_arguments": fields.game_arguments.trim(),
                },
                "weekly_timeouts": timeouts, "switches": switches,
                "task_options": task_options,
            }),
        })
    }

    pub fn show(&mut self, ctx: &egui::Context, blocked: bool) -> Option<EditAction> {
        if let Some(result) = self.picker.as_ref().and_then(FilePicker::poll) {
            self.picker = None;
            match result {
                Ok(Some(path)) => self.data.script.script_path = path,
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = blocked || self.picker.is_some();
        let mut action = None;
        let close = crate::dialogs::common::Dialog::new(
            "script-editor",
            &format!("配置 {}", self.data.script.display_name),
        )
        .width(590.0)
        .description("设置脚本入口、运行行为与任务开关")
        .show(ctx, !blocked, |ui| {
            crate::dialogs::common::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| self.fields_ui(ui));
            });
            crate::dialogs::common::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("配置可能已部分保存，请刷新后核对；不会自动重试保存。"),
            );
            crate::dialogs::common::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !blocked && !self.needs_reload,
                        crate::dialogs::common::primary_button("保存"),
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
                    .add_enabled(!blocked, crate::dialogs::common::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(EditAction::Cancel);
                }
                if blocked {
                    ui.spinner();
                }
                ui.with_layout(egui::Layout::left_to_right(egui::Align::Center), |ui| {
                    if ui
                        .add_enabled(!blocked, crate::dialogs::common::secondary_button("刷新"))
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
        crate::dialogs::common::form_section(ui, "基本信息", |ui| {
            crate::dialogs::common::form_grid(ui, "script-fields", |ui| {
                ui.label("脚本名称");
                ui.add(crate::dialogs::common::text_input(&mut fields.display_name));
                ui.end_row();
                ui.label("脚本路径");
                if crate::dialogs::common::path_input(ui, &mut fields.script_path).1 {
                    self.picker = Some(FilePicker::start(
                        ui.ctx().clone(),
                        crate::dialogs::file_picker::FileKind::Script,
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
                ui.add(
                    crate::dialogs::common::text_input(&mut fields.script_arguments)
                        .hint_text("可选"),
                );
                ui.end_row();
            });
        });
        crate::dialogs::common::form_section(ui, "运行行为", |ui| {
            crate::dialogs::common::form_grid(ui, "script-behavior", |ui| {
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
                    crate::dialogs::common::text_input(&mut fields.game_process_name)
                        .hint_text("例如 Game.exe"),
                );
                ui.end_row();
                ui.label("游戏路径");
                ui.add(crate::dialogs::common::text_input(&mut fields.game_path));
                ui.end_row();
                ui.label("游戏启动参数");
                ui.add(crate::dialogs::common::text_input(
                    &mut fields.game_arguments,
                ));
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
        crate::dialogs::common::form_section(ui, "每周超时", |ui| {
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
                        crate::dialogs::common::text_input(&mut self.timeouts[index])
                            .desired_width(f32::INFINITY),
                    );
                }
            });
        });
        let groups = task_groups(&self.data);
        if !groups.is_empty() {
            crate::dialogs::common::form_section(ui, "任务", |ui| {
                for group in groups {
                    ui.push_id(&group.name, |ui| {
                        if group.switches.is_empty()
                            && group.options.len() == 1
                            && self.data.task_options[group.options[0]].display_name == group.name
                        {
                            task_option_ui(ui, &mut self.data.task_options[group.options[0]]);
                            ui.add_space(8.0);
                            return;
                        }
                        if group.switches.len() != 1
                            || self.data.switches[group.switches[0]].name != group.name
                        {
                            ui.label(egui::RichText::new(&group.name).strong());
                        }
                        for index in group.switches {
                            let row = &mut self.data.switches[index];
                            ui.checkbox(&mut row.enabled, &row.name);
                        }
                        if !group.options.is_empty() {
                            ui.indent("children", |ui| {
                                for index in group.options {
                                    task_option_ui(ui, &mut self.data.task_options[index]);
                                }
                            });
                        }
                        ui.add_space(8.0);
                    });
                }
            });
        }
    }
}

#[cfg(test)]
#[path = "../../tests/dialogs/script_config_dialog.rs"]
mod tests;
