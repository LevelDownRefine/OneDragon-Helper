//! Native script picker. Cancellation does not change the form.
use std::sync::mpsc::{self, Receiver, TryRecvError};

pub struct FilePicker(Receiver<Result<Option<String>, String>>);

impl FilePicker {
    pub fn start(ctx: eframe::egui::Context, include_shortcuts: bool) -> Self {
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = sender.send(pick(include_shortcuts));
            ctx.request_repaint();
        });
        Self(receiver)
    }

    pub fn poll(&self) -> Option<Result<Option<String>, String>> {
        match self.0.try_recv() {
            Ok(result) => Some(result),
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => Some(Err("文件选择窗口意外退出".into())),
        }
    }
}

#[cfg(windows)]
fn pick(include_shortcuts: bool) -> Result<Option<String>, String> {
    use windows_sys::Win32::UI::Controls::Dialogs::{
        CommDlgExtendedError, GetOpenFileNameW, OFN_DONTADDTORECENT, OFN_FILEMUSTEXIST,
        OFN_NOCHANGEDIR, OFN_PATHMUSTEXIST, OPENFILENAMEW,
    };
    let filter: Vec<u16> = if include_shortcuts {
        "脚本和快捷方式\0*.exe;*.bat;*.py;*.lnk\0所有文件\0*.*\0\0"
    } else {
        "脚本文件\0*.exe;*.bat;*.py\0所有文件\0*.*\0\0"
    }
    .encode_utf16()
    .collect();
    let title: Vec<u16> = "选择脚本".encode_utf16().chain(Some(0)).collect();
    let mut buffer = vec![0_u16; 32768];
    let mut dialog = OPENFILENAMEW {
        lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
        lpstrFilter: filter.as_ptr(),
        nFilterIndex: 1,
        lpstrFile: buffer.as_mut_ptr(),
        nMaxFile: buffer.len() as u32,
        lpstrTitle: title.as_ptr(),
        Flags: OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_DONTADDTORECENT,
        ..Default::default()
    };
    // The dialog owns no buffer; all pointers remain valid until it closes.
    if unsafe { GetOpenFileNameW(&mut dialog) } == 0 {
        let error = unsafe { CommDlgExtendedError() };
        return if error == 0 {
            Ok(None)
        } else {
            Err(format!("文件选择失败：{error}"))
        };
    }
    let length = buffer
        .iter()
        .position(|value| *value == 0)
        .unwrap_or(buffer.len());
    String::from_utf16(&buffer[..length])
        .map(Some)
        .map_err(|error| error.to_string())
}

#[cfg(not(windows))]
fn pick(_include_shortcuts: bool) -> Result<Option<String>, String> {
    Err("当前系统请直接粘贴脚本路径".into())
}
