use super::super::*;
use super::*;
use base64::Engine;
use eframe::egui;
use image::ImageDecoder;
use onedragon_rust_gui::backend::Request;
use serde::Deserialize;
use serde_json::json;
use std::{
    path::{Path, PathBuf},
    sync::mpsc,
};

/// 背景层（壁纸图、壁纸渐变、遮光层 shade）共用的圆角半径，单位 px。
/// 必须等于窗口边框圆角：否则遮光层与壁纸圆角错位，四角回填残留色块（即 PR #136 所修现象）。
/// 改窗口圆角时，下方三处绘制须同步改动，否则该 bug 复活。
const BACKDROP_CORNER_RADIUS: f32 = 16.0;

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    Image,
    Video,
    Gradient,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct Wallpaper {
    pub script_name: String,
    pub display_name: String,
    pub mode: Mode,
    pub source: PathBuf,
    pub custom_path: Option<PathBuf>,
    pub token: Option<String>,
    pub cache: Option<PathBuf>,
}

struct Loaded {
    image: egui::ColorImage,
    jpeg: Option<Vec<u8>>,
}
type Reply = (u64, Result<Loaded, String>);

pub struct Backdrop {
    video: crate::video::Player,
    video_ready: bool,
    sender: mpsc::SyncSender<(u64, Wallpaper)>,
    receiver: mpsc::Receiver<Reply>,
    pending: Option<(u64, Wallpaper)>,
    generation: u64,
    state: Option<Wallpaper>,
    pub texture: Option<egui::TextureHandle>,
    pub placeholder: Option<String>,
    pub ready: bool,
    cache: Option<Request>,
}

impl Backdrop {
    pub fn new(ctx: egui::Context) -> Self {
        let (sender, requests) = mpsc::sync_channel::<(u64, Wallpaper)>(1);
        let (replies, receiver) = mpsc::sync_channel(1);
        let video = crate::video::Player::new(ctx.clone());
        std::thread::spawn(move || {
            for (generation, state) in requests {
                let result = load(&state);
                if replies.send((generation, result)).is_err() {
                    break;
                }
                ctx.request_repaint();
            }
        });
        Self {
            video,
            video_ready: false,
            sender,
            receiver,
            pending: None,
            generation: 0,
            state: None,
            texture: None,
            placeholder: None,
            ready: false,
            cache: None,
        }
    }

    pub fn select(&mut self, display_name: &str) {
        self.generation += 1;
        self.video.set(self.generation, None);
        self.video_ready = false;
        self.state = None;
        self.pending = None;
        self.cache = None;
        self.texture = None;
        self.placeholder = Some(display_name.chars().take(1).collect());
        self.ready = false;
    }

    pub fn set(&mut self, state: Wallpaper) {
        if self.state.as_ref() == Some(&state) {
            return;
        }
        self.select(&state.display_name);
        if state.mode == Mode::Gradient {
            self.ready = true;
        } else if state.mode != Mode::Video || state.cache.is_some() {
            self.pending = Some((self.generation, state.clone()));
        }
        if state.mode == Mode::Video {
            self.video.set(self.generation, Some(state.source.clone()));
        }
        self.state = Some(state);
    }

    pub fn take_cache(&mut self) -> Option<Request> {
        self.cache.take()
    }

    pub fn poll(&mut self, ctx: &egui::Context) -> Option<String> {
        let mut error = None;
        while let Ok((generation, result)) = self.receiver.try_recv() {
            if generation != self.generation || self.video_ready {
                continue;
            }
            let video = self
                .state
                .as_ref()
                .is_some_and(|state| state.mode == Mode::Video);
            if !video {
                self.ready = true;
            }
            match result {
                Ok(loaded) => {
                    self.texture = Some(ctx.load_texture(
                        "wallpaper",
                        loaded.image,
                        egui::TextureOptions::LINEAR,
                    ));
                    let state = self.state.as_ref().expect("active wallpaper");
                    if let Some(jpeg) = loaded.jpeg
                        && let Some(token) = &state.token
                    {
                        self.cache = Some(Request {
                            method: "wallpaper.cache".into(),
                            params: json!({"script_name":state.script_name,"token":token,"jpeg_base64":base64::engine::general_purpose::STANDARD.encode(jpeg)}),
                        });
                    }
                }
                Err(message) if video => log::warn!("视频首帧缓存不可读，等待解码：{message}"),
                Err(message) => error = Some(format!("壁纸无法显示，已使用渐变背景：{message}")),
            }
        }
        if let Some(output) = self.video.poll()
            && output.generation == self.generation
        {
            self.ready = true;
            match output.result {
                Ok(frame) => {
                    self.video_ready = true;
                    if let Some(texture) = &mut self.texture {
                        texture.set(frame.image, egui::TextureOptions::LINEAR);
                    } else {
                        self.texture = Some(ctx.load_texture(
                            "video-wallpaper",
                            frame.image,
                            egui::TextureOptions::LINEAR,
                        ));
                    }
                    let state = self.state.as_ref().expect("active video");
                    if let (Some(jpeg), Some(token)) = (frame.jpeg, &state.token) {
                        self.cache = Some(Request {
                            method: "wallpaper.cache".into(),
                            params: json!({"script_name":state.script_name,"token":token,"jpeg_base64":base64::engine::general_purpose::STANDARD.encode(jpeg)}),
                        });
                    }
                }
                Err(message) => {
                    error = Some(format!("视频无法播放，保留已有画面或渐变背景：{message}"))
                }
            }
        }
        if let Some(request) = self.pending.take() {
            match self.sender.try_send(request) {
                Ok(()) => {}
                Err(mpsc::TrySendError::Full(request)) => self.pending = Some(request),
                Err(mpsc::TrySendError::Disconnected(_)) => {
                    self.ready = true;
                    error = Some("壁纸解码线程已退出，请重启助手".into());
                }
            }
        }
        error
    }
}

fn decode(path: &Path) -> Result<image::DynamicImage, String> {
    let mut reader = image::ImageReader::open(path)
        .map_err(|e| e.to_string())?
        .with_guessed_format()
        .map_err(|e| e.to_string())?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(16384);
    limits.max_image_height = Some(16384);
    limits.max_alloc = Some(256 * 1024 * 1024);
    reader.limits(limits);
    let mut decoder = reader.into_decoder().map_err(|e| e.to_string())?;
    if decoder.total_bytes() > 256 * 1024 * 1024 {
        return Err("图片解码尺寸过大".into());
    }
    let orientation = decoder.orientation().map_err(|e| e.to_string())?;
    let mut image = image::DynamicImage::from_decoder(decoder).map_err(|e| e.to_string())?;
    image.apply_orientation(orientation);
    Ok(image)
}

fn load(state: &Wallpaper) -> Result<Loaded, String> {
    let mut from_cache = false;
    let mut decoded = None;
    if let Some(cache) = &state.cache {
        match decode(cache) {
            Ok(image) => {
                decoded = Some(image);
                from_cache = true;
            }
            Err(error) => log::warn!("壁纸缓存不可读：{error}"),
        }
    }
    let image = match decoded {
        Some(image) => image,
        None if state.mode == Mode::Video => {
            return Err("视频首帧缓存不可读".into());
        }
        None => decode(&state.source)?,
    };
    let resized = image.width().max(image.height()) > 1920;
    let image = if resized {
        image.resize(1920, 1920, image::imageops::FilterType::Triangle)
    } else {
        image
    };
    let jpeg = if resized && !from_cache {
        let mut bytes = Vec::new();
        image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 90)
            .encode_image(&image.to_rgb8())
            .map_err(|e| e.to_string())?;
        Some(bytes)
    } else {
        None
    };
    let rgba = image.to_rgba8();
    Ok(Loaded {
        image: egui::ColorImage::from_rgba_unmultiplied(
            [rgba.width() as usize, rgba.height() as usize],
            &rgba,
        ),
        jpeg,
    })
}

impl View {
    pub(super) fn background(&self, ui: &mut Ui, screen: Rect) {
        let image = self.wallpaper.texture.as_ref();
        if let Some(image) = image {
            let aspect = image.size_vec2().x / image.size_vec2().y;
            let target = screen.aspect_ratio();
            let uv_size = if aspect > target {
                vec2(target / aspect, 1.0)
            } else {
                vec2(1.0, aspect / target)
            };
            let uv = Rect::from_center_size(pos2(0.5, 0.5), uv_size);
            egui::Image::new((image.id(), screen.size()))
                .uv(uv)
                .corner_radius(BACKDROP_CORNER_RADIUS)
                .paint_at(ui, screen);
        } else {
            egui::Image::new((self.assets.gradient.id(), screen.size()))
                .corner_radius(BACKDROP_CORNER_RADIUS)
                .paint_at(ui, screen);
            if let Some(character) = &self.wallpaper.placeholder {
                ui.painter().text(
                    screen.center(),
                    egui::Align2::CENTER_CENTER,
                    character,
                    egui::FontId::proportional(320.0),
                    egui::Color32::from_white_alpha(15),
                );
            }
        }
        // The shade must follow the wallpaper's corners, not fill their transparent cutouts.
        egui::Image::new((self.assets.shade.id(), screen.size()))
            .corner_radius(BACKDROP_CORNER_RADIUS)
            .paint_at(ui, screen);
    }
}

impl App {
    pub(in crate::main_window) fn select_wallpaper(&mut self) {
        if let Some(script) = self
            .scripts
            .iter()
            .find(|script| Some(&script.script_name) == self.selected.as_ref())
        {
            self.ui.wallpaper.select(&script.display_name);
        }
    }

    pub(in crate::main_window) fn receive_wallpaper(
        &mut self,
        method: &str,
        result: Result<Value, Failure>,
    ) {
        let value = match result {
            Ok(value) => value,
            Err(failure) => {
                let message = if self.write_confirmed {
                    format!("已保存，刷新失败：{}", failure.message)
                } else {
                    failure.message
                };
                log::warn!("壁纸操作失败：{message}");
                if failure.code == "transport_failed" {
                    self.backend = None;
                }
                if method != "wallpaper.cache" {
                    self.ui.toast(&message);
                    if let Some(dialog) = &mut self.wallpaper_dialog {
                        dialog.failure(
                            message,
                            self.write_confirmed
                                || failure.refresh_required
                                || failure.code == "transport_failed",
                        );
                    }
                }
                self.write_confirmed = false;
                self.status = "壁纸操作失败".into();
                return;
            }
        };
        match method {
            "wallpaper.cache" if value.is_boolean() => {
                self.status = "已同步".into();
            }
            "wallpaper.set" if value.is_null() => {
                let name = self
                    .wallpaper_dialog
                    .as_ref()
                    .expect("wallpaper editor open")
                    .script_name()
                    .to_owned();
                self.write_confirmed = true;
                self.request("wallpaper.view", json!({"script_name":name}));
            }
            "wallpaper.current" | "wallpaper.view" => {
                match serde_json::from_value::<Wallpaper>(value) {
                    Ok(state) if Some(&state.script_name) == self.selected.as_ref() => {
                        self.ui.wallpaper.set(state.clone());
                        self.wallpaper_pending = None;
                        if method == "wallpaper.view" {
                            self.wallpaper_dialog = Some(WallpaperDialog::new(state));
                        }
                        self.write_confirmed = false;
                        self.status = "已同步".into();
                    }
                    _ => self.fail(Failure::transport("壁纸响应无效")),
                }
            }
            _ => self.fail(Failure::transport("壁纸响应无效")),
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_wallpaper(&mut self, ui: &mut Ui) {
        let blocked = self.dialog_blocked();
        if let Some(action) = self
            .wallpaper_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx(), blocked))
        {
            match action {
                WallpaperAction::Close => {
                    self.wallpaper_dialog = None;
                    if self.view.is_none() && self.backend.is_some() {
                        self.refresh_view();
                    }
                }
                WallpaperAction::Request(request) => {
                    if self.backend.is_none() {
                        self.wallpaper_dialog = None;
                        self.open_wallpaper_after_snapshot = true;
                        self.connect();
                    } else {
                        self.request(&request.method, request.params);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "../../tests/controllers/background.rs"]
mod tests;
