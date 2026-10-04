use super::super::*;
use super::*;

impl App {
    pub(in crate::main_window) fn receive_update(
        &mut self,
        method: &str,
        result: Result<Value, Failure>,
    ) {
        let handled = result.and_then(|value| {
            if method == "update.view" {
                let view: UpdateView =
                    serde_json::from_value(value).map_err(|e| Failure::transport(e.to_string()))?;
                self.update_dialog = Some(UpdateDialog::new(view));
                return Ok(false);
            }
            let dialog = self
                .update_dialog
                .as_mut()
                .ok_or_else(|| Failure::transport("更新窗口已不存在"))?;
            match method {
                "update.check" | "update.download" | "update.install" => {
                    dialog.started(method, value).map(|()| false)
                }
                "job.poll" => dialog.receive(value),
                "job.cancel" if value.is_boolean() => Ok(false),
                _ => Err("更新响应无效".into()),
            }
            .map_err(Failure::transport)
        });
        match handled {
            Ok(close) => {
                if close {
                    self.update_dialog = None;
                }
                self.status = if self
                    .update_dialog
                    .as_ref()
                    .is_some_and(UpdateDialog::active)
                {
                    "处理中"
                } else {
                    "已同步"
                }
                .into();
            }
            Err(failure) => {
                self.ui.toast(&failure.message);
                if let Some(dialog) = &mut self.update_dialog {
                    dialog.failure(
                        failure.message,
                        failure.refresh_required || failure.code == "transport_failed",
                    );
                }
                if failure.code == "transport_failed" {
                    self.backend = None;
                }
                self.status = "更新操作失败".into();
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_update(&mut self, ui: &mut Ui) {
        let request_pending = self.request_pending;
        let local_operation_active = self.local_operation_active();
        if let Some(action) = self
            .update_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx(), request_pending, local_operation_active))
        {
            match action {
                UpdateAction::Close => {
                    self.update_dialog = None;
                }
                UpdateAction::OpenReleases(value) => {
                    let ctx = self.ctx.clone();
                    self.open_job = Some(OpenJob::start(Target::Url { value }, move || {
                        ctx.request_repaint()
                    }));
                }
                UpdateAction::Request(request) => {
                    if self.backend.is_none() {
                        self.update_dialog = None;
                        self.open_update_after_snapshot = true;
                        self.connect();
                    } else {
                        self.request(&request.method, request.params);
                    }
                }
            }
        }
    }
}
