//! Bounded, asynchronous icon extraction. No shell handlers or executable launch.
use eframe::egui;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::mpsc,
};

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
mod windows {
    use super::*;
    use std::{os::windows::ffi::OsStrExt, ptr};
    use windows_sys::Win32::{
        Graphics::Gdi::{
            BI_RGB, BITMAPINFO, BITMAPINFOHEADER, CreateCompatibleDC, CreateDIBSection,
            DIB_RGB_COLORS, DeleteDC, DeleteObject, GdiFlush, HBITMAP, HDC, HGDIOBJ, SelectObject,
        },
        UI::WindowsAndMessaging::{
            DI_NORMAL, DestroyIcon, DrawIconEx, HICON, PrivateExtractIconsW,
        },
    };

    struct Icon(HICON);
    impl Drop for Icon {
        fn drop(&mut self) {
            unsafe {
                DestroyIcon(self.0);
            }
        }
    }

    struct Surface {
        dc: HDC,
        bitmap: HBITMAP,
        previous: HGDIOBJ,
        bits: *mut u8,
        length: usize,
    }

    impl Surface {
        fn new(size: u32) -> Result<Self, String> {
            unsafe {
                let dc = CreateCompatibleDC(ptr::null_mut());
                if dc.is_null() {
                    return Err(std::io::Error::last_os_error().to_string());
                }
                let info = BITMAPINFO {
                    bmiHeader: BITMAPINFOHEADER {
                        biSize: size_of::<BITMAPINFOHEADER>() as u32,
                        biWidth: size as i32,
                        biHeight: -(size as i32),
                        biPlanes: 1,
                        biBitCount: 32,
                        biCompression: BI_RGB,
                        ..Default::default()
                    },
                    ..Default::default()
                };
                let mut bits = ptr::null_mut();
                let bitmap =
                    CreateDIBSection(dc, &info, DIB_RGB_COLORS, &mut bits, ptr::null_mut(), 0);
                if bitmap.is_null() {
                    let error = std::io::Error::last_os_error().to_string();
                    DeleteDC(dc);
                    return Err(error);
                }
                let previous = SelectObject(dc, bitmap);
                if previous.is_null() || previous as isize == -1 {
                    let error = std::io::Error::last_os_error().to_string();
                    DeleteObject(bitmap);
                    DeleteDC(dc);
                    return Err(error);
                }
                Ok(Self {
                    dc,
                    bitmap,
                    previous,
                    bits: bits.cast(),
                    length: size as usize * size as usize * 4,
                })
            }
        }

        fn draw(&mut self, icon: &Icon, size: u32, background: u8) -> Result<Vec<u8>, String> {
            unsafe {
                let pixels = std::slice::from_raw_parts_mut(self.bits, self.length);
                for pixel in pixels.chunks_exact_mut(4) {
                    pixel.copy_from_slice(&[background, background, background, 255]);
                }
                if DrawIconEx(
                    self.dc,
                    0,
                    0,
                    icon.0,
                    size as i32,
                    size as i32,
                    0,
                    ptr::null_mut(),
                    DI_NORMAL,
                ) == 0
                {
                    return Err(std::io::Error::last_os_error().to_string());
                }
                if GdiFlush() == 0 {
                    return Err("GDI 图标绘制失败".into());
                }
                Ok(std::slice::from_raw_parts(self.bits, self.length).to_vec())
            }
        }
    }

    impl Drop for Surface {
        fn drop(&mut self) {
            unsafe {
                SelectObject(self.dc, self.previous);
                DeleteObject(self.bitmap);
                DeleteDC(self.dc);
            }
        }
    }

    pub fn extract(path: &Path, size: u32) -> Result<Option<egui::ColorImage>, String> {
        if !path.is_file() {
            return Ok(None);
        }
        let wide: Vec<_> = path.as_os_str().encode_wide().chain([0]).collect();
        let mut handle = ptr::null_mut();
        let count = unsafe {
            PrivateExtractIconsW(
                wide.as_ptr(),
                0,
                size as i32,
                size as i32,
                &mut handle,
                ptr::null_mut(),
                1,
                0,
            )
        };
        if handle.is_null() {
            return Ok(None);
        }
        let icon = Icon(handle);
        if count != 1 {
            return Ok(None);
        }
        let mut surface = Surface::new(size)?;
        let black = surface.draw(&icon, size, 0)?;
        let white = surface.draw(&icon, size, 255)?;
        Ok(Some(from_backgrounds(&black, &white, size)))
    }

    // Two backgrounds recover alpha for both ARGB icons and legacy AND masks.
    fn from_backgrounds(black: &[u8], white: &[u8], size: u32) -> egui::ColorImage {
        let mut rgba = Vec::with_capacity(black.len());
        for (black, white) in black.chunks_exact(4).zip(white.chunks_exact(4)) {
            let alpha = 255
                - (0..3)
                    .map(|channel| white[channel].saturating_sub(black[channel]))
                    .max()
                    .unwrap();
            rgba.extend([
                black[2].min(alpha),
                black[1].min(alpha),
                black[0].min(alpha),
                alpha,
            ]);
        }
        egui::ColorImage::from_rgba_premultiplied([size as usize; 2], &rgba)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn extracts_real_resources_and_missing_files_fall_back() {
            let shell =
                PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join("System32/shell32.dll");
            for size in [64, 256] {
                let image = extract(&shell, size).unwrap().unwrap();
                assert_eq!(image.size, [size as usize; 2]);
                assert!(image.pixels.iter().any(|pixel| pixel.a() > 0));
                assert!(image.pixels.iter().any(|pixel| pixel.a() == 0));
            }
            let root = tempfile::tempdir().unwrap();
            assert!(
                extract(&root.path().join("missing.exe"), 64)
                    .unwrap()
                    .is_none()
            );
            let invalid = root.path().join("无图标.exe");
            std::fs::write(&invalid, "not an executable").unwrap();
            assert!(extract(&invalid, 64).unwrap().is_none());
        }

        #[test]
        fn mask_and_partial_alpha_do_not_create_black_boxes() {
            for (black, white, expected) in [
                ([0, 0, 0, 255], [255, 255, 255, 255], [0, 0, 0, 0]),
                ([12, 24, 40, 255], [12, 24, 40, 255], [40, 24, 12, 255]),
                ([10, 20, 30, 255], [137, 147, 157, 255], [30, 20, 10, 128]),
            ] {
                assert_eq!(
                    from_backgrounds(&black, &white, 1).pixels[0].to_array(),
                    expected
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
        time::{Duration, Instant},
    };

    #[test]
    fn pending_old_icon_cannot_replace_refreshed_entry() {
        let ctx = egui::Context::default();
        let (started, wait_start) = mpsc::channel();
        let (release, wait_release) = mpsc::channel();
        let mut icons = Icons::with_loader(ctx.clone(), move |_| {
            started.send(()).unwrap();
            wait_release.recv().unwrap();
            Ok(Some(egui::ColorImage::new(
                [1, 1],
                vec![egui::Color32::WHITE],
            )))
        });
        let path = Path::new("same.exe");
        icons.get(Some(path), 64);
        wait_start.recv_timeout(Duration::from_secs(5)).unwrap();
        icons.invalidate();
        icons.get(Some(path), 64);
        release.send(()).unwrap();
        wait_start.recv_timeout(Duration::from_secs(5)).unwrap();
        icons.poll(&ctx);
        assert!(
            icons.get(Some(path), 64).is_none(),
            "old generation must be discarded"
        );
        release.send(()).unwrap();
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            icons.poll(&ctx);
            if icons.get(Some(path), 64).is_some() {
                break;
            }
            assert!(Instant::now() < end);
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    #[test]
    fn cache_evicts_oldest_paths_at_capacity() {
        let mut icons = Icons::with_loader(egui::Context::default(), |_| Ok(None));
        for index in 0..CAPACITY * 2 {
            icons.get(Some(Path::new(&format!("{index}.exe"))), 64);
            assert!(
                icons
                    .replies
                    .recv_timeout(Duration::from_secs(5))
                    .unwrap()
                    .2
                    .unwrap()
                    .is_none()
            );
        }
        assert_eq!(icons.entries.len(), CAPACITY);
        assert!(!icons.entries.contains_key(&Key {
            path: "0.exe".into(),
            size: 64
        }));
        assert!(icons.entries.contains_key(&Key {
            path: format!("{}.exe", CAPACITY * 2 - 1).into(),
            size: 64
        }));
    }

    #[test]
    fn refresh_retries_missing_icons() {
        let present = Arc::new(AtomicBool::new(false));
        let captured = present.clone();
        let ctx = egui::Context::default();
        let mut icons = Icons::with_loader(ctx.clone(), move |_| {
            Ok(captured
                .load(Ordering::SeqCst)
                .then(|| egui::ColorImage::new([1, 1], vec![egui::Color32::WHITE])))
        });
        let path = Path::new("same.exe");
        icons.get(Some(path), 64);
        let old = icons.replies.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(old.2.unwrap().is_none());
        present.store(true, Ordering::SeqCst);
        assert!(icons.get(Some(path), 64).is_none());
        icons.invalidate();
        icons.get(Some(path), 64);
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            icons.poll(&ctx);
            if icons.get(Some(path), 64).is_some() {
                break;
            }
            assert!(Instant::now() < end);
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(icons.entries.len(), 1);
    }
}
