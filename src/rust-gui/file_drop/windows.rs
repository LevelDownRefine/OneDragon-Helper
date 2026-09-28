use super::*;
use std::{cell::Cell, ptr, sync::mpsc};
use windows_sys::Win32::{
    Foundation::{DRAGDROP_E_NOTREGISTERED, HWND, LPARAM, LRESULT, WPARAM},
    System::Ole::RevokeDragDrop,
    UI::{
        Shell::{
            DefSubclassProc, DragAcceptFiles, DragFinish, DragQueryFileW, HDROP,
            RemoveWindowSubclass, SetWindowSubclass,
        },
        WindowsAndMessaging::{
            ChangeWindowMessageFilterEx, MSGFLT_ALLOW, WM_DROPFILES, WM_NCDESTROY,
        },
    },
};

const ID: usize = 0x4f444844;
const WM_COPYGLOBALDATA: u32 = 0x0049;

pub struct Data {
    pub enabled: Cell<bool>,
    destroyed: Cell<bool>,
    sender: mpsc::SyncSender<Result<Vec<PathBuf>, String>>,
    ctx: egui::Context,
}

pub struct Hook {
    hwnd: HWND,
    pub data: Option<Box<Data>>,
    pub receiver: mpsc::Receiver<Result<Vec<PathBuf>, String>>,
}

impl Hook {
    pub fn install(hwnd: HWND, ctx: egui::Context) -> Result<Self, String> {
        let (sender, receiver) = mpsc::sync_channel(4);
        let mut data = Box::new(Data {
            enabled: Cell::new(false),
            destroyed: Cell::new(false),
            sender,
            ctx,
        });
        // The boxed address is stable; installation and removal stay on the GUI thread.
        unsafe {
            if SetWindowSubclass(hwnd, Some(callback), ID, (&mut *data as *mut Data) as usize) == 0
            {
                return Err(format!(
                    "安装文件拖放失败：{}",
                    std::io::Error::last_os_error()
                ));
            }
            // OLE has priority and rejects Explorer drops across integrity levels.
            let result = RevokeDragDrop(hwnd);
            if result != 0 && result != DRAGDROP_E_NOTREGISTERED {
                log::warn!("撤销 OLE 拖放注册失败：HRESULT {result:#x}");
            }
            for message in [WM_DROPFILES, WM_COPYGLOBALDATA] {
                if ChangeWindowMessageFilterEx(hwnd, message, MSGFLT_ALLOW, ptr::null_mut()) == 0 {
                    log::warn!(
                        "放行文件拖放消息 {message:#x} 失败：{}",
                        std::io::Error::last_os_error()
                    );
                }
            }
            DragAcceptFiles(hwnd, 1);
        }
        Ok(Self {
            hwnd,
            data: Some(data),
            receiver,
        })
    }
}

impl Drop for Hook {
    fn drop(&mut self) {
        let data = self.data.take().unwrap();
        if !data.destroyed.get() {
            unsafe {
                DragAcceptFiles(self.hwnd, 0);
                if RemoveWindowSubclass(self.hwnd, Some(callback), ID) == 0 {
                    // Retain callback storage if Windows cannot detach it; never leave a dangling pointer.
                    log::error!("移除文件拖放回调失败，保留回调存储直到进程退出");
                    let _ = Box::leak(data);
                }
            }
        }
    }
}

unsafe extern "system" fn callback(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    _: usize,
    reference: usize,
) -> LRESULT {
    // Owned by Hook until successful detach, or until WM_NCDESTROY has run.
    let data = unsafe { &*(reference as *const Data) };
    if message == WM_DROPFILES {
        struct Finish(HDROP);
        impl Drop for Finish {
            fn drop(&mut self) {
                unsafe {
                    DragFinish(self.0);
                }
            }
        }
        let drop = Finish(wparam as HDROP);
        let result = if data.enabled.get() {
            read_paths(drop.0)
        } else {
            Err("对话框打开或操作进行中，本次拖入已忽略".into())
        };
        if let Err(error) = data.sender.try_send(result) {
            log::warn!("文件拖入队列不可用，本次拖入已忽略：{error}");
        }
        data.ctx.request_repaint();
        return 0;
    }
    if message == WM_NCDESTROY {
        data.destroyed.set(true);
        unsafe {
            RemoveWindowSubclass(hwnd, Some(callback), ID);
        }
    }
    unsafe { DefSubclassProc(hwnd, message, wparam, lparam) }
}

fn read_paths(drop: HDROP) -> Result<Vec<PathBuf>, String> {
    use std::os::windows::ffi::OsStringExt;
    let count = unsafe { DragQueryFileW(drop, u32::MAX, ptr::null_mut(), 0) };
    if count == 0 || count > 128 {
        return Err("请一次拖入 1 到 128 个脚本文件".into());
    }
    (0..count)
        .map(|index| {
            let length = unsafe { DragQueryFileW(drop, index, ptr::null_mut(), 0) };
            if length == 0 || length > 32767 {
                return Err(format!("第 {} 个文件路径无效", index + 1));
            }
            let mut buffer = vec![0; length as usize + 1];
            if unsafe { DragQueryFileW(drop, index, buffer.as_mut_ptr(), length + 1) } != length {
                return Err(format!("无法读取第 {} 个文件路径", index + 1));
            }
            Ok(std::ffi::OsString::from_wide(&buffer[..length as usize]).into())
        })
        .collect()
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/file_drop/windows.rs"]
mod tests;
