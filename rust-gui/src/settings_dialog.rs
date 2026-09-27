use crate::{daily_plan::DailyView, run_dialog::RunOptions, skin};
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::time::{Duration, Instant};

#[derive(Clone, Deserialize, Serialize)]
pub struct StartupOptions {
    pub enabled: bool,
    pub delay_seconds: u64,
}

#[derive(Deserialize)]
pub struct SettingsView {
    pub startup: StartupOptions,
    pub daily_enabled: bool,
    pub run_options: RunOptions,
    pub shutdown_supported: bool,
}

pub enum SettingsAction {
    Backup(bool),
    Request(Request),
    Close,
}

pub struct SettingsDialog {
    data: SettingsView,
    run_draft: Option<RunOptions>,
    daily_draft: Option<DailyView>,
    error: Option<String>,
    needs_reload: bool,
}

impl SettingsDialog {
    pub fn new(mut data: SettingsView) -> Self {
        data.run_options.form_defaults();
        Self {
            data,
            run_draft: None,
            daily_draft: None,
            error: None,
            needs_reload: false,
        }
    }

    pub fn set_daily(&mut self, mut data: DailyView) {
        data.plan.run_options.form_defaults();
        self.data.daily_enabled = data.plan.enabled;
        self.daily_draft = Some(data);
        self.error = None;
        self.needs_reload = false;
    }

    #[cfg(feature = "capture")]
    pub fn is_daily(&self) -> bool {
        self.daily_draft.is_some()
    }

    pub fn failure(&mut self, message: String, reload: bool) {
        self.error = Some(message);
        self.needs_reload = reload;
    }

    pub fn refresh_run(&mut self, data: SettingsView) {
        // A nested save must preserve the parent startup draft.
        self.data.run_options = data.run_options;
        self.data.daily_enabled = data.daily_enabled;
        self.data.shutdown_supported = data.shutdown_supported;
        self.run_draft = None;
        self.error = None;
        self.needs_reload = false;
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<SettingsAction> {
        let mut action = None;
        let mut back = false;
        let modal = egui::Modal::new("global-settings".into())
            .frame(
                egui::Frame::new()
                    .fill(skin::PANEL)
                    .stroke(egui::Stroke::new(1.0, skin::BORDER))
                    .corner_radius(16)
                    .inner_margin(20),
            )
            .show(ctx, |ui| {
                ui.set_width(500.0);
                ui.heading(if self.daily_draft.is_some() {
                    "每日计划"
                } else if self.run_draft.is_some() {
                    "运行选项"
                } else {
                    "配置"
                });
                ui.add_space(12.0);
                ui.add_enabled_ui(!busy && !self.needs_reload, |ui| {
                    if let Some(draft) = &mut self.daily_draft {
                        egui::ScrollArea::vertical()
                            .max_height(480.0)
                            .show(ui, |ui| draft.show(ui));
                    } else if let Some(draft) = &mut self.run_draft {
                        egui::ScrollArea::vertical()
                            .max_height(480.0)
                            .show(ui, |ui| draft.show(ui, self.data.shutdown_supported));
                    } else {
                        ui.add_enabled_ui(!self.data.daily_enabled, |ui| {
                            ui.checkbox(&mut self.data.startup.enabled, "打开后自动运行勾选脚本");
                            ui.horizontal(|ui| {
                                ui.label("倒计时");
                                ui.add_enabled(
                                    self.data.startup.enabled,
                                    egui::DragValue::new(&mut self.data.startup.delay_seconds)
                                        .range(1..=3600)
                                        .suffix(" 秒"),
                                );
                            });
                        });
                        if self.data.daily_enabled {
                            ui.small("每日计划已开启，打开窗口不会自动运行。");
                        }
                        ui.separator();
                        if ui
                            .add_sized(
                                [500.0, 42.0],
                                egui::Button::new("运行选项 · 静音、重跑、通知与关机"),
                            )
                            .clicked()
                        {
                            self.run_draft = Some(self.data.run_options.clone());
                        }
                        if ui
                            .add_sized(
                                [500.0, 42.0],
                                egui::Button::new("每日计划 · 每日时间与独立运行选项"),
                            )
                            .clicked()
                        {
                            action = Some(SettingsAction::Request(Request {
                                method: "plan.view".into(),
                                params: json!({}),
                            }));
                        }
                        for (label, restore) in [("备份配置", false), ("恢复配置", true)] {
                            if ui
                                .add_sized([500.0, 40.0], egui::Button::new(label))
                                .clicked()
                            {
                                action = Some(SettingsAction::Backup(restore));
                            }
                        }
                        ui.add_enabled(
                            false,
                            egui::Button::new("更新 · 暂不可用").min_size(egui::vec2(500.0, 40.0)),
                        );
                    }
                });
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                if self.needs_reload {
                    ui.label("配置可能已保存，请重新读取核对。");
                }
                ui.add_space(12.0);
                ui.horizontal(|ui| {
                    if ui.add_enabled(!busy, egui::Button::new("取消")).clicked() {
                        back = true;
                    }
                    if ui
                        .add_enabled(!busy, egui::Button::new("重新读取"))
                        .clicked()
                    {
                        action = Some(SettingsAction::Request(Request {
                            method: if self.daily_draft.is_some() {
                                "plan.view"
                            } else {
                                "settings.view"
                            }
                            .into(),
                            params: json!({}),
                        }));
                    }
                    if ui
                        .add_enabled(
                            !busy
                                && !self.needs_reload
                                && self
                                    .daily_draft
                                    .as_ref()
                                    .is_none_or(|draft| draft.supported),
                            egui::Button::new("保存"),
                        )
                        .clicked()
                    {
                        if let Some(draft) = &self.daily_draft {
                            action = Some(SettingsAction::Request(Request {
                                method: "plan.save".into(),
                                params: json!({"plan":draft.plan}),
                            }));
                            return;
                        }
                        let (method, options) = if let Some(draft) = &self.run_draft {
                            ("settings.run_save", json!(draft))
                        } else {
                            ("settings.startup_save", json!(self.data.startup))
                        };
                        action = Some(SettingsAction::Request(Request {
                            method: method.into(),
                            params: json!({"options":options}),
                        }));
                    }
                    if busy {
                        ui.spinner();
                    }
                });
            });
        if !busy && (back || modal.should_close()) {
            if self.daily_draft.is_some() && !self.needs_reload {
                self.daily_draft = None;
                self.error = None;
            } else if self.run_draft.is_some() && !self.needs_reload {
                self.run_draft = None;
                self.error = None;
            } else {
                action = Some(SettingsAction::Close);
            }
        }
        action
    }
}

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
        let modal = egui::Modal::new("startup-countdown".into())
            .frame(
                egui::Frame::new()
                    .fill(skin::PANEL)
                    .corner_radius(16)
                    .inner_margin(24),
            )
            .show(ctx, |ui| {
                ui.set_width(420.0);
                ui.heading("即将启动勾选脚本");
                ui.add_space(16.0);
                ui.label(format!("将在 {remaining} 秒后按上次配置启动"));
                ui.add_space(16.0);
                ui.horizontal(|ui| {
                    if ui.button("取消").clicked() {
                        action = Some(false);
                    }
                    if ui.button("立即启动").clicked() {
                        action = Some(true);
                    }
                });
            });
        if modal.should_close() || ctx.input(|input| input.viewport().close_requested()) {
            return Some(false);
        }
        ctx.request_repaint_after(Duration::from_millis(100));
        action.or_else(|| (remaining == 0).then_some(true))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn data() -> SettingsView {
        serde_json::from_value(json!({"startup":{"enabled":true,"delay_seconds":60},"daily_enabled":false,"shutdown_supported":false,"run_options":{"shutdown_enabled":false,"shutdown_delay":0,"mute_enabled":false,"unmute_enabled":false,"close_running_enabled":false,"rerun_enabled":false,"notify_enabled":false,"email":"","smtp_host":"","smtp_port":"","auth_code":""}})).unwrap()
    }

    #[test]
    fn daily_refresh_preserves_startup_and_cancel_keeps_saved_plan_state() {
        let mut dialog = SettingsDialog::new(data());
        dialog.data.startup.delay_seconds = 99;
        let plan = json!({"plan":{"enabled":true,"target_time":"04:10","run_options":dialog.data.run_options},"state":null,"state_error":"denied","supported":true,"shutdown_supported":false});
        dialog.set_daily(serde_json::from_value(plan).unwrap());
        assert!(dialog.data.daily_enabled);
        assert_eq!(
            dialog
                .daily_draft
                .as_ref()
                .unwrap()
                .plan
                .run_options
                .smtp_host,
            "smtp.qq.com"
        );
        assert_eq!(dialog.data.startup.delay_seconds, 99);
        dialog.daily_draft.as_mut().unwrap().plan.enabled = false;
        let ctx = egui::Context::default();
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                dialog.show(ui.ctx(), false);
            });
            output.textures_delta.clear();
        }
        let mut input = egui::RawInput::default();
        input.events.push(egui::Event::Key {
            key: egui::Key::Escape,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: Default::default(),
        });
        let mut output = ctx.run_ui(input, |ui| {
            assert!(dialog.show(ui.ctx(), false).is_none());
        });
        output.textures_delta.clear();
        assert!(dialog.daily_draft.is_none());
        assert!(
            dialog.data.daily_enabled,
            "cancel must retain saved daily state"
        );
    }

    #[test]
    fn nested_save_preserves_startup_draft_and_clears_credential() {
        let mut dialog = SettingsDialog::new(data());
        dialog.data.startup.delay_seconds = 99;
        dialog.run_draft = Some(dialog.data.run_options.clone());
        dialog.run_draft.as_mut().unwrap().auth_code = "secret".into();
        dialog.refresh_run(data());
        assert_eq!(dialog.data.startup.delay_seconds, 99);
        assert!(dialog.run_draft.is_none());
        assert!(dialog.data.run_options.auth_code.is_empty());
    }

    #[test]
    fn startup_disabled_for_daily_plan_and_escape_cancels() {
        let mut data = data();
        data.daily_enabled = true;
        assert!(StartupDialog::from_settings(&data).is_none());
        data.daily_enabled = false;
        let mut dialog = StartupDialog::from_settings(&data).unwrap();
        let ctx = egui::Context::default();
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(dialog.show(ui.ctx()).is_none());
            });
            output.textures_delta.clear();
        }
        let mut input = egui::RawInput::default();
        input.events.push(egui::Event::Key {
            key: egui::Key::Escape,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: Default::default(),
        });
        let mut output = ctx.run_ui(input, |ui| assert_eq!(dialog.show(ui.ctx()), Some(false)));
        output.textures_delta.clear();
    }
}
