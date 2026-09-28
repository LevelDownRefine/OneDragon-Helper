use crate::config_dialog::SettingsView;
use eframe::egui;
use std::time::{Duration, Instant};

pub struct StartupDialog {
    seconds: u64,
    started: Option<Instant>,
}

impl StartupDialog {
    pub fn from_settings(data: &SettingsView) -> Option<Self> {
        (data.startup.enabled && !data.daily_enabled).then_some(Self {
            seconds: data.startup.delay_seconds,
            started: None,
        })
    }

    pub fn show(&mut self, ctx: &egui::Context) -> Option<bool> {
        let started = *self.started.get_or_insert_with(Instant::now);
        let remaining = self.seconds.saturating_sub(started.elapsed().as_secs());
        let mut action = None;
        let close = crate::dialogs::Dialog::new("startup-countdown", "即将启动勾选脚本")
            .width(420.0)
            .description("按已保存的运行选项执行")
            .show(ctx, true, |ui| {
                crate::dialogs::form_section(ui, "启动倒计时", |ui| {
                    ui.label(format!("将在 {remaining} 秒后按上次配置启动"));
                });
                crate::dialogs::dialog_footer(ui, |ui| {
                    if ui.add(crate::dialogs::primary_button("立即启动")).clicked() {
                        action = Some(true);
                    }
                    if ui.add(crate::dialogs::secondary_button("取消")).clicked() {
                        action = Some(false);
                    }
                });
            });
        if close || ctx.input(|input| input.viewport().close_requested()) {
            return Some(false);
        }
        ctx.request_repaint_after(Duration::from_millis(100));
        action.or_else(|| (remaining == 0).then_some(true))
    }
}

#[cfg(test)]
#[path = "../../tests/rust-gui/startup_dialog.rs"]
mod tests;
