use crate::dialogs::file_picker::FilePicker;
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

    pub fn show(&mut self, ctx: &egui::Context, blocked: bool) -> Option<ListAction> {
        if let Some(result) = self.picker.as_ref().and_then(FilePicker::poll) {
            self.picker = None;
            match result {
                Ok(Some(path)) => self.path = path,
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = blocked || self.picker.is_some();
        let mut action = None;
        let close = crate::dialogs::common::Dialog::new(
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
            crate::dialogs::common::dialog_body(ui, |ui| {
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                    crate::dialogs::common::form_section(
                        ui,
                        if self.remove.is_some() {
                            "确认移除"
                        } else {
                            "脚本文件"
                        },
                        |ui| {
                            if let Some((name, display)) = &self.remove {
                                ui.label(egui::RichText::new(display).size(20.0).strong());
                                if name != display {
                                    ui.label(egui::RichText::new(name).color(crate::theme::MUTED));
                                }
                                ui.add_space(8.0);
                                ui.colored_label(
                                    crate::theme::DANGER,
                                    "将删除助手中的脚本条目及每周设置。",
                                );
                                ui.label("脚本文件保留在原位置，可以重新添加。");
                            } else {
                                ui.label("选择 .exe、.bat、.py 或指向这些文件的快捷方式。");
                                if crate::dialogs::common::path_input(ui, &mut self.path).1 {
                                    self.picker = Some(FilePicker::start(
                                        ctx.clone(),
                                        crate::dialogs::file_picker::FileKind::ScriptOrShortcut,
                                    ));
                                }
                            }
                        },
                    );
                });
            });
            crate::dialogs::common::dialog_status(
                ui,
                self.error.as_deref(),
                self.needs_reload
                    .then_some("列表可能已改变，请刷新核对后再操作。"),
            );
            crate::dialogs::common::dialog_footer(ui, |ui| {
                if ui
                    .add_enabled(
                        !blocked && !self.needs_reload,
                        if self.remove.is_some() {
                            crate::dialogs::common::danger_button("确认删除脚本")
                        } else {
                            crate::dialogs::common::primary_button("添加")
                        },
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
                    .add_enabled(!blocked, crate::dialogs::common::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(ListAction::Cancel);
                }
                if self.needs_reload
                    && ui
                        .add_enabled(
                            !blocked,
                            crate::dialogs::common::secondary_button("刷新列表"),
                        )
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
#[path = "../../tests/dialogs/list_dialog.rs"]
mod tests;
