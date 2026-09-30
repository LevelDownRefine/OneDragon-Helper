use super::super::*;
use super::*;

impl App {
    pub(in crate::main_window) fn show_config(&mut self, ui: &mut Ui) {
        if let Some(action) = self
            .settings_dialog
            .as_mut()
            .filter(|_| self.backup_dialog.is_none() && self.update_dialog.is_none())
            .and_then(|dialog| dialog.show(ui.ctx(), self.busy))
        {
            match action {
                SettingsAction::Backup(restore) => {
                    self.backup_dialog = Some(BackupDialog::new(restore))
                }
                SettingsAction::Close => {
                    self.settings_dialog = None;
                    self.refresh_settings_run = false;
                    if self.view.is_none() && self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                }
                SettingsAction::Request(request) => {
                    self.error = None;
                    self.refresh_settings_run = false;
                    if self.backend.is_none() && request.method == "update.view" {
                        self.open_update_after_snapshot = true;
                        self.connect();
                    } else if self.backend.is_none()
                        && matches!(request.method.as_str(), "settings.view" | "plan.view")
                    {
                        self.open_settings_after_snapshot = true;
                        self.connect();
                    } else {
                        self.request(&request.method, request.params);
                    }
                }
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_backup(&mut self, ui: &mut Ui) {
        if let Some(action) = self
            .backup_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx(), self.busy))
        {
            match action {
                BackupAction::Request(request) => {
                    self.request(&request.method, request.params);
                }
                BackupAction::Close => {
                    self.backup_dialog = None;
                    self.error = None;
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    } else {
                        self.connect();
                    }
                }
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn receive_backup(&mut self, method: &str, result: Value) {
        let handled = if let Some(dialog) = &mut self.backup_dialog {
            if method == "job.poll" {
                dialog.receive(result)
            } else {
                dialog.started(result)
            }
        } else {
            Err("后台操作窗口已关闭".into())
        };
        match handled {
            Ok(()) => {
                self.status = if self
                    .backup_dialog
                    .as_ref()
                    .is_some_and(BackupDialog::active)
                {
                    "处理中"
                } else {
                    "操作结束"
                }
                .into()
            }
            Err(error) => self.fail(Failure::transport(error)),
        }
    }
}

impl App {
    pub(in crate::main_window) fn receive_config(&mut self, method: &str, result: Value) {
        if matches!(method, "settings.view" | "startup.view") {
            match serde_json::from_value::<SettingsView>(result) {
                Ok(data) => {
                    if method == "startup.view" {
                        self.startup_dialog = StartupDialog::from_settings(&data);
                    } else if std::mem::take(&mut self.refresh_settings_run)
                        && self.settings_dialog.is_some()
                    {
                        self.settings_dialog.as_mut().unwrap().refresh_run(data);
                    } else {
                        self.settings_dialog = Some(SettingsDialog::new(data));
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && self.settings.capture_restore {
                            self.backup_dialog = Some(BackupDialog::new(true));
                        }
                        #[cfg(feature = "capture")]
                        if self.settings.capture.is_some() && self.settings.capture_plan {
                            self.request("plan.view", json!({}));
                        }
                    }
                    self.write_confirmed = false;
                    self.status = "已同步".into();
                }
                Err(error) => self.fail(Failure::transport(format!("全局设置数据无效：{error}"))),
            }
        } else if method == "settings.run_save" && result.is_null() {
            self.write_confirmed = true;
            self.refresh_settings_run = true;
            self.request("settings.view", json!({}));
        } else if method == "settings.startup_save" && result.is_null() {
            self.settings_dialog = None;
            self.ui.toast("启动设置已保存，下次打开生效");
            self.status = "已同步".into();
        } else {
            self.fail(Failure::transport("写操作响应无效"));
        }
    }
}
