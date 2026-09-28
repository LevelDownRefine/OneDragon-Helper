use crate::main_window::controllers::background::Wallpaper;
use eframe::egui;
use onedragon_rust_gui::backend::Request;
use serde_json::json;
use std::path::Path;

pub enum WallpaperAction {
    Request(Request),
    Close,
}

pub struct WallpaperDialog {
    state: Wallpaper,
    path: String,
    picker: Option<crate::file_picker::FilePicker>,
    error: Option<String>,
    needs_reload: bool,
}

impl WallpaperDialog {
    pub fn new(state: Wallpaper) -> Self {
        Self {
            path: state
                .custom_path
                .as_ref()
                .map(|p| p.display().to_string())
                .unwrap_or_default(),
            state,
            picker: None,
            error: None,
            needs_reload: false,
        }
    }
    pub fn script_name(&self) -> &str {
        &self.state.script_name
    }
    pub fn failure(&mut self, error: String, needs_reload: bool) {
        self.error = Some(error);
        self.needs_reload = needs_reload;
    }
    pub fn show(&mut self, ctx: &egui::Context, busy: bool) -> Option<WallpaperAction> {
        if let Some(result) = self
            .picker
            .as_ref()
            .and_then(crate::file_picker::FilePicker::poll)
        {
            self.picker = None;
            match result {
                Ok(Some(path)) => self.path = path,
                Ok(None) => {}
                Err(error) => self.error = Some(error),
            }
        }
        let blocked = busy || self.picker.is_some();
        let mut action = None;
        let close = crate::dialogs::Dialog::new(
            "wallpaper-dialog",
            &format!("{} · 壁纸", self.state.display_name),
        )
        .description("为当前脚本设置图片或动态背景")
        .show(ctx, !blocked, |ui| {
            crate::dialogs::dialog_body(ui, |ui| {
                crate::dialogs::form_section(ui, "背景文件", |ui| {
                    ui.label(format!("当前来源：{}", self.state.source.display()));
                    ui.label("图片：PNG、JPEG、WebP、BMP；视频：MP4、WebM、MKV、MOV。");
                    ui.label("视频静音循环播放；能否解码取决于 Windows 已安装的编解码器。");
                    ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                        if crate::dialogs::path_input(ui, &mut self.path).1 {
                            self.picker = Some(crate::file_picker::FilePicker::start(
                                ctx.clone(),
                                crate::file_picker::FileKind::Wallpaper,
                            ));
                        }
                    });
                });
            });
            crate::dialogs::dialog_status(ui, self.error.as_deref(), None);
            crate::dialogs::dialog_footer(ui, |ui| {
                if self.needs_reload {
                    if ui
                        .add_enabled(!blocked, crate::dialogs::secondary_button("刷新"))
                        .clicked()
                    {
                        action = Some(WallpaperAction::Request(Request {
                            method: "wallpaper.view".into(),
                            params: json!({"script_name":self.state.script_name}),
                        }));
                    }
                } else {
                    if ui
                        .add_enabled(!blocked, crate::dialogs::primary_button("应用壁纸"))
                        .clicked()
                    {
                        let extension = Path::new(self.path.trim())
                            .extension()
                            .and_then(|value| value.to_str())
                            .unwrap_or_default()
                            .to_ascii_lowercase();
                        if ![
                            "png", "jpg", "jpeg", "webp", "bmp", "mp4", "webm", "mkv", "mov",
                        ]
                        .contains(&extension.as_str())
                        {
                            self.error = Some("请选择支持的图片或视频文件".into());
                        } else {
                            action = Some(self.save(Some(self.path.trim())));
                        }
                    }
                }
                if ui
                    .add_enabled(!blocked, crate::dialogs::secondary_button("取消"))
                    .clicked()
                {
                    action = Some(WallpaperAction::Close);
                }
                if !self.needs_reload
                    && ui
                        .add_enabled(!blocked, crate::dialogs::secondary_button("恢复默认"))
                        .clicked()
                {
                    action = Some(self.save(None));
                }
                if blocked {
                    ui.spinner();
                }
            });
        });
        if close {
            action = Some(WallpaperAction::Close);
        }
        action
    }
    fn save(&self, path: Option<&str>) -> WallpaperAction {
        WallpaperAction::Request(Request {
            method: "wallpaper.set".into(),
            params: json!({"script_name":self.state.script_name,"file_path":path}),
        })
    }
}

#[cfg(test)]
#[path = "../../tests/rust-gui/wallpaper_dialog.rs"]
mod tests;
