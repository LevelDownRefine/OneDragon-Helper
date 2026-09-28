use super::*;
use std::{os::windows::ffi::OsStrExt, ptr};
use windows_sys::Win32::{
    Graphics::Gdi::{
        BI_RGB, BITMAPINFO, BITMAPINFOHEADER, CreateCompatibleDC, CreateDIBSection, DIB_RGB_COLORS,
        DeleteDC, DeleteObject, GdiFlush, HBITMAP, HDC, HGDIOBJ, SelectObject,
    },
    UI::WindowsAndMessaging::{DI_NORMAL, DestroyIcon, DrawIconEx, HICON, PrivateExtractIconsW},
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
            let bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, &mut bits, ptr::null_mut(), 0);
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
#[path = "../../../tests/rust-gui/icons/windows.rs"]
mod tests;
