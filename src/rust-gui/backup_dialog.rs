use crate::file_picker::{FileKind, FilePicker};
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::{Duration, Instant};

pub enum BackupAction {
    Request(Request),
    Close,
}

pub struct BackupDialog {
    restore: bool,
    path: String,
    confirmed: bool,
    picker: Option<FilePicker>,
    awaiting: bool,
    job: Option<String>,
    next_poll: Instant,
    result: Option<String>,
    error: Option<String>,
    finished: bool,
}

impl BackupDialog {
    pub fn new(restore: bool) -> Self {
        Self {
            restore,
            path: String::new(),
            confirmed: false,
            picker: None,
            awaiting: false,
            job: None,
            next_poll: Instant::now(),
            result: None,
            error: None,
            finished: false,
        }
    }

    pub fn active(&self) -> bool {
        self.awaiting || self.job.is_some()
    }

    pub fn failure(&mut self, message: String) {
        self.error = Some(message);
        self.awaiting = false;
        self.job = None;
        self.finished = true;
    }

    pub fn started(&mut self, value: Value) -> Result<(), String> {
        #[derive(Deserialize)]
        struct Started {
            id: String,
        }
        let started: Started = serde_json::from_value(value).map_err(|error| error.to_string())?;
        if started.id.is_empty() {
            return Err("后台任务编号为空".into());
        }
        self.awaiting = false;
        self.job = Some(started.id);
        self.next_poll = Instant::now();
        Ok(())
    }

    pub fn poll(&mut self) -> Option<Request> {
        let id = self.job.as_ref()?;
        if Instant::now() < self.next_poll {
            return None;
        }
        self.next_poll = Instant::now() + Duration::from_millis(400);
        Some(Request {
            method: "job.poll".into(),
            params: json!({"job_id":id}),
        })
    }

    pub fn receive(&mut self, value: Value) -> Result<(), String> {
        #[derive(Deserialize)]
        struct Progress {
            id: String,
            kind: String,
            state: String,
            result: Option<Value>,
            error: Option<String>,
        }
        let progress: Progress =
            serde_json::from_value(value).map_err(|error| error.to_string())?;
        if self.job.as_deref() != Some(&progress.id)
            || progress.kind != if self.restore { "restore" } else { "backup" }
        {
            return Err("后台操作身份不匹配".into());
        }
        match progress.state.as_str() {
            "running" => return Ok(()),
            "failed" => self.error = Some(progress.error.ok_or("后台失败信息缺失")?),
            "succeeded" => {
                let value = progress.result.ok_or("后台结果缺失")?;
                self.result = Some(if self.restore {
                    #[derive(Deserialize)]
                    struct Restored {
                        restored: usize,
                        skipped_scripts: Vec<String>,
                        pre_backup: Option<String>,
                    }
                    let result: Restored =
                        serde_json::from_value(value).map_err(|error| error.to_string())?;
                    format!(
                        "已恢复 {} 个文件，本机游戏路径保持不变。\n跳过未配置脚本：{}\n恢复前备份：{}",
                        result.restored,
                        if result.skipped_scripts.is_empty() {
                            "无".into()
                        } else {
                            result.skipped_scripts.join("、")
                        },
                        result
                            .pre_backup
                            .unwrap_or_else(|| "无（目标原先不存在）".into())
                    )
                } else {
                    #[derive(Deserialize)]
                    struct Created {
                        path: String,
                        file_count: usize,
                    }
                    let result: Created =
                        serde_json::from_value(value).map_err(|error| error.to_string())?;
                    format!("已备份 {} 个文件：\n{}", result.file_count, result.path)
                });
            }
            _ => return Err("后台状态无效".into()),
        }
        self.job = None;
        self.finished = true;
        Ok(())
    }

    fn start_request(&mut self) -> Result<Request, String> {
        if self.restore && (self.path.trim().is_empty() || !self.confirmed) {
            return Err("请选择 ZIP 并确认覆盖当前脚本配置".into());
        }
        self.awaiting = true;
        Ok(Request {
            method: if self.restore {
                "restore.start"
            } else {
                "backup.start"
            }
            .into(),
            params: if self.restore {
                json!({"zip_path":self.path.trim(),"confirmed":true})
            } else {
                json!({})
            },
        })
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<BackupAction> {
        if let Some(result) = self.picker.as_ref().and_then(FilePicker::poll) {
            self.picker = None;
            match result {
                Ok(Some(path)) => {
                    self.path = path;
                    self.confirmed = false;
                }
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = busy || self.active() || self.picker.is_some();
        let mut action = None;
        let close = crate::dialogs::Dialog::new(
            "backup-restore",
            if self.restore {
                "恢复配置"
            } else {
                "备份配置"
            },
        )
        .description(if self.restore {
            "从 ZIP 恢复脚本配置"
        } else {
            "将脚本配置打包保存，方便恢复或迁移"
        })
        .show(ctx, !blocked, |ui| {
            crate::dialogs::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!blocked && !self.finished, |ui| {
                    crate::dialogs::form_section(
                        ui,
                        if self.restore {
                            "选择备份"
                        } else {
                            "备份范围"
                        },
                        |ui| {
                            if self.restore {
                                ui.label(
                                    "选择 ZIP，覆盖当前脚本目录中的同名配置；本机游戏路径保留。",
                                );
                                ui.label(
                            "请先停止相关脚本。恢复前会备份现有目标，失败时可能已完成部分文件。",
                        );
                                let (changed, browse) =
                                    crate::dialogs::path_input(ui, &mut self.path);
                                if changed {
                                    self.confirmed = false;
                                }
                                if browse {
                                    self.picker =
                                        Some(FilePicker::start(ctx.clone(), FileKind::Zip));
                                }
                                ui.checkbox(&mut self.confirmed, "确认覆盖当前脚本配置");
                            } else {
                                ui.label("备份已配置脚本的配置文件，ZIP 保存到 config/backups。");
                            }
                        },
                    );
                });
                if let Some(result) = &self.result {
                    ui.label(result);
                    if ui.button("复制结果").clicked() {
                        ui.ctx().copy_text(result.clone());
                    }
                }
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                if self.finished && self.error.is_some() {
                    ui.label("请先核对结果与日志；不会自动重试或回滚。");
                }
                if self.active() {
                    ui.spinner();
                    ui.label("正在处理，请等待完成后关闭窗口。");
                    ctx.request_repaint_after(Duration::from_millis(200));
                }
            });
            crate::dialogs::dialog_footer(ui, |ui| {
                if !self.finished
                    && ui
                        .add_enabled(
                            !blocked,
                            crate::dialogs::primary_button(if self.restore {
                                "开始恢复"
                            } else {
                                "开始备份"
                            }),
                        )
                        .clicked()
                {
                    match self.start_request() {
                        Ok(request) => action = Some(BackupAction::Request(request)),
                        Err(error) => self.error = Some(error),
                    }
                }
                if ui
                    .add_enabled(
                        !blocked,
                        crate::dialogs::secondary_button(if self.finished {
                            "关闭"
                        } else {
                            "取消"
                        }),
                    )
                    .clicked()
                {
                    action = Some(BackupAction::Close);
                }
            });
        });
        if close {
            action = Some(BackupAction::Close);
        }
        action
    }
}

#[cfg(test)]
#[path = "../../tests/rust-gui/backup_dialog.rs"]
mod tests;
