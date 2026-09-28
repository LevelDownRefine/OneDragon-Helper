use crate::{file_picker::FilePicker, skin};
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde_json::json;

pub enum ListAction {
    Request(Request),
    Cancel,
    Refresh,
}

pub struct ListDialog {
    remove: Option<(String, String)>,
    path: String,
    picker: Option<FilePicker>,
    error: Option<String>,
    needs_reload: bool,
}

impl ListDialog {
    pub fn add() -> Self {
        Self {
            remove: None,
            path: String::new(),
            picker: None,
            error: None,
            needs_reload: false,
        }
    }

    pub fn remove(name: String, display: String) -> Self {
        Self {
            remove: Some((name, display)),
            ..Self::add()
        }
    }

    pub fn failure(&mut self, message: String, needs_reload: bool) {
        self.error = Some(message);
        self.needs_reload = needs_reload;
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<ListAction> {
        if let Some(result) = self.picker.as_ref().and_then(FilePicker::poll) {
            self.picker = None;
            match result {
                Ok(Some(path)) => self.path = path,
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = busy || self.picker.is_some();
        let mut action = None;
        let close = skin::Dialog::new(
            "script-list-dialog",
            if self.remove.is_some() {
                "删除脚本"
            } else {
                "添加脚本"
            },
        )
        .description(if self.remove.is_some() {
            "从助手列表移除脚本"
        } else {
            "将脚本添加到助手，统一管理运行"
        })
        .show(ctx, !blocked, |ui| {
            skin::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                    skin::form_section(
                        ui,
                        if self.remove.is_some() {
                            "确认移除"
                        } else {
                            "脚本文件"
                        },
                        |ui| {
                            if let Some((_, display)) = &self.remove {
                                ui.label(format!("确定从助手列表删除「{display}」？"));
                                ui.label("将移除该条目和每周设置，脚本文件仍保留。");
                            } else {
                                ui.label("选择 .exe、.bat、.py 或指向这些文件的快捷方式。");
                                if skin::path_input(ui, &mut self.path).1 {
                                    self.picker = Some(FilePicker::start(
                                        ctx.clone(),
                                        crate::file_picker::FileKind::ScriptOrShortcut,
                                    ));
                                }
                            }
                        },
                    );
                });
            });
            skin::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("列表可能已改变，请刷新核对后再操作。"),
            );
            skin::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !blocked && !self.needs_reload,
                        skin::primary_button(if self.remove.is_some() {
                            "确认删除"
                        } else {
                            "添加"
                        }),
                    )
                    .clicked()
                {
                    if let Some((name, _)) = &self.remove {
                        action = Some(ListAction::Request(Request {
                            method: "script.remove".into(),
                            params: json!({"script_name":name}),
                        }));
                    } else if self.path.trim().is_empty() {
                        self.error = Some("请选择脚本文件".into());
                    } else {
                        action = Some(ListAction::Request(Request {
                            method: "script.add".into(),
                            params: json!({"file_path":self.path.trim()}),
                        }));
                    }
                }
                if ui
                    .add_enabled(!blocked, skin::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(ListAction::Cancel);
                }
                if self.needs_reload
                    && ui
                        .add_enabled(!blocked, skin::secondary_button("刷新列表"))
                        .clicked()
                {
                    action = Some(ListAction::Refresh);
                }
                if blocked {
                    ui.spinner();
                }
            });
        });
        if close {
            action = Some(ListAction::Cancel);
        }
        action
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escape_cancels_add_and_delete_without_a_request() {
        for mut dialog in [
            ListDialog::add(),
            ListDialog::remove("script".into(), "示例".into()),
        ] {
            let ctx = egui::Context::default();
            for _ in 0..2 {
                let mut output = ctx.run_ui(Default::default(), |ui| {
                    assert!(dialog.show(ui.ctx(), false).is_none());
                });
                output.textures_delta.clear();
            }
            let mut cancelled = false;
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
                    cancelled = matches!(dialog.show(ui.ctx(), false), Some(ListAction::Cancel));
                },
            );
            output.textures_delta.clear();
            assert!(cancelled);
        }
    }
}
