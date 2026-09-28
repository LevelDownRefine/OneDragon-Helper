//! Open resolved resources with their system association, without a command shell.
use super::*;
use serde::Deserialize;
use std::sync::mpsc::{self, Receiver, TryRecvError};

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Target {
    Url { value: String },
    Path { value: String },
    Unavailable { reason: String },
}

impl Target {
    fn value(&self) -> Result<&str, String> {
        let value = match self {
            Self::Url { value }
                if value.starts_with("https://") || value.starts_with("http://") =>
            {
                value
            }
            Self::Path { value } if std::path::Path::new(value).is_absolute() => value,
            Self::Unavailable { reason } => return Err(reason.clone()),
            _ => return Err("资源目标无效".into()),
        };
        if value.contains('\0') {
            return Err("资源目标含无效字符".into());
        }
        Ok(value)
    }
}

pub struct OpenJob(Receiver<Result<(), String>>);

impl OpenJob {
    pub fn start(target: Target, repaint: impl FnOnce() + Send + 'static) -> Self {
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let result = target.value().and_then(open);
            let _ = sender.send(result);
            repaint();
        });
        Self(receiver)
    }

    pub fn poll(&self) -> Option<Result<(), String>> {
        match self.0.try_recv() {
            Ok(result) => Some(result),
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => Some(Err("打开资源的任务意外退出".into())),
        }
    }
}

#[cfg(windows)]
pub(crate) fn open(value: &str) -> Result<(), String> {
    use windows_sys::Win32::{
        System::Com::{
            COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE, CoInitializeEx, CoUninitialize,
        },
        UI::Shell::ShellExecuteW,
    };
    let path: Vec<u16> = value.encode_utf16().chain(Some(0)).collect();
    let verb: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
    // This worker owns its COM apartment; the strings remain alive for the call.
    unsafe {
        let initialized = CoInitializeEx(
            std::ptr::null(),
            (COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) as u32,
        );
        if initialized < 0 {
            return Err(format!("无法初始化系统文件关联：{initialized:#x}"));
        }
        let result = ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            path.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        ) as isize;
        CoUninitialize();
        if result <= 32 {
            return Err(format!(
                "无法打开资源（系统错误 {result}），请检查文件与默认关联程序"
            ));
        }
    }
    Ok(())
}

#[cfg(not(windows))]
pub(crate) fn open(value: &str) -> Result<(), String> {
    let executable = if cfg!(target_os = "macos") {
        "open"
    } else {
        "xdg-open"
    };
    let status = std::process::Command::new(executable)
        .arg(value)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|error| format!("无法打开资源：{error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("系统关联程序退出：{status}"))
    }
}

impl View {
    pub(in crate::main_window) fn refresh_icons(
        &mut self,
        default_path: Option<std::path::PathBuf>,
    ) {
        self.default_icon_path = default_path;
        self.icons.invalidate();
        self.game_icon = None;
        self.game_hover = None;
    }

    pub(in crate::main_window) fn set_game_icon(
        &mut self,
        name: String,
        path: Option<std::path::PathBuf>,
    ) {
        self.game_icon = Some((name, path));
    }

    pub(super) fn game_button(
        &mut self,
        ui: &mut Ui,
        bounds: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) -> bool {
        let response = ui.interact(bounds, Id::new(("icon", "启动游戏")), Sense::click());
        self.assets.icon(
            ui,
            "game",
            Rect::from_center_size(bounds.center(), vec2(26.0, 26.0)),
        );
        let hovered = response.hovered();
        #[cfg(feature = "capture")]
        let hovered = hovered || self.capture_game_icon;
        if hovered {
            ui.painter().rect_filled(bounds, 9, HOVER);
            self.assets.icon(
                ui,
                "game",
                Rect::from_center_size(bounds.center(), vec2(26.0, 26.0)),
            );
            if !data.busy
                && let Some(name) = data.selected
                && self.game_hover.as_deref() != Some(name)
            {
                self.game_hover = Some(name.into());
                actions.push(Action::Request(Request {
                    method: "script.icon_path".into(),
                    params: json!({"script_name":name}),
                }));
            }
            let path = self
                .game_icon
                .as_ref()
                .filter(|(name, _)| Some(name.as_str()) == data.selected)
                .and_then(|(_, path)| path.as_deref());
            if let Some(texture) = self.icons.get(path, 256) {
                #[cfg(feature = "capture")]
                {
                    self.capture_icon_ready = true;
                }
                egui::Area::new(Id::new("game-icon-preview"))
                    .order(egui::Order::Tooltip)
                    .fixed_pos(pos2(
                        bounds.left() - 18.0 - 144.0,
                        (bounds.center().y - 72.0).max(4.0),
                    ))
                    .interactable(false)
                    .show(ui.ctx(), |ui| {
                        egui::Frame::new()
                            .fill(CONTROL)
                            .stroke(egui::Stroke::new(1.0, BORDER))
                            .corner_radius(24)
                            .inner_margin(8)
                            .show(ui, |ui| {
                                ui.add(
                                    egui::Image::new(&texture)
                                        .fit_to_exact_size(vec2(128.0, 128.0))
                                        .corner_radius(16),
                                );
                            });
                    });
                return response.clicked();
            }
        } else {
            self.game_hover = None;
        }
        response.on_hover_text("启动游戏").clicked()
    }
}

impl View {
    pub(super) fn toolbar(
        &mut self,
        ui: &mut Ui,
        screen: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) {
        let dx = screen.width() - SIZE.x;
        let toolbar = rect(1212.0 + dx, 88.0, 52.0, 396.0);
        panel(ui, toolbar, 18, PANEL);
        for (index, (icon, name)) in [
            ("home", "游戏官网"),
            ("game", "启动游戏"),
            ("folder", "脚本目录"),
            ("log", "运行日志"),
            ("configfile", "脚本配置文件"),
            ("bili", "哔哩哔哩"),
            ("github", "GitHub"),
            ("wallpaper", "更换壁纸"),
        ]
        .iter()
        .enumerate()
        {
            let bounds = rect(
                toolbar.left() + 8.0,
                100.0 + index as f32 * 48.0,
                36.0,
                36.0,
            );
            let hint = (*name).to_owned();
            let clicked = if *icon == "game" {
                self.game_button(ui, bounds, data, actions)
            } else {
                self.icon_button(ui, icon, bounds, &hint, true)
            };
            if clicked {
                // A click wins over the optional hover read; only one CLI request per frame.
                actions.retain(|action| !matches!(action, Action::Request(request) if request.method == "script.icon_path"));
                if !data.busy {
                    if let Some(script) = data.selected {
                        actions.push(Action::Request(Request {
                            method: match *icon {
                                "game" => "script.launch_target",
                                "wallpaper" => "wallpaper.view",
                                _ => "script.target",
                            }
                            .into(),
                            params: if *icon == "wallpaper" {
                                json!({"script_name":script})
                            } else {
                                json!({"script_name": script, "target": icon})
                            },
                        }));
                    } else {
                        self.toast("尚无脚本");
                    }
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/controllers/links.rs"]
mod tests;
