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
            .frame(skin::dialog_frame())
            .show(ctx, |ui| {
                ui.set_width(520.0_f32.min((ctx.content_rect().width() - 80.0).max(300.0)));
                skin::dialog_style(ui);
                let (title, description) = if self.daily_draft.is_some() {
                    ("每日计划", "设置每天的运行时间与独立运行选项")
                } else if self.run_draft.is_some() {
                    ("运行选项", "管理脚本运行前后的动作")
                } else {
                    ("配置", "运行设置、配置备份与程序更新")
                };
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new(title).size(22.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add_enabled(!busy, egui::Button::new("×").frame(false))
                            .on_hover_text("关闭")
                            .clicked()
                        {
                            back = true;
                        }
                    });
                });
                ui.label(
                    egui::RichText::new(description)
                        .size(12.0)
                        .color(skin::MUTED),
                );
                ui.add_space(6.0);
                ui.add_enabled_ui(!busy && !self.needs_reload, |ui| {
                    if let Some(draft) = &mut self.daily_draft {
                        egui::ScrollArea::vertical()
                            .max_height((ctx.content_rect().height() - 230.0).max(180.0))
                            .show(ui, |ui| draft.show(ui));
                    } else if let Some(draft) = &mut self.run_draft {
                        egui::ScrollArea::vertical()
                            .max_height((ctx.content_rect().height() - 230.0).max(180.0))
                            .show(ui, |ui| draft.show(ui, self.data.shutdown_supported));
                    } else {
                        egui::ScrollArea::vertical()
                            .id_salt("settings-home")
                            .max_height((ctx.content_rect().height() - 230.0).max(180.0))
                            .show(ui, |ui| {
                                skin::form_section(ui, "启动行为", |ui| {
                                    ui.add_enabled_ui(!self.data.daily_enabled, |ui| {
                                        ui.checkbox(
                                            &mut self.data.startup.enabled,
                                            "打开助手后自动运行勾选脚本",
                                        );
                                        ui.horizontal(|ui| {
                                            ui.label(
                                                egui::RichText::new("启动前等待")
                                                    .color(skin::MUTED),
                                            );
                                            ui.add_enabled(
                                                self.data.startup.enabled,
                                                egui::DragValue::new(
                                                    &mut self.data.startup.delay_seconds,
                                                )
                                                .range(1..=3600)
                                                .suffix(" 秒"),
                                            );
                                        });
                                    });
                                    if self.data.daily_enabled {
                                        ui.label(
                                            egui::RichText::new(
                                                "每日计划已开启，打开窗口不会额外运行。",
                                            )
                                            .size(12.0)
                                            .color(skin::MUTED),
                                        );
                                    }
                                });
                                ui.add_space(2.0);
                                ui.label(
                                    egui::RichText::new("运行与计划")
                                        .size(12.0)
                                        .color(skin::MUTED),
                                );
                                if action_row(
                                    ui,
                                    "run-options",
                                    "运行选项",
                                    "静音、失败重跑、邮件通知与自动关机",
                                )
                                .clicked()
                                {
                                    self.run_draft = Some(self.data.run_options.clone());
                                }
                                if action_row(
                                    ui,
                                    "daily-plan",
                                    "每日计划",
                                    "每天定时运行，使用独立的运行选项",
                                )
                                .clicked()
                                {
                                    action = Some(SettingsAction::Request(Request {
                                        method: "plan.view".into(),
                                        params: json!({}),
                                    }));
                                }
                                ui.add_space(2.0);
                                ui.label(
                                    egui::RichText::new("备份与维护")
                                        .size(12.0)
                                        .color(skin::MUTED),
                                );
                                ui.columns(2, |columns| {
                                    for (index, title, description, restore) in [
                                        (0, "备份配置", "保存配置到 ZIP 文件", false),
                                        (1, "恢复配置", "从 ZIP 恢复，保留本机路径", true),
                                    ] {
                                        if action_row(
                                            &mut columns[index],
                                            title,
                                            title,
                                            description,
                                        )
                                        .clicked()
                                        {
                                            action = Some(SettingsAction::Backup(restore));
                                        }
                                    }
                                });
                                if action_row(
                                    ui,
                                    "app-update",
                                    "助手更新",
                                    "检查新版本，查看下载与安装进度",
                                )
                                .clicked()
                                {
                                    action = Some(SettingsAction::Request(Request {
                                        method: "update.view".into(),
                                        params: json!({}),
                                    }));
                                }
                            });
                    }
                });
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                if self.needs_reload {
                    ui.label("配置可能已保存，请重新读取核对。");
                }
                ui.add_space(4.0);
                ui.separator();
                ui.horizontal(|ui| {
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
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add_enabled(
                                !busy
                                    && !self.needs_reload
                                    && self
                                        .daily_draft
                                        .as_ref()
                                        .is_none_or(|draft| draft.supported),
                                skin::primary_button("保存"),
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
                        if ui
                            .add_enabled(
                                !busy,
                                egui::Button::new("取消").min_size(egui::vec2(78.0, 34.0)),
                            )
                            .clicked()
                        {
                            back = true;
                        }
                        if busy {
                            ui.spinner();
                        }
                    });
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

/// Whole-row hit target with a title and quieter description.
fn action_row(ui: &mut egui::Ui, id: &str, title: &str, description: &str) -> egui::Response {
    let (_, rect) = ui.allocate_space(egui::vec2(ui.available_width(), 54.0));
    let response = ui.interact(
        rect,
        egui::Id::new(("settings-action", id)),
        egui::Sense::click(),
    );
    response.widget_info(|| {
        egui::WidgetInfo::labeled(egui::WidgetType::Button, ui.is_enabled(), title)
    });
    let active = response.hovered() || response.has_focus();
    ui.painter().rect(
        rect,
        10,
        if active { skin::HOVER } else { skin::CONTROL },
        egui::Stroke::new(1.0, if active { skin::ACCENT } else { skin::DIVIDER }),
        egui::StrokeKind::Inside,
    );
    let text_rect = egui::Rect::from_min_max(
        rect.min + egui::vec2(16.0, 6.0),
        rect.max - egui::vec2(32.0, 6.0),
    );
    skin::label(
        ui,
        egui::Rect::from_min_size(text_rect.min, egui::vec2(text_rect.width(), 23.0)),
        title,
        15.0,
        skin::TEXT,
    );
    skin::label(
        ui,
        egui::Rect::from_min_size(
            text_rect.min + egui::vec2(0.0, 23.0),
            egui::vec2(text_rect.width(), 19.0),
        ),
        description,
        12.0,
        skin::MUTED,
    );
    let center = egui::pos2(rect.right() - 18.0, rect.center().y);
    ui.painter().add(egui::Shape::line(
        vec![
            center + egui::vec2(-3.0, -5.0),
            center + egui::vec2(2.0, 0.0),
            center + egui::vec2(-3.0, 5.0),
        ],
        egui::Stroke::new(1.5, skin::MUTED),
    ));
    response.on_hover_cursor(egui::CursorIcon::PointingHand)
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

    fn frame(
        ctx: &egui::Context,
        dialog: &mut SettingsDialog,
        events: Vec<egui::Event>,
        busy: bool,
    ) -> Option<SettingsAction> {
        let mut action = None;
        let mut output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, skin::SIZE)),
                events,
                ..Default::default()
            },
            |ui| action = dialog.show(ui.ctx(), busy),
        );
        output.textures_delta.clear();
        action
    }

    fn click(
        ctx: &egui::Context,
        dialog: &mut SettingsDialog,
        id: &str,
        busy: bool,
    ) -> Option<SettingsAction> {
        let pos = ctx
            .read_response(egui::Id::new(("settings-action", id)))
            .expect("visible settings action")
            .rect
            .center();
        frame(ctx, dialog, vec![egui::Event::PointerMoved(pos)], busy);
        assert_eq!(
            ctx.read_response(egui::Id::new(("settings-action", id)))
                .unwrap()
                .rect
                .center(),
            pos,
            "moved after hover"
        );
        frame(
            ctx,
            dialog,
            vec![
                egui::Event::PointerMoved(pos),
                egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: Default::default(),
                },
            ],
            busy,
        );
        frame(
            ctx,
            dialog,
            vec![egui::Event::PointerButton {
                pos,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: Default::default(),
            }],
            busy,
        )
    }

    #[test]
    fn settings_cards_route_to_existing_actions_and_busy_blocks_them() {
        for busy in [false, true] {
            for id in [
                "run-options",
                "daily-plan",
                "备份配置",
                "恢复配置",
                "app-update",
            ] {
                let ctx = egui::Context::default();
                skin::configure(&ctx);
                let mut dialog = SettingsDialog::new(data());
                for _ in 0..12 {
                    frame(&ctx, &mut dialog, vec![], busy);
                }
                let action = click(&ctx, &mut dialog, id, busy);
                if busy {
                    assert!(action.is_none());
                    assert!(dialog.run_draft.is_none());
                    continue;
                }
                match id {
                    "run-options" => {
                        assert!(action.is_none());
                        assert!(
                            dialog.run_draft.is_some(),
                            "response: {:?}",
                            ctx.read_response(egui::Id::new(("settings-action", id)))
                        );
                    }
                    "备份配置" => {
                        assert!(matches!(action, Some(SettingsAction::Backup(false))))
                    }
                    "恢复配置" => assert!(matches!(action, Some(SettingsAction::Backup(true)))),
                    _ => {
                        let Some(SettingsAction::Request(request)) = action else {
                            panic!("missing request: {id}");
                        };
                        assert_eq!(
                            request.method,
                            if id == "daily-plan" {
                                "plan.view"
                            } else {
                                "update.view"
                            }
                        );
                        assert_eq!(request.params, json!({}));
                    }
                }
            }
        }
    }

    #[test]
    fn settings_card_supports_keyboard_and_failed_save_keeps_actions_disabled() {
        let ctx = egui::Context::default();
        let mut dialog = SettingsDialog::new(data());
        for _ in 0..12 {
            frame(&ctx, &mut dialog, vec![], false);
        }
        ctx.memory_mut(|memory| {
            memory.request_focus(egui::Id::new(("settings-action", "run-options")))
        });
        let action = frame(
            &ctx,
            &mut dialog,
            vec![egui::Event::Key {
                key: egui::Key::Enter,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: Default::default(),
            }],
            false,
        );
        assert!(action.is_none());
        assert!(dialog.run_draft.is_some());
        dialog.run_draft = None;
        dialog.failure("partial save".into(), true);
        for _ in 0..12 {
            frame(&ctx, &mut dialog, vec![], false);
        }
        assert!(click(&ctx, &mut dialog, "run-options", false).is_none());
        assert!(dialog.run_draft.is_none());
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
