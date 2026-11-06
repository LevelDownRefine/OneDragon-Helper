use crate::dialogs::run_options_editor::RunOptions;
use crate::theme;
use eframe::egui;
use serde::{Deserialize, Serialize};

#[derive(Clone, Deserialize, Serialize)]
pub struct DailyPlan {
    pub enabled: bool,
    pub target_time: String,
    pub run_options: RunOptions,
    #[serde(default)]
    pub selected_scripts: Option<Vec<String>>,
}

#[derive(Deserialize)]
pub struct PlanScript {
    id: String,
    display_name: String,
}

#[derive(Clone, Deserialize)]
pub struct TaskState {
    exists: bool,
    enabled: bool,
    target_time: String,
    entry_matches: bool,
}

#[derive(Deserialize)]
pub struct PlanEntry {
    pub id: String,
    pub name: String,
    pub plan: DailyPlan,
    state: Option<TaskState>,
    state_error: Option<String>,
}

#[derive(Deserialize)]
pub struct DailyView {
    pub plans: Vec<PlanEntry>,
    #[serde(default)]
    pub scripts: Vec<PlanScript>,
    pub supported: bool,
    #[serde(skip)]
    pub editing: Option<PlanEntry>,
    #[serde(skip)]
    pub delete_id: Option<String>,
}

impl DailyView {
    pub fn show(
        &mut self,
        ui: &mut egui::Ui,
        shutdown_supported: bool,
        defaults: &RunOptions,
    ) -> Option<onedragon_rust_gui::backend::Request> {
        let mut request = None;
        if let Some(draft) = &mut self.editing {
            crate::dialogs::common::form_section(ui, "计划时间", |ui| {
                ui.horizontal(|ui| {
                    ui.label("名称");
                    ui.text_edit_singleline(&mut draft.name);
                });
                ui.colored_label(theme::MUTED, "每个计划单独选择脚本，脚本设置共用。");
                ui.horizontal(|ui| {
                    ui.checkbox(&mut draft.plan.enabled, "启用每日计划");
                    ui.label("每天");
                    ui.add(
                        crate::dialogs::common::text_input(&mut draft.plan.target_time)
                            .desired_width(70.0)
                            .hint_text("04:10"),
                    );
                });
                if let Some(state) = &draft.state {
                    let status = if !state.exists {
                        "未注册"
                    } else if state.enabled {
                        "已启用"
                    } else {
                        "已禁用"
                    };
                    ui.label(format!("系统任务：{status} {}", state.target_time));
                    if state.exists && !state.entry_matches {
                        ui.colored_label(theme::MUTED, "任务入口不一致，保存后更新。");
                    }
                }
                if let Some(error) = &draft.state_error {
                    ui.colored_label(
                        egui::Color32::LIGHT_RED,
                        format!("系统任务状态未知：{error}"),
                    );
                }
                ui.small("关闭助手后仍有效；需开机并登录，错过时间不补跑。");
            });
            crate::dialogs::common::form_section(ui, "运行脚本", |ui| {
                let mut all = draft.plan.selected_scripts.is_none();
                if ui
                    .checkbox(&mut all, "全部脚本（包括以后添加的脚本）")
                    .changed()
                {
                    draft.plan.selected_scripts = if all {
                        None
                    } else {
                        Some(
                            self.scripts
                                .iter()
                                .map(|script| script.id.clone())
                                .collect(),
                        )
                    };
                }
                if let Some(selected) = &mut draft.plan.selected_scripts {
                    for script in &self.scripts {
                        let mut checked = selected.contains(&script.id);
                        if ui.checkbox(&mut checked, &script.display_name).changed() {
                            if checked {
                                selected.push(script.id.clone());
                            } else {
                                selected.retain(|id| id != &script.id);
                            }
                        }
                    }
                    if selected
                        .iter()
                        .any(|id| !self.scripts.iter().any(|script| &script.id == id))
                    {
                        ui.colored_label(theme::MUTED, "部分已选脚本当前不可用，保存时会保留。 ");
                    }
                    if selected.is_empty() {
                        ui.colored_label(theme::MUTED, "未选择脚本，此计划到时间时不会运行。");
                    }
                }
            });
            draft.plan.run_options.show(ui, shutdown_supported);
        } else {
            if !self.supported {
                ui.colored_label(theme::MUTED, "每日计划仅支持 Windows。");
            }
            if ui
                .add_enabled(self.supported, egui::Button::new("新增计划"))
                .clicked()
            {
                let mut options = defaults.clone();
                options.auth_code.clear();
                self.editing = Some(PlanEntry {
                    id: String::new(),
                    name: "新计划".into(),
                    plan: DailyPlan {
                        enabled: false,
                        target_time: "04:10".into(),
                        run_options: options,
                        selected_scripts: None,
                    },
                    state: None,
                    state_error: None,
                });
            }
            for item in &self.plans {
                ui.horizontal(|ui| {
                    let status = if item.plan.enabled {
                        "已启用"
                    } else {
                        "已停用"
                    };
                    ui.label(format!(
                        "{}  每天 {}  {}",
                        item.name, item.plan.target_time, status
                    ));
                    if ui.button("编辑").clicked() {
                        let mut plan = item.plan.clone();
                        plan.run_options.form_defaults();
                        self.editing = Some(PlanEntry {
                            id: item.id.clone(),
                            name: item.name.clone(),
                            plan,
                            state: item.state.clone(),
                            state_error: item.state_error.clone(),
                        });
                    }
                    if ui.button("复制").clicked() {
                        let mut plan = item.plan.clone();
                        plan.enabled = false;
                        plan.run_options.auth_code.clear();
                        self.editing = Some(PlanEntry {
                            id: String::new(),
                            name: format!("{} 副本", item.name),
                            plan,
                            state: None,
                            state_error: None,
                        });
                    }
                    if ui.button("删除").clicked() {
                        self.delete_id = Some(item.id.clone());
                    }
                });
                if let Some(error) = &item.state_error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                } else if let Some(state) = &item.state
                    && item.plan.enabled
                    && (!state.exists
                        || !state.enabled
                        || !state.entry_matches
                        || state.target_time != item.plan.target_time)
                {
                    ui.colored_label(
                        egui::Color32::LIGHT_RED,
                        "系统任务状态不一致，请编辑保存修复。",
                    );
                }
            }
            if let Some(id) = self.delete_id.clone() {
                ui.horizontal(|ui| {
                    ui.label("确定删除该计划？");
                    if ui.button("确认删除").clicked() {
                        request = Some(onedragon_rust_gui::backend::Request {
                            method: "plans.delete".into(),
                            params: serde_json::json!({"id":id}),
                        });
                    }
                    if ui.button("取消删除").clicked() {
                        self.delete_id = None;
                    }
                });
            }
        }
        request
    }

    pub fn save_request(&self) -> Option<onedragon_rust_gui::backend::Request> {
        self.editing.as_ref().map(|draft| onedragon_rust_gui::backend::Request { method: "plans.save".into(), params: serde_json::json!({"id":draft.id,"name":draft.name,"enabled":draft.plan.enabled,"target_time":draft.plan.target_time,"run_options":draft.plan.run_options,"selected_scripts":draft.plan.selected_scripts}) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn saves_selection_and_preserves_all_scripts_default() {
        let value = json!({
            "plans": [], "supported": true,
            "scripts": [{"id": "a", "display_name": "脚本 A"}],
        });
        let mut view: DailyView = serde_json::from_value(value).unwrap();
        let options: RunOptions = serde_json::from_value(json!({
            "shutdown_enabled": false, "shutdown_delay": 0, "mute_enabled": false,
            "unmute_enabled": false, "close_running_enabled": false,
            "rerun_enabled": false, "notify_enabled": false, "email": "",
            "smtp_host": "", "smtp_port": "", "auth_code": ""
        }))
        .unwrap();
        view.editing = Some(PlanEntry {
            id: "default".into(),
            name: "默认".into(),
            state: None,
            state_error: None,
            plan: DailyPlan {
                enabled: true,
                target_time: "04:10".into(),
                run_options: options,
                selected_scripts: None,
            },
        });
        assert!(view.save_request().unwrap().params["selected_scripts"].is_null());
        view.editing.as_mut().unwrap().plan.selected_scripts =
            Some(vec!["a".into(), "missing".into()]);
        assert_eq!(
            view.save_request().unwrap().params["selected_scripts"],
            json!(["a", "missing"])
        );
        view.editing.as_mut().unwrap().plan.selected_scripts = Some(vec![]);
        assert_eq!(
            view.save_request().unwrap().params["selected_scripts"],
            json!([])
        );
    }
}
