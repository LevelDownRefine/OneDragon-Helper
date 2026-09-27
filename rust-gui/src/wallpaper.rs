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
        let modal = egui::Modal::new(egui::Id::new("wallpaper-dialog"))
            .frame(
                egui::Frame::new()
                    .fill(crate::skin::PANEL)
                    .corner_radius(16)
                    .inner_margin(20),
            )
            .show(ctx, |ui| {
                ui.set_width(520.0);
                ui.heading(format!("{} · 壁纸", self.state.display_name));
                ui.label(format!("当前来源：{}", self.state.source.display()));
                ui.label("图片：PNG、JPEG、WebP、BMP；视频：MP4、WebM、MKV、MOV。");
                ui.label("视频静音循环播放；能否解码取决于 Windows 已安装的编解码器。");
                ui.add_enabled_ui(!blocked && !self.needs_reload, |ui| {
                    ui.horizontal(|ui| {
                        ui.add(egui::TextEdit::singleline(&mut self.path).desired_width(410.0));
                        if ui.button("浏览…").clicked() {
                            self.picker = Some(crate::file_picker::FilePicker::start(
                                ctx.clone(),
                                crate::file_picker::FileKind::Wallpaper,
                            ));
                        }
                    });
                });
                if let Some(error) = &self.error {
                    ui.colored_label(egui::Color32::LIGHT_RED, error);
                }
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(!blocked, egui::Button::new("取消"))
                        .clicked()
                    {
                        action = Some(WallpaperAction::Close);
                    }
                    if self.needs_reload {
                        if ui
                            .add_enabled(!blocked, egui::Button::new("重新读取"))
                            .clicked()
                        {
                            action = Some(WallpaperAction::Request(Request {
                                method: "wallpaper.view".into(),
                                params: json!({"script_name":self.state.script_name}),
                            }));
                        }
                    } else {
                        if ui
                            .add_enabled(!blocked, egui::Button::new("恢复默认"))
                            .clicked()
                        {
                            action = Some(self.save(None));
                        }
                        if ui
                            .add_enabled(!blocked, egui::Button::new("应用壁纸"))
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
                    if blocked {
                        ui.spinner();
                    }
                });
            });
        if !blocked && modal.should_close() {
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
mod tests {
    use super::*;
    #[test]
    fn video_decode_failure_preserves_existing_preview_or_gradient() {
        let root = tempfile::tempdir().unwrap();
        let source = root.path().join("broken.mp4");
        std::fs::write(&source, "not a video").unwrap();
        let preview = root.path().join("preview.jpg");
        image::RgbImage::from_pixel(4, 4, image::Rgb([255, 0, 0]))
            .save(&preview)
            .unwrap();
        for cache in [None, Some(preview.clone())] {
            let ctx = egui::Context::default();
            let mut backdrop = Backdrop::new(ctx.clone());
            let mut state = state(source.clone());
            state.mode = Mode::Video;
            state.cache = cache.clone();
            backdrop.set(state);
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
            loop {
                if let Some(error) = backdrop.poll(&ctx) {
                    assert!(error.contains("视频无法播放"));
                    break;
                }
                assert!(std::time::Instant::now() < deadline);
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            assert!(backdrop.ready);
            assert_eq!(backdrop.texture.is_some(), cache.is_some());
            assert!(backdrop.take_cache().is_none());
            backdrop.select("另一脚本");
            assert!(backdrop.texture.is_none());
            assert!(backdrop.poll(&ctx).is_none());
        }
    }

    fn state(path: PathBuf) -> Wallpaper {
        Wallpaper {
            script_name: "test".into(),
            display_name: "测试".into(),
            mode: Mode::Image,
            source: path,
            custom_path: None,
            token: Some("current".into()),
            cache: None,
        }
    }

    #[test]
    fn formats_resize_and_cache_recovery_keep_source_unchanged() {
        let root = tempfile::tempdir().unwrap();
        for extension in ["png", "jpg", "webp", "bmp"] {
            let path = root.path().join(format!("中文.{extension}"));
            image::RgbImage::from_pixel(3200, 20, image::Rgb([60, 100, 180]))
                .save(&path)
                .unwrap();
            let before = std::fs::read(&path).unwrap();
            let mut state = state(path.clone());
            let corrupt = root.path().join("corrupt.jpg");
            std::fs::write(&corrupt, "bad cache").unwrap();
            state.cache = Some(corrupt);
            let loaded = load(&state).unwrap();
            assert_eq!(loaded.image.size, [1920, 12]);
            let jpeg = loaded.jpeg.unwrap();
            assert!(jpeg.starts_with(&[0xff, 0xd8]));
            assert!(jpeg.len() < 4 * 1024 * 1024);
            assert_eq!(std::fs::read(path).unwrap(), before);
        }
    }

    #[test]
    fn missing_corrupt_and_oversized_images_fail_with_no_texture() {
        let root = tempfile::tempdir().unwrap();
        assert!(load(&state(root.path().join("missing.png"))).is_err());
        let path = root.path().join("bad.png");
        std::fs::write(&path, "not a PNG").unwrap();
        assert!(load(&state(path.clone())).is_err());
        image::RgbImage::new(16385, 1).save(&path).unwrap();
        assert!(load(&state(path)).is_err());
    }

    #[test]
    fn selection_discards_old_decode_and_pending_cache() {
        let ctx = egui::Context::default();
        let mut backdrop = Backdrop::new(ctx.clone());
        let (sender, receiver) = mpsc::sync_channel(1);
        backdrop.receiver = receiver;
        let old_generation = backdrop.generation;
        backdrop.select("新脚本");
        sender
            .send((
                old_generation,
                Ok(Loaded {
                    image: egui::ColorImage::new([1, 1], vec![egui::Color32::WHITE]),
                    jpeg: Some(vec![1]),
                }),
            ))
            .unwrap();
        assert!(backdrop.poll(&ctx).is_none());
        assert!(backdrop.texture.is_none());
        assert!(backdrop.take_cache().is_none());
        assert_eq!(backdrop.placeholder.as_deref(), Some("新"));
    }

    #[test]
    fn escape_cancels_wallpaper_without_saving() {
        let ctx = egui::Context::default();
        let mut dialog = WallpaperDialog::new(state("unused.png".into()));
        dialog.path = "draft.png".into();
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
                    Some(WallpaperAction::Close)
                ));
            },
        );
        output.textures_delta.clear();
    }
}
