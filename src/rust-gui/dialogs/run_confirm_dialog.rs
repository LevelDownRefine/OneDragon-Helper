use crate::dialogs::run_options_editor::RunOptions;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct InvalidScript {
    name: String,
    reason: String,
}

#[derive(Deserialize)]
pub struct RunView {
    script_names: Vec<String>,
    invalid: Vec<InvalidScript>,
    options: RunOptions,
    shutdown_supported: bool,
}

pub enum RunAction {
    Request(Request),
    Cancel,
}

pub struct RunDialog {
    data: RunView,
    confirm_invalid: bool,
    error: Option<String>,
    needs_reload: bool,
}

impl RunDialog {
    pub fn new(mut data: RunView) -> Self {
        data.options.form_defaults();
        Self {
            data,
            confirm_invalid: false,
            error: None,
            needs_reload: false,
        }
    }

    pub fn failure(&mut self, message: String, needs_reload: bool) {
        self.error = Some(message);
        self.needs_reload = needs_reload;
    }

    fn request(&self) -> Result<Request, String> {
        if !self.data.invalid.is_empty() && !self.confirm_invalid {
            return Err("请确认将跳过配置不合法的脚本".into());
        }
        if self.data.options.shutdown_enabled && !self.data.shutdown_supported {
            return Err("请先关闭暂不可用的自动关机选项".into());
        }
        Ok(Request {
            method: "run.prepare".into(),
            params: json!({"script_names":self.data.script_names,"options":self.data.options,"confirm_invalid":self.confirm_invalid}),
        })
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<RunAction> {
        let mut action = None;
        let close = crate::dialogs::common::Dialog::new(
            "run-confirm",
            &format!("确认运行 {} 个脚本", self.data.script_names.len()),
        )
        .description("检查本次运行选项，确认后开始执行")
        .show(ctx, !busy, |ui| {
            crate::dialogs::common::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!busy && !self.needs_reload, |ui| {
                    if !self.data.invalid.is_empty() {
                        ui.colored_label(egui::Color32::LIGHT_RED, "以下脚本将在运行时跳过：");
                        for invalid in &self.data.invalid {
                            ui.label(format!("{}：{}", invalid.name, invalid.reason));
                        }
                        ui.checkbox(&mut self.confirm_invalid, "仍然运行有效脚本");
                        ui.separator();
                    }
                    self.data.options.show(ui, self.data.shutdown_supported);
                });
            });
            crate::dialogs::common::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("选项可能已保存，请刷新核对；不会自动启动。"),
            );
            crate::dialogs::common::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !busy && !self.needs_reload,
                        crate::dialogs::common::primary_button("确认运行"),
                    )
                    .clicked()
                {
                    match self.request() {
                        Ok(request) => action = Some(RunAction::Request(request)),
                        Err(error) => self.error = Some(error),
                    }
                }
                if ui
                    .add_enabled(!busy, crate::dialogs::common::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(RunAction::Cancel);
                }
                if ui
                    .add_enabled(!busy, crate::dialogs::common::secondary_button("刷新"))
                    .clicked()
                {
                    action = Some(RunAction::Request(Request {
                        method: "run.view".into(),
                        params: json!({"script_names":self.data.script_names}),
                    }));
                }
                if busy {
                    ui.spinner();
                }
            });
        });
        if close {
            action = Some(RunAction::Cancel);
        }
        action
    }
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/dialogs/run_confirm_dialog.rs"]
mod tests;
