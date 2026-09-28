use crate::skin;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Clone, Deserialize, Serialize)]
pub struct RunOptions {
    pub shutdown_enabled: bool,
    pub shutdown_delay: u32,
    pub mute_enabled: bool,
    pub unmute_enabled: bool,
    pub close_running_enabled: bool,
    pub rerun_enabled: bool,
    pub notify_enabled: bool,
    pub email: String,
    pub smtp_host: String,
    pub smtp_port: String,
    pub auth_code: String,
}

impl RunOptions {
    pub fn form_defaults(&mut self) {
        if self.smtp_host.is_empty() {
            self.smtp_host = "smtp.qq.com".into();
        }
        if self.smtp_port.is_empty() {
            self.smtp_port = "465".into();
        }
    }

    pub fn show(&mut self, ui: &mut egui::Ui, shutdown_supported: bool) {
        skin::form_section(ui, "运行前", |ui| {
            ui.checkbox(&mut self.close_running_enabled, "关闭残留脚本和游戏进程");
            ui.checkbox(&mut self.mute_enabled, "静音");
        });
        skin::form_section(ui, "运行中", |ui| {
            ui.checkbox(&mut self.rerun_enabled, "重跑失败脚本");
        });
        skin::form_section(ui, "运行后", |ui| {
            ui.checkbox(&mut self.unmute_enabled, "开启声音");
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.shutdown_enabled, "自动关机");
                ui.add_enabled(
                    self.shutdown_enabled && shutdown_supported,
                    egui::DragValue::new(&mut self.shutdown_delay)
                        .range(0..=86400)
                        .suffix(" 秒"),
                );
            });
            if !shutdown_supported {
                ui.colored_label(skin::MUTED, "关机确认入口不可用，请关闭此项后运行。");
            }
        });
        skin::form_section(ui, "邮件通知", |ui| {
            ui.checkbox(&mut self.notify_enabled, "运行结束后发送邮件通知");
            ui.add_enabled_ui(self.notify_enabled, |ui| {
                skin::form_grid(ui, "mail-options", |ui| {
                    for (label, text, secret) in [
                        ("邮箱", &mut self.email, false),
                        ("授权码", &mut self.auth_code, true),
                        ("SMTP 主机", &mut self.smtp_host, false),
                        ("SMTP 端口", &mut self.smtp_port, false),
                    ] {
                        ui.label(label);
                        ui.add(skin::text_input(text).password(secret));
                        ui.end_row();
                    }
                });
                ui.label(
                    egui::RichText::new("授权码留空保留已存凭据；仅首次或更换时填写。")
                        .size(12.0)
                        .color(skin::MUTED),
                );
            });
        });
    }
}

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
        let close = skin::Dialog::new(
            "run-confirm",
            &format!("确认运行 {} 个脚本", self.data.script_names.len()),
        )
        .description("检查本次运行选项，确认后开始执行")
        .show(ctx, !busy, |ui| {
            skin::dialog_body(ui, |ui| {
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
            skin::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("选项可能已保存，请重新读取核对；不会自动启动。"),
            );
            skin::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !busy && !self.needs_reload,
                        skin::primary_button("确认运行"),
                    )
                    .clicked()
                {
                    match self.request() {
                        Ok(request) => action = Some(RunAction::Request(request)),
                        Err(error) => self.error = Some(error),
                    }
                }
                if ui
                    .add_enabled(!busy, skin::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(RunAction::Cancel);
                }
                if ui
                    .add_enabled(!busy, skin::secondary_button("重新读取"))
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
mod tests {
    use super::*;
    fn dialog() -> RunDialog {
        RunDialog::new(serde_json::from_value(json!({
            "script_names":["demo"],"invalid":[{"name":"demo","reason":"missing"}],"shutdown_supported":false,
            "options":{"shutdown_enabled":false,"shutdown_delay":60,"mute_enabled":false,"unmute_enabled":false,"close_running_enabled":true,"rerun_enabled":false,"notify_enabled":false,"email":"","smtp_host":"","smtp_port":"","auth_code":""}
        })).unwrap())
    }
    #[test]
    fn confirmation_blocks_invalid_scripts_and_unavailable_shutdown() {
        let mut dialog = dialog();
        assert!(dialog.request().is_err());
        dialog.confirm_invalid = true;
        let request = dialog.request().unwrap();
        assert_eq!(request.method, "run.prepare");
        assert_eq!(request.params["confirm_invalid"], true);
        assert_eq!(request.params["options"]["smtp_port"], "465");
        dialog.data.options.shutdown_enabled = true;
        assert!(dialog.request().is_err());
    }
    #[test]
    fn escape_cancels_without_saving_or_starting() {
        let ctx = egui::Context::default();
        let mut dialog = dialog();
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(dialog.show(ui.ctx(), false).is_none());
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
                cancelled = matches!(dialog.show(ui.ctx(), false), Some(RunAction::Cancel));
            },
        );
        output.textures_delta.clear();
        assert!(cancelled);
    }
}
