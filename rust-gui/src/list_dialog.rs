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
        let modal = egui::Modal::new(egui::Id::new("script-list-dialog"))
            .frame(
                egui::Frame::new()
                    .fill(skin::PANEL)
                    .stroke(egui::Stroke::new(1.0, skin::BORDER))
                    .corner_radius(16)
                    .inner_margin(20),
            )
            .show(ctx, |ui| {
                ui.set_width(480.0);
                ui.heading(if self.remove.is_some() {
                    "删除脚本"
                } else {
                    "添加脚本"
                });
                ui.add_space(12.0);
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                    if let Some((_, display)) = &self.remove {
                        ui.label(format!("确定从助手列表删除「{display}」？"));
                        ui.label("将移除该条目和每周设置，脚本文件仍保留。");
                    } else {
                        ui.label("选择 .exe、.bat、.py 或指向这些文件的快捷方式。");
                        ui.horizontal(|ui| {
                            ui.add(egui::TextEdit::singleline(&mut self.path).desired_width(360.0));
                            if ui.button("浏览…").clicked() {
                                self.picker = Some(FilePicker::start(
                                    ctx.clone(),
                                    crate::file_picker::FileKind::ScriptOrShortcut,
                                ));
                            }
                        });
                    }
                });
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                if self.needs_reload {
                    ui.label("列表可能已改变，请刷新核对后再操作。");
                }
                ui.add_space(12.0);
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(!blocked, egui::Button::new("取消"))
                        .clicked()
                    {
                        action = Some(ListAction::Cancel);
                    }
                    if self.needs_reload
                        && ui
                            .add_enabled(!blocked, egui::Button::new("刷新列表"))
                            .clicked()
                    {
                        action = Some(ListAction::Refresh);
                    }
                    if ui
                        .add_enabled(
                            !blocked && !self.needs_reload,
                            egui::Button::new(if self.remove.is_some() {
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
                    if blocked {
                        ui.spinner();
                    }
                });
            });
        if !blocked && modal.should_close() {
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
