use crate::skin;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::{Duration, Instant};

#[derive(Deserialize)]
pub struct Release {
    version: String,
    notes: String,
    size: u64,
}

#[derive(Deserialize)]
struct Previous {
    status: String,
    error: Option<String>,
}

#[derive(Deserialize)]
pub struct UpdateView {
    version: String,
    unavailable_reason: String,
    previous_result: Option<Previous>,
    releases_url: String,
    release: Option<Release>,
    prepared_version: Option<String>,
    handoff_ready: bool,
}

pub enum UpdateAction {
    Request(Request),
    OpenReleases(String),
    Close,
}

pub struct UpdateDialog {
    data: UpdateView,
    awaiting: Option<String>,
    job: Option<(String, String)>,
    progress: Option<(u64, u64)>,
    next_poll: Instant,
    close_pending: bool,
    message: String,
    error: Option<String>,
    needs_reload: bool,
}

impl UpdateDialog {
    pub fn new(data: UpdateView) -> Self {
        Self {
            data,
            awaiting: None,
            job: None,
            progress: None,
            next_poll: Instant::now(),
            close_pending: false,
            message: String::new(),
            error: None,
            needs_reload: false,
        }
    }

    pub fn active(&self) -> bool {
        self.awaiting.is_some() || self.job.is_some()
    }

    pub fn ready(&self) -> bool {
        self.data.handoff_ready
    }

    fn installing(&self) -> bool {
        self.awaiting.as_deref() == Some("update.install")
            || self
                .job
                .as_ref()
                .is_some_and(|(_, kind)| kind == "update.install")
    }

    pub fn failure(&mut self, message: String, reload: bool) {
        self.awaiting = None;
        self.job = None;
        self.close_pending = false;
        self.error = Some(message);
        self.needs_reload = reload;
    }

    fn start(&mut self, method: &str) -> Request {
        assert!(!self.active() && !self.ready());
        self.awaiting = Some(method.into());
        self.progress = None;
        self.error = None;
        if method == "update.check" {
            self.data.release = None;
            self.data.prepared_version = None;
        }
        self.message = match method {
            "update.check" => "正在检查新版本…",
            "update.download" => "正在下载与校验…",
            "update.install" => "正在准备安装；就绪后将关闭窗口…",
            _ => unreachable!("unknown update operation"),
        }
        .into();
        Request {
            method: method.into(),
            params: json!({}),
        }
    }

    pub fn started(&mut self, method: &str, value: Value) -> Result<(), String> {
        #[derive(Deserialize)]
        struct Started {
            id: String,
        }
        let result: Started = serde_json::from_value(value).map_err(|e| e.to_string())?;
        if self.awaiting.as_deref() != Some(method) || result.id.is_empty() {
            return Err("更新任务身份不匹配".into());
        }
        self.awaiting = None;
        self.job = Some((result.id, method.into()));
        self.next_poll = Instant::now();
        Ok(())
    }

    pub fn poll(&mut self) -> Option<Request> {
        let (id, _) = self.job.as_ref()?;
        if Instant::now() < self.next_poll {
            return None;
        }
        self.next_poll = Instant::now() + Duration::from_millis(400);
        Some(Request {
            method: "job.poll".into(),
            params: json!({"job_id":id}),
        })
    }

    pub fn receive(&mut self, value: Value) -> Result<bool, String> {
        #[derive(Deserialize)]
        struct Progress {
            received: u64,
            total: u64,
        }
        #[derive(Deserialize)]
        struct State {
            id: String,
            kind: String,
            state: String,
            progress: Option<Progress>,
            result: Option<Value>,
            error: Option<String>,
        }
        let response: State = serde_json::from_value(value).map_err(|e| e.to_string())?;
        if self.job.as_ref() != Some(&(response.id.clone(), response.kind.clone())) {
            return Err("更新任务身份不匹配".into());
        }
        if let Some(progress) = response.progress {
            self.progress = Some((progress.received, progress.total));
        }
        match response.state.as_str() {
            "running" => return Ok(false),
            "cancelled" if response.kind == "update.install" => {
                return Err("安装交接不能取消".into());
            }
            "cancelled" => {
                self.message = "已取消".into();
            }
            "failed" => self.error = Some(response.error.ok_or("更新错误缺失")?),
            "succeeded" => {
                let result = response.result.ok_or("更新结果缺失")?;
                if response.kind == "update.check" {
                    #[derive(Deserialize)]
                    struct Checked {
                        release: Option<Release>,
                    }
                    let checked: Checked =
                        serde_json::from_value(result).map_err(|e| e.to_string())?;
                    self.data.release = checked.release;
                    self.data.prepared_version = None;
                    self.message = if self.data.release.is_some() {
                        "发现新版本"
                    } else {
                        "当前已是最新版本"
                    }
                    .into();
                } else if response.kind == "update.download" {
                    #[derive(Deserialize)]
                    struct Prepared {
                        version: String,
                    }
                    let prepared: Prepared =
                        serde_json::from_value(result).map_err(|e| e.to_string())?;
                    if self
                        .data
                        .release
                        .as_ref()
                        .map(|release| release.version.as_str())
                        != Some(prepared.version.as_str())
                    {
                        return Err("下载版本与检查结果不一致".into());
                    }
                    self.data.prepared_version = Some(prepared.version);
                    self.message = "下载与校验完成".into();
                } else if response.kind == "update.install" {
                    #[derive(Deserialize)]
                    struct Handoff {
                        version: String,
                        ready: bool,
                    }
                    let handoff: Handoff =
                        serde_json::from_value(result).map_err(|e| e.to_string())?;
                    if !handoff.ready
                        || self.data.prepared_version.as_deref() != Some(&handoff.version)
                    {
                        return Err("安装交接尚未确认".into());
                    }
                    self.data.handoff_ready = true;
                    self.message = "安装器已就绪，正在关闭助手…".into();
                } else {
                    return Err("更新操作无效".into());
                }
            }
            _ => return Err("更新状态无效".into()),
        }
        self.job = None;
        Ok(self.close_pending || response.state == "cancelled")
    }

    fn close(&mut self) -> Option<UpdateAction> {
        if self.installing() || self.ready() {
            return None;
        }
        if let Some((id, _)) = &self.job {
            if self.close_pending {
                return None;
            }
            self.close_pending = true;
            self.message = "正在取消，请等待当前网络请求结束…".into();
            Some(UpdateAction::Request(Request {
                method: "job.cancel".into(),
                params: json!({"job_id":id}),
            }))
        } else if !self.active() {
            Some(UpdateAction::Close)
        } else {
            None
        }
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<UpdateAction> {
        let mut action = None;
        let close = skin::Dialog::new("update-dialog", "助手更新")
            .description("检查新版本，查看下载与安装进度")
            .show(
                ctx,
                !busy && !self.close_pending && !self.installing() && !self.ready(),
                |ui| {
                    skin::dialog_body(ui, |ui| {
                        skin::form_section(ui, "版本信息", |ui| {
                            ui.label(format!("当前版本：{}", self.data.version));
                            if let Some(previous) = &self.data.previous_result {
                                let message = match previous.status.as_str() {
                                    "installed" => "上次更新已安装完成。",
                                    "recovered" => "上次更新已恢复到旧版本。",
                                    "failed" => "上次更新未完成。",
                                    "restart_failed" => "上次更新已安装，请手动重新打开助手。",
                                    _ => "上次更新状态未知。",
                                };
                                ui.label(message);
                                if let Some(error) = &previous.error {
                                    ui.label(error);
                                }
                            }
                            if !self.data.unavailable_reason.is_empty() {
                                ui.label(&self.data.unavailable_reason);
                            }
                        });
                        if let Some(release) = &self.data.release {
                            skin::form_section(ui, "可用更新", |ui| {
                                ui.label(format!(
                                    "新版本：{} · {:.1} MiB",
                                    release.version,
                                    release.size as f64 / 1048576.0
                                ));
                                ui.label(if release.notes.is_empty() {
                                    "此版本未提供更新说明。"
                                } else {
                                    &release.notes
                                });
                            });
                        }
                        if let Some((received, total)) = self.progress {
                            let fraction = if total > 0 {
                                (received as f32 / total as f32).clamp(0.0, 1.0)
                            } else {
                                0.0
                            };
                            ui.add(egui::ProgressBar::new(fraction).text(format!(
                                "{:.1} / {:.1} MiB",
                                received as f64 / 1048576.0,
                                total as f64 / 1048576.0
                            )));
                        }
                        if self.active() {
                            ui.spinner();
                            ctx.request_repaint_after(Duration::from_millis(200));
                        }
                        if !self.message.is_empty() {
                            ui.label(&self.message);
                        }
                        if let Some(error) = &self.error {
                            ui.colored_label(egui::Color32::LIGHT_RED, error);
                        }
                        if self.needs_reload {
                            ui.label("状态未确认，请重新读取；不会自动重试操作。");
                        }
                        if self.data.prepared_version.is_some() && !self.active() && !self.ready() {
                            ui.label(
                                "安装将关闭助手并重启。请先结束正在运行的任务和其他助手窗口。",
                            );
                        }
                    });
                    skin::dialog_footer(ui, |ui| {
                        if !self.active() && self.needs_reload {
                            if ui
                                .add_enabled(!busy, skin::secondary_button("重新读取"))
                                .clicked()
                            {
                                action = Some(UpdateAction::Request(Request {
                                    method: "update.view".into(),
                                    params: json!({}),
                                }));
                            }
                        } else if !self.active() && !self.data.unavailable_reason.is_empty() {
                            ui.add_enabled(false, skin::secondary_button("检查更新"));
                        } else if !self.active() && !self.ready() {
                            let (label, method) = if self.data.prepared_version.is_some() {
                                ("安装并重启", "update.install")
                            } else if self.data.release.is_some() {
                                ("下载更新", "update.download")
                            } else {
                                ("检查更新", "update.check")
                            };
                            if ui.add_enabled(!busy, skin::primary_button(label)).clicked() {
                                action = Some(UpdateAction::Request(self.start(method)));
                            }
                            if self.data.release.is_some()
                                && ui
                                    .add_enabled(!busy, skin::secondary_button("检查更新"))
                                    .clicked()
                            {
                                action = Some(UpdateAction::Request(self.start("update.check")));
                            }
                        }
                        if ui
                            .add_enabled(
                                !busy && !self.close_pending && !self.installing() && !self.ready(),
                                skin::secondary_button(if self.active() {
                                    "取消更新"
                                } else {
                                    "关闭"
                                }),
                            )
                            .clicked()
                        {
                            action = self.close();
                        }
                        if ui
                            .add_enabled(
                                !busy && !self.active(),
                                skin::secondary_button("发布页面"),
                            )
                            .clicked()
                        {
                            action =
                                Some(UpdateAction::OpenReleases(self.data.releases_url.clone()));
                        }
                    });
                },
            );
        if close {
            action = self.close();
        }
        action
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dialog() -> UpdateDialog {
        UpdateDialog::new(
            serde_json::from_value(json!({
                "version":"1.0.0","unavailable_reason":"","previous_result":null,
                "releases_url":"https://github.com/LevelDownRefine/OneDragon-Helper/releases",
                "release":{"version":"2.0.0","notes":"notes","size":100},
                "prepared_version":null,"handoff_ready":false
            }))
            .unwrap(),
        )
    }

    #[test]
    fn cancellation_waits_for_terminal_state_and_rejects_stale_job() {
        let mut dialog = dialog();
        assert_eq!(dialog.start("update.download").method, "update.download");
        assert!(dialog.active());
        assert!(dialog.close().is_none());
        dialog
            .started("update.download", json!({"id":"job"}))
            .unwrap();
        assert!(
            dialog
                .receive(json!({"id":"old","kind":"update.download","state":"running"}))
                .is_err()
        );
        assert!(!dialog.receive(json!({"id":"job","kind":"update.download","state":"running","progress":{"received":7,"total":10}})).unwrap());
        assert_eq!(dialog.progress, Some((7, 10)));
        let Some(UpdateAction::Request(cancel)) = dialog.close() else {
            panic!("expected cancel");
        };
        assert_eq!(cancel.method, "job.cancel");
        assert_eq!(cancel.params, json!({"job_id":"job"}));
        assert!(dialog.close().is_none());
        assert!(dialog.active());
        assert!(
            dialog
                .receive(json!({"id":"job","kind":"update.download","state":"cancelled"}))
                .unwrap()
        );
        assert!(!dialog.active());
        assert!(dialog.poll().is_none());
    }

    #[test]
    fn download_failure_keeps_release_without_automatic_retry() {
        let mut dialog = dialog();
        dialog.start("update.download");
        dialog
            .started("update.download", json!({"id":"job"}))
            .unwrap();
        assert!(
            !dialog
                .receive(
                    json!({"id":"job","kind":"update.download","state":"failed","error":"网络中断"})
                )
                .unwrap()
        );
        assert_eq!(dialog.error.as_deref(), Some("网络中断"));
        assert!(dialog.data.release.is_some());
        assert!(!dialog.active());
        assert!(dialog.poll().is_none());
        dialog.failure("连接中断".into(), true);
        assert!(dialog.needs_reload);
        assert!(matches!(dialog.close(), Some(UpdateAction::Close)));
    }

    #[test]
    fn install_waits_for_matching_ready_and_cannot_be_cancelled() {
        let mut dialog = dialog();
        dialog.data.prepared_version = Some("2.0.0".into());
        let request = dialog.start("update.install");
        assert_eq!(request.params, json!({}));
        assert!(dialog.close().is_none());
        dialog
            .started("update.install", json!({"id":"install"}))
            .unwrap();
        assert!(dialog.close().is_none());
        assert!(!dialog.ready());
        for result in [
            json!({"ready":false,"version":"2.0.0"}),
            json!({"ready":true,"version":"other"}),
        ] {
            assert!(dialog.receive(json!({"id":"install","kind":"update.install","state":"succeeded","result":result})).is_err());
            assert!(!dialog.ready());
        }
        assert!(!dialog.receive(json!({"id":"install","kind":"update.install","state":"succeeded","result":{"ready":true,"version":"2.0.0"}})).unwrap());
        assert!(dialog.ready());
        assert!(!dialog.active());
        assert!(dialog.poll().is_none());
        assert!(dialog.close().is_none());
    }

    #[test]
    fn failed_install_keeps_prepared_version_and_does_not_exit_or_retry() {
        let mut dialog = dialog();
        dialog.data.prepared_version = Some("2.0.0".into());
        dialog.start("update.install");
        dialog
            .started("update.install", json!({"id":"install"}))
            .unwrap();
        assert!(!dialog.receive(json!({"id":"install","kind":"update.install","state":"failed","error":"仍有任务"})).unwrap());
        assert!(!dialog.ready());
        assert!(!dialog.active());
        assert_eq!(dialog.data.prepared_version.as_deref(), Some("2.0.0"));
        assert!(dialog.poll().is_none());
        assert_eq!(dialog.start("update.install").method, "update.install");
        dialog.failure("连接中断".into(), true);
        assert!(!dialog.ready());
        assert!(dialog.needs_reload);
    }

    #[test]
    fn escape_closes_idle_dialog_without_check_or_download() {
        let ctx = egui::Context::default();
        let mut dialog = dialog();
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(dialog.show(ui.ctx(), false).is_none());
            });
            output.textures_delta.clear();
        }
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
                assert!(matches!(
                    dialog.show(ui.ctx(), false),
                    Some(UpdateAction::Close)
                ));
            },
        );
        output.textures_delta.clear();
        assert!(!dialog.active());
    }
}
