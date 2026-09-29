//! Window-local WM_DROPFILES support, including elevated Windows windows.
use eframe::egui;
use std::path::PathBuf;

pub struct FileDrop {
    #[cfg(windows)]
    native: windows::Hook,
}

impl FileDrop {
    pub fn new(cc: &eframe::CreationContext<'_>) -> Result<Self, String> {
        #[cfg(windows)]
        {
            use raw_window_handle::{HasWindowHandle, RawWindowHandle};
            let RawWindowHandle::Win32(handle) =
                cc.window_handle().map_err(|e| e.to_string())?.as_raw()
            else {
                return Err("无法取得 Windows 窗口句柄".into());
            };
            Ok(Self {
                native: windows::Hook::install(handle.hwnd.get() as _, cc.egui_ctx.clone())?,
            })
        }
        #[cfg(not(windows))]
        {
            let _ = cc;
            Ok(Self {})
        }
    }

    pub fn set_enabled(&self, enabled: bool) {
        #[cfg(windows)]
        self.native.data.as_ref().unwrap().enabled.set(enabled);
        #[cfg(not(windows))]
        let _ = enabled;
    }

    pub fn poll(&self, ctx: &egui::Context) -> Option<Result<Vec<PathBuf>, String>> {
        #[cfg(windows)]
        {
            let _ = ctx;
            self.native.receiver.try_recv().ok()
        }
        #[cfg(not(windows))]
        {
            fallback(ctx)
        }
    }
}

pub fn fallback(ctx: &egui::Context) -> Option<Result<Vec<PathBuf>, String>> {
    let files = ctx.input(|input| input.raw.dropped_files.clone());
    if files.is_empty() {
        None
    } else {
        Some(Ok(files
            .into_iter()
            .map(|file| file.path().to_path_buf())
            .collect()))
    }
}

#[cfg(windows)]
#[path = "windows/file_drop.rs"]
mod windows;
