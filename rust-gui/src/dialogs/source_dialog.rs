use crate::dialogs::common;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::Path,
    time::{Duration, Instant},
};

#[derive(Deserialize)]
struct Application {
    display_name: String,
    entry: String,
    manual_arguments: Vec<String>,
    run_arguments: Vec<String>,
}

pub enum SourceAction {
    Request(Request),
    Close,
}

pub struct SourceDialog {
    catalog: BTreeMap<String, Application>,
    selected: String,
    job: Option<String>,
    awaiting: bool,
    next_poll: Instant,
    message: String,
    error: Option<String>,
    finished: bool,
}

impl SourceDialog {
    pub fn new() -> Self {
        Self {
            catalog: BTreeMap::new(),
            selected: String::new(),
            job: None,
            awaiting: true,
            next_poll: Instant::now(),
            message: String::new(),
            error: None,
            finished: false,
        }
    }
    pub fn active(&self) -> bool {
        self.awaiting || self.job.is_some()
    }
    pub fn failure(&mut self, message: String) {
        self.awaiting = false;
        self.job = None;
        self.error = Some(message);
    }
    pub fn poll(&mut self) -> Option<Request> {
        let id = self.job.as_ref()?;
        if Instant::now() < self.next_poll {
            return None;
        }
        self.next_poll = Instant::now() + Duration::from_millis(400);
        Some(Request {
            method: "job.poll".into(),
            params: json!({"job_id": id}),
        })
    }
    pub fn receive(&mut self, method: &str, value: Value) -> Result<Option<Request>, String> {
        match method {
            "source.catalog" => {
                self.catalog =
                    serde_json::from_value(value).map_err(|e| format!("应用列表无效：{e}"))?;
                self.selected = self.catalog.keys().next().ok_or("应用列表为空")?.clone();
                self.awaiting = false;
            }
            "source.install_catalog" => {
                let id = value
                    .get("id")
                    .and_then(Value::as_str)
                    .filter(|id| !id.is_empty())
                    .ok_or("任务编号无效")?;
                self.job = Some(id.into());
                self.awaiting = false;
                self.next_poll = Instant::now();
            }
            "job.poll" => {
                if value.get("id").and_then(Value::as_str) != self.job.as_deref()
                    || value.get("kind").and_then(Value::as_str) != Some("source_install")
                {
                    return Err("安装任务身份不匹配".into());
                }
                if let Some(message) = value.get("message").and_then(Value::as_str) {
                    self.message = message.to_owned();
                }
                match value.get("state").and_then(Value::as_str) {
                    Some("running") => {}
                    Some("failed") => {
                        self.job = None;
                        self.error = Some(
                            value
                                .get("error")
                                .and_then(Value::as_str)
                                .ok_or("任务错误信息缺失")?
                                .into(),
                        );
                    }
                    Some("succeeded") => {
                        let source = value
                            .get("result")
                            .and_then(|v| v.get("source"))
                            .and_then(Value::as_str)
                            .filter(|s| !s.is_empty())
                            .ok_or("安装结果无效")?;
                        let app = self.catalog.get(&self.selected).ok_or("应用声明不存在")?;
                        let entry = Path::new(source)
                            .join(&app.entry)
                            .to_string_lossy()
                            .into_owned();
                        self.job = None;
                        self.awaiting = true;
                        return Ok(Some(Request {
                            method: "source.register".into(),
                            params: json!({"application_id": self.selected, "display_name": app.display_name, "source_root": source, "script_path": entry, "manual_arguments": app.manual_arguments, "run_arguments": app.run_arguments}),
                        }));
                    }
                    _ => return Err("任务状态无效".into()),
                }
            }
            "source.register" => {
                if value.get("script_name").and_then(Value::as_str) != Some(self.selected.as_str())
                {
                    return Err("注册结果无效".into());
                }
                self.awaiting = false;
                self.finished = true;
                self.message = "安装完成".into();
            }
            _ => return Err("未知响应".into()),
        }
        Ok(None)
    }
    fn install_request(&mut self) -> Request {
        self.error = None;
        self.awaiting = true;
        Request {
            method: "source.install_catalog".into(),
            params: json!({"application_id": self.selected}),
        }
    }

    pub fn show(&mut self, ctx: &egui::Context, blocked: bool) -> Option<SourceAction> {
        let active = self.active();
        let mut action = None;
        let close = common::Dialog::new("source-install", "安装源码应用")
            .description("选择应用，首次安装需要下载依赖")
            .show(ctx, !blocked && !active, |ui| {
                common::dialog_body(ui, |ui| {
                    ui.add_enabled_ui(!blocked && !active && !self.finished, |ui| {
                        common::form_section(ui, "安装配置", |ui| {
                            let label = self
                                .catalog
                                .get(&self.selected)
                                .map(|app| app.display_name.as_str())
                                .unwrap_or("正在读取应用列表");
                            egui::ComboBox::from_id_salt("source-app")
                                .selected_text(label)
                                .show_ui(ui, |ui| {
                                    for (id, app) in &self.catalog {
                                        ui.selectable_value(
                                            &mut self.selected,
                                            id.clone(),
                                            &app.display_name,
                                        );
                                    }
                                });
                        });
                    });
                });
                common::dialog_status(
                    ui,
                    self.error.as_deref(),
                    (!self.message.is_empty()).then_some(self.message.as_str()),
                );
                common::dialog_footer(ui, |ui| {
                    if ui
                        .add_enabled(
                            !blocked && !active && !self.finished && !self.selected.is_empty(),
                            common::primary_button("安装"),
                        )
                        .clicked()
                    {
                        action = Some(SourceAction::Request(self.install_request()));
                    }
                    if ui
                        .add_enabled(
                            !blocked && !active,
                            common::secondary_button(if self.finished {
                                "完成"
                            } else {
                                "关闭"
                            }),
                        )
                        .clicked()
                    {
                        action = Some(SourceAction::Close);
                    }
                    if active {
                        ui.spinner();
                    }
                });
            });
        if close {
            action = Some(SourceAction::Close);
        }
        action
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn install_polls_then_registers_catalog_entry() {
        let mut dialog = SourceDialog::new();
        dialog.receive("source.catalog", json!({"app": {"display_name": "应用", "entry": "main.py", "manual_arguments": ["--gui"], "run_arguments": ["--run"]}})).unwrap();
        dialog.awaiting = true;
        dialog
            .receive("source.install_catalog", json!({"id": "job"}))
            .unwrap();
        assert_eq!(dialog.poll().unwrap().method, "job.poll");
        assert!(
            dialog
                .receive(
                    "job.poll",
                    json!({"id": "other", "kind": "source_install", "state": "running"})
                )
                .is_err()
        );
        let request = dialog.receive("job.poll", json!({"id": "job", "kind": "source_install", "state": "succeeded", "result": {"source": "C:/apps/app"}})).unwrap().unwrap();
        assert_eq!(request.method, "source.register");
        assert_eq!(request.params["run_arguments"], json!(["--run"]));
        assert!(dialog.active());
        dialog
            .receive("source.register", json!({"script_name": "app"}))
            .unwrap();
        assert!(dialog.finished);
        assert!(!dialog.active());
    }

    #[test]
    fn install_request_uses_managed_directory() {
        let mut dialog = SourceDialog::new();
        dialog.selected = "ok-ww".into();
        let request = dialog.install_request();
        assert_eq!(request.method, "source.install_catalog");
        assert_eq!(request.params, json!({"application_id": "ok-ww"}));
    }

    #[test]
    fn failed_install_allows_retry() {
        let mut dialog = SourceDialog::new();
        dialog
            .receive("source.install_catalog", json!({"id": "job"}))
            .unwrap();
        dialog.receive("job.poll", json!({"id": "job", "kind": "source_install", "state": "failed", "error": "network"})).unwrap();
        assert_eq!(dialog.error.as_deref(), Some("network"));
        assert!(!dialog.active());
    }
}
