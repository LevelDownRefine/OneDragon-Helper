use crate::{run_dialog::RunOptions, skin};
use eframe::egui;
use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize)]
pub struct DailyPlan {
    pub enabled: bool,
    pub target_time: String,
    pub run_options: RunOptions,
}

#[derive(Deserialize)]
pub struct TaskState {
    exists: bool,
    enabled: bool,
    target_time: String,
    entry_matches: bool,
}

#[derive(Deserialize)]
pub struct DailyView {
    pub plan: DailyPlan,
    state: Option<TaskState>,
    state_error: Option<String>,
    pub supported: bool,
    shutdown_supported: bool,
}

impl DailyView {
    pub fn show(&mut self, ui: &mut egui::Ui) {
        ui.label("每日计划对所有脚本生效，运行选项单独设置。");
        ui.horizontal(|ui| {
            ui.checkbox(&mut self.plan.enabled, "启用每日计划");
            ui.label("每天");
            ui.add(
                egui::TextEdit::singleline(&mut self.plan.target_time)
                    .desired_width(70.0)
                    .hint_text("04:10"),
            );
        });
        if let Some(state) = &self.state {
            let status = if !state.exists {
                "未注册"
            } else if state.enabled {
                "已启用"
            } else {
                "已禁用"
            };
            ui.label(format!("系统任务：{status} {}", state.target_time));
            if state.exists && !state.entry_matches {
                ui.colored_label(skin::MUTED, "任务入口与当前 Rust 前端不一致，保存后更新。");
            }
        }
        if let Some(error) = &self.state_error {
            ui.colored_label(
                egui::Color32::LIGHT_RED,
                format!("系统任务状态未知：{error}"),
            );
        }
        if !self.supported {
            ui.colored_label(skin::MUTED, "每日计划仅支持 Windows。");
        }
        ui.small("暂停后保留设置；关闭助手后仍有效。需开机并登录，错过时间不补跑。");
        ui.separator();
        self.plan.run_options.show(ui, self.shutdown_supported);
    }
}
