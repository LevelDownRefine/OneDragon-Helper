use crate::dialogs::{daily_plan_dialog::DailyView, run_options_editor::RunOptions};
use crate::theme;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::{Deserialize, Serialize};
use serde_json::json;

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
        let (title, description) = if self.daily_draft.is_some() {
            ("每日计划", "设置每天的运行时间与独立运行选项")
        } else if self.run_draft.is_some() {
            ("运行选项", "管理脚本运行前后的动作")
        } else {
            ("配置", "运行设置、配置备份与程序更新")
        };
        let close = crate::dialogs::common::Dialog::new("global-settings", title)
            .description(description)
            .show(ctx, !busy, |ui| {
                crate::dialogs::common::dialog_body(ui, |ui| {
                    ui.add_enabled_ui(!busy && !self.needs_reload, |ui| {
                        if let Some(draft) = &mut self.daily_draft {
                            draft.show(ui);
                        } else if let Some(draft) = &mut self.run_draft {
                            draft.show(ui, self.data.shutdown_supported);
                        } else {
                            crate::dialogs::common::form_section(ui, "启动行为", |ui| {
                                ui.add_enabled_ui(!self.data.daily_enabled, |ui| {
                                    ui.checkbox(
                                        &mut self.data.startup.enabled,
                                        "打开助手后自动运行勾选脚本",
                                    );
                                    ui.horizontal(|ui| {
                                        ui.label(
                                            egui::RichText::new("启动前等待").color(theme::MUTED),
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
                                        .color(theme::MUTED),
                                    );
                                }
                            });
                            ui.add_space(2.0);
                            ui.label(
                                egui::RichText::new("运行与计划")
                                    .size(12.0)
                                    .color(theme::MUTED),
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
                                    .color(theme::MUTED),
                            );
                            ui.columns(2, |columns| {
                                for (index, title, description, restore) in [
                                    (0, "备份配置", "保存配置到 ZIP 文件", false),
                                    (1, "恢复配置", "从 ZIP 恢复，保留本机路径", true),
                                ] {
                                    if action_row(&mut columns[index], title, title, description)
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
                        }
                    });
                });
                crate::dialogs::common::dialog_status(
                    ui,
                    self.error.as_deref(),
                    self.needs_reload.then_some("配置可能已保存，请刷新核对。"),
                );
                crate::dialogs::common::dialog_footer(ui, |ui| {
                    if ui
                        .add_enabled(
                            !busy
                                && !self.needs_reload
                                && self
                                    .daily_draft
                                    .as_ref()
                                    .is_none_or(|draft| draft.supported),
                            crate::dialogs::common::primary_button("保存"),
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
                        .add_enabled(!busy, crate::dialogs::common::secondary_button("取消"))
                        .clicked()
                    {
                        back = true;
                    }
                    if busy {
                        ui.spinner();
                    }
                    ui.with_layout(egui::Layout::left_to_right(egui::Align::Center), |ui| {
                        if ui
                            .add_enabled(!busy, crate::dialogs::common::secondary_button("刷新"))
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
                    });
                });
            });
        if !busy && (back || close) {
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
        if active { theme::HOVER } else { theme::CONTROL },
        egui::Stroke::new(
            1.0,
            if active {
                theme::ACCENT
            } else {
                theme::DIVIDER
            },
        ),
        egui::StrokeKind::Inside,
    );
    let text_rect = egui::Rect::from_min_max(
        rect.min + egui::vec2(16.0, 6.0),
        rect.max - egui::vec2(32.0, 6.0),
    );
    theme::label(
        ui,
        egui::Rect::from_min_size(text_rect.min, egui::vec2(text_rect.width(), 23.0)),
        title,
        15.0,
        theme::TEXT,
    );
    theme::label(
        ui,
        egui::Rect::from_min_size(
            text_rect.min + egui::vec2(0.0, 23.0),
            egui::vec2(text_rect.width(), 19.0),
        ),
        description,
        12.0,
        theme::MUTED,
    );
    let center = egui::pos2(rect.right() - 18.0, rect.center().y);
    ui.painter().add(egui::Shape::line(
        vec![
            center + egui::vec2(-3.0, -5.0),
            center + egui::vec2(2.0, 0.0),
            center + egui::vec2(-3.0, 5.0),
        ],
        egui::Stroke::new(1.5, theme::MUTED),
    ));
    response.on_hover_cursor(egui::CursorIcon::PointingHand)
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/dialogs/config_dialog.rs"]
mod tests;
