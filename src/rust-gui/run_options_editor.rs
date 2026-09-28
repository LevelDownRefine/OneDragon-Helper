use crate::theme;
use eframe::egui;
use serde::{Deserialize, Serialize};

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
        crate::dialogs::form_section(ui, "运行前", |ui| {
            ui.checkbox(&mut self.close_running_enabled, "关闭残留脚本和游戏进程");
            ui.checkbox(&mut self.mute_enabled, "静音");
        });
        crate::dialogs::form_section(ui, "运行中", |ui| {
            ui.checkbox(&mut self.rerun_enabled, "重跑失败脚本");
        });
        crate::dialogs::form_section(ui, "运行后", |ui| {
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
                ui.colored_label(theme::MUTED, "关机确认入口不可用，请关闭此项后运行。");
            }
        });
        crate::dialogs::form_section(ui, "邮件通知", |ui| {
            ui.checkbox(&mut self.notify_enabled, "运行结束后发送邮件通知");
            ui.add_enabled_ui(self.notify_enabled, |ui| {
                crate::dialogs::form_grid(ui, "mail-options", |ui| {
                    for (label, text, secret) in [
                        ("邮箱", &mut self.email, false),
                        ("授权码", &mut self.auth_code, true),
                        ("SMTP 主机", &mut self.smtp_host, false),
                        ("SMTP 端口", &mut self.smtp_port, false),
                    ] {
                        ui.label(label);
                        ui.add(crate::dialogs::text_input(text).password(secret));
                        ui.end_row();
                    }
                });
                ui.label(
                    egui::RichText::new("授权码留空保留已存凭据；仅首次或更换时填写。")
                        .size(12.0)
                        .color(theme::MUTED),
                );
            });
        });
    }
}
