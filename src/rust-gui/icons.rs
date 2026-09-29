//! Bounded, asynchronous icon extraction. No shell handlers or executable launch.
use eframe::egui;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::mpsc,
};

use crate::theme::CANVAS;
use eframe::egui::{Color32, Pos2, Rect, pos2};

pub struct Assets {
    pub background: egui::TextureHandle,
    pub gradient: egui::TextureHandle,
    pub icons: HashMap<&'static str, egui::TextureHandle>,
}

fn texture(ctx: &egui::Context, name: &str, bytes: &[u8]) -> egui::TextureHandle {
    let image = image::load_from_memory(bytes).expect("valid bundled image");
    let max_side = ctx.input(|input| input.max_texture_side) as u32;
    let image = if image.width().max(image.height()) > max_side {
        image.thumbnail(max_side, max_side)
    } else {
        image
    };
    let rgba = image.to_rgba8();
    let size = [rgba.width() as usize, rgba.height() as usize];
    ctx.load_texture(
        name,
        egui::ColorImage::from_rgba_unmultiplied(size, &rgba),
        egui::TextureOptions::LINEAR,
    )
}

impl Assets {
    pub fn new(ctx: &egui::Context) -> Self {
        let background = texture(
            ctx,
            "default-wallpaper",
            include_bytes!("../../assets/ds.jpg"),
        );
        let mut icons = HashMap::new();
        macro_rules! icon {
            ($name:literal) => {
                icons.insert(
                    $name,
                    texture(
                        ctx,
                        $name,
                        include_bytes!(concat!("assets/icons/", $name, ".png")),
                    ),
                );
            };
        }
        icon!("home");
        icon!("game");
        icon!("folder");
        icon!("bili");
        icon!("github");
        icon!("wallpaper");
        icon!("settings");
        icon!("min");
        icon!("close");
        icon!("log");
        icon!("configfile");
        icon!("play");
        icon!("play_all");
        icon!("chevron_down");
        icon!("grid");
        icon!("script");
        let gradient = ctx.load_texture(
            "wallpaper-gradient",
            egui::ColorImage::new([1, 2], vec![Color32::from_rgb(58, 63, 82), CANVAS]),
            egui::TextureOptions::LINEAR,
        );
        Self {
            background,
            gradient,
            icons,
        }
    }

    pub fn icon(&self, ui: &egui::Ui, name: &str, rect: Rect) {
        assert!(self.icons.contains_key(name), "bundled icon must exist");
        let handle = &self.icons[name];
        ui.painter().image(
            handle.id(),
            rect,
            Rect::from_min_max(Pos2::ZERO, pos2(1.0, 1.0)),
            Color32::WHITE,
        );
    }
}

const CAPACITY: usize = 96;

#[derive(Clone, Hash, Eq, PartialEq)]
struct Key {
    path: PathBuf,
    size: u32,
}

struct Entry {
    texture: Option<egui::TextureHandle>,
    used: u64,
}

type Loaded = (u64, Key, Result<Option<egui::ColorImage>, String>);

pub struct Icons {
    requests: mpsc::SyncSender<(u64, Key)>,
    replies: mpsc::Receiver<Loaded>,
    entries: HashMap<Key, Entry>,
    generation: u64,
    clock: u64,
}

impl Icons {
    pub fn new(ctx: egui::Context) -> Self {
        Self::with_loader(ctx, |key| extract(&key.path, key.size))
    }

    fn with_loader(
        ctx: egui::Context,
        loader: impl Fn(&Key) -> Result<Option<egui::ColorImage>, String> + Send + 'static,
    ) -> Self {
        let (requests, incoming) = mpsc::sync_channel::<(u64, Key)>(8);
        let (outgoing, replies) = mpsc::sync_channel(8);
        std::thread::spawn(move || {
            for (generation, key) in incoming {
                let result = loader(&key);
                if outgoing.send((generation, key, result)).is_err() {
                    break;
                }
                ctx.request_repaint();
            }
        });
        Self {
            requests,
            replies,
            entries: HashMap::new(),
            generation: 0,
            clock: 0,
        }
    }

    pub fn invalidate(&mut self) {
        self.generation += 1;
        self.entries.clear();
    }

    pub fn poll(&mut self, ctx: &egui::Context) {
        while let Ok((generation, key, result)) = self.replies.try_recv() {
            if generation != self.generation {
                continue;
            }
            let Some(entry) = self.entries.get_mut(&key) else {
                continue;
            };
            match result {
                Ok(Some(image)) => {
                    entry.texture = Some(ctx.load_texture(
                        format!("icon:{}:{}", key.path.display(), key.size),
                        image,
                        egui::TextureOptions::LINEAR,
                    ))
                }
                Ok(None) => {}
                Err(error) => log::warn!("读取图标 {} 失败：{error}", key.path.display()),
            }
        }
    }

    pub fn get(&mut self, path: Option<&Path>, size: u32) -> Option<egui::TextureHandle> {
        let path = path?;
        assert!(matches!(size, 64 | 256));
        let key = Key {
            path: path.into(),
            size,
        };
        self.clock += 1;
        if let Some(entry) = self.entries.get_mut(&key) {
            entry.used = self.clock;
            return entry.texture.clone();
        }
        if self
            .requests
            .try_send((self.generation, key.clone()))
            .is_ok()
        {
            if self.entries.len() == CAPACITY {
                let oldest = self
                    .entries
                    .iter()
                    .min_by_key(|(_, entry)| entry.used)
                    .map(|(key, _)| key.clone())
                    .unwrap();
                self.entries.remove(&oldest);
            }
            self.entries.insert(
                key,
                Entry {
                    texture: None,
                    used: self.clock,
                },
            );
        }
        None
    }
}

#[cfg(not(windows))]
fn extract(_path: &Path, _size: u32) -> Result<Option<egui::ColorImage>, String> {
    Ok(None)
}

#[cfg(windows)]
fn extract(path: &Path, size: u32) -> Result<Option<egui::ColorImage>, String> {
    windows::extract(path, size)
}

#[cfg(windows)]
#[path = "windows/icons.rs"]
mod windows;

#[cfg(test)]
#[path = "../../tests/rust-gui/icons.rs"]
mod tests;
