use crate::skin;
use eframe::egui;
use onedragon_rust_gui::backend::{Failure, Request};
use serde_json::{Value, json};
use std::{collections::VecDeque, path::PathBuf};

pub struct DropDialog {
    pending: VecDeque<String>,
    current: Option<String>,
    results: Vec<(String, String)>,
    added: usize,
    duplicate: usize,
    failed: usize,
    stopped: usize,
}

impl DropDialog {
    pub fn new(paths: Vec<PathBuf>) -> Result<Self, String> {
        if paths.is_empty() || paths.len() > 128 {
            return Err("请一次拖入 1 到 128 个脚本文件".into());
        }
        // Match the original GUI: reject a mixed/invalid drop before any write.
        let mut pending = VecDeque::new();
        for path in paths {
            let valid = path.extension().and_then(|s| s.to_str()).is_some_and(|s| {
                ["exe", "bat", "py", "lnk"].contains(&s.to_ascii_lowercase().as_str())
            });
            if !valid || !path.is_file() {
                return Err("请拖入 .exe、.bat、.py 文件或有效快捷方式".into());
            }
            pending.push_back(
                path.into_os_string()
                    .into_string()
                    .map_err(|_| "文件路径无法用 UTF-8 表示，请先重命名文件".to_string())?,
            );
        }
        Ok(Self {
            pending,
            current: None,
            results: Vec::new(),
            added: 0,
            duplicate: 0,
            failed: 0,
            stopped: 0,
        })
    }

    pub fn active(&self) -> bool {
        self.current.is_some() || !self.pending.is_empty()
    }

    pub fn awaiting(&self) -> bool {
        self.current.is_some()
    }

    pub fn next(&mut self) -> Option<Request> {
        if self.current.is_some() {
            return None;
        }
        let path = self.pending.pop_front()?;
        let request = Request {
            method: "script.add".into(),
            params: json!({"file_path":path}),
        };
        self.current = Some(path);
        Some(request)
    }

    pub fn receive(&mut self, result: Result<Value, Failure>) -> bool {
        let path = self.current.take().expect("one pending add per drop");
        #[derive(serde::Deserialize)]
        struct Added {
            script_name: String,
        }
        let result = result.and_then(|value| {
            serde_json::from_value::<Added>(value)
                .ok()
                .filter(|added| !added.script_name.is_empty())
                .map(|added| added.script_name)
                .ok_or_else(|| Failure::transport("添加响应无效，需刷新核对"))
        });
        let mut disconnected = false;
        let message = match result {
            Ok(name) => {
                self.added += 1;
                format!("已添加：{name}")
            }
            Err(failure) => {
                disconnected = failure.code == "transport_failed";
                if failure.code == "duplicate_script" {
                    self.duplicate += 1;
                } else {
                    self.failed += 1;
                }
                if failure.refresh_required || disconnected {
                    for path in self.pending.drain(..) {
                        self.stopped += 1;
                        self.results.push((path, "未尝试；请先刷新核对列表".into()));
                    }
                    format!("{}；此项可能已写入，请刷新核对", failure.message)
                } else {
                    failure.message
                }
            }
        };
        self.results.push((path, message));
        disconnected
    }

    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> bool {
        let blocked = self.active() || busy;
        let mut close = false;
        let response = egui::Modal::new(egui::Id::new("file-drop-result"))
            .frame(
                egui::Frame::new()
                    .fill(skin::PANEL)
                    .inner_margin(20)
                    .corner_radius(16),
            )
            .show(ctx, |ui| {
                ui.set_width(500.0);
                ui.heading(if self.active() {
                    "正在添加脚本"
                } else {
                    "文件导入结果"
                });
                ui.label(format!(
                    "已添加 {}，重复 {}，失败 {}，未尝试 {}",
                    self.added, self.duplicate, self.failed, self.stopped
                ));
                if let Some(path) = &self.current {
                    ui.horizontal(|ui| {
                        ui.spinner();
                        ui.label(path);
                    });
                }
                egui::ScrollArea::vertical()
                    .max_height(280.0)
                    .show(ui, |ui| {
                        for (path, message) in &self.results {
                            ui.label(path);
                            ui.label(message);
                            ui.separator();
                        }
                    });
                if self.active() {
                    ui.label("只添加启动信息。请等待完成后关闭窗口。");
                }
                if ui
                    .add_enabled(!blocked, egui::Button::new("完成"))
                    .clicked()
                {
                    close = true;
                }
            });
        close || (!blocked && response.should_close())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths(root: &std::path::Path) -> Vec<PathBuf> {
        ["一.EXE", "two.bat", "three.py"]
            .map(|name| {
                let path = root.join(name);
                std::fs::write(&path, "never execute").unwrap();
                path
            })
            .into()
    }

    #[test]
    fn escape_waits_for_import_then_closes_results() {
        let root = tempfile::tempdir().unwrap();
        let mut dialog = DropDialog::new(paths(root.path())).unwrap();
        let ctx = egui::Context::default();
        for finished in [false, true] {
            if finished {
                while dialog.next().is_some() {
                    dialog.receive(Ok(json!({"script_name":"saved"})));
                }
            }
            for _ in 0..2 {
                let mut output = ctx.run_ui(Default::default(), |ui| {
                    assert!(!dialog.show(ui.ctx(), false));
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
                    assert_eq!(dialog.show(ui.ctx(), false), finished);
                },
            );
            output.textures_delta.clear();
        }
    }

    #[test]
    fn rejects_mixed_drop_before_start_and_preserves_files() {
        let root = tempfile::tempdir().unwrap();
        let mut paths = paths(root.path());
        paths.push(root.path().join("missing.exe"));
        assert!(DropDialog::new(paths.clone()).is_err());
        paths.pop();
        paths.push(root.path().to_path_buf());
        assert!(DropDialog::new(paths).is_err());
        assert_eq!(
            std::fs::read_to_string(root.path().join("一.EXE")).unwrap(),
            "never execute"
        );
    }

    #[test]
    fn serial_import_counts_duplicates_and_stops_unknown_writes() {
        let root = tempfile::tempdir().unwrap();
        let mut dialog = DropDialog::new(paths(root.path())).unwrap();
        assert_eq!(dialog.next().unwrap().method, "script.add");
        assert!(dialog.next().is_none());
        assert!(!dialog.receive(Ok(json!({"script_name":"first"}))));
        dialog.next().unwrap();
        dialog.receive(Err(Failure {
            code: "duplicate_script".into(),
            message: "exists".into(),
            refresh_required: false,
        }));
        dialog.next().unwrap();
        dialog.receive(Ok(json!({"script_name":"third"})));
        assert!(!dialog.active());
        assert_eq!((dialog.added, dialog.duplicate, dialog.failed), (2, 1, 0));
        for failure in [
            Failure::transport("lost"),
            Failure {
                code: "operation_failed".into(),
                message: "init failed".into(),
                refresh_required: true,
            },
        ] {
            let mut dialog = DropDialog::new(paths(root.path())).unwrap();
            dialog.next().unwrap();
            dialog.receive(Err(failure));
            assert!(!dialog.active());
            assert!(dialog.next().is_none(), "must not replay unknown writes");
            assert_eq!((dialog.failed, dialog.stopped), (1, 2));
        }
    }
}
