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
mod windows {
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
                if SetWindowSubclass(hwnd, Some(callback), ID, (&mut *data as *mut Data) as usize)
                    == 0
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
                    if ChangeWindowMessageFilterEx(hwnd, message, MSGFLT_ALLOW, ptr::null_mut())
                        == 0
                    {
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
                if unsafe { DragQueryFileW(drop, index, buffer.as_mut_ptr(), length + 1) } != length
                {
                    return Err(format!("无法读取第 {} 个文件路径", index + 1));
                }
                Ok(std::ffi::OsString::from_wide(&buffer[..length as usize]).into())
            })
            .collect()
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use windows_sys::Win32::{
            System::Memory::{GMEM_MOVEABLE, GMEM_ZEROINIT, GlobalAlloc, GlobalLock, GlobalUnlock},
            UI::{
                Shell::DROPFILES,
                WindowsAndMessaging::{CreateWindowExW, DestroyWindow, HWND_MESSAGE, SendMessageW},
            },
        };

        unsafe fn deliver(hwnd: HWND, paths: &[&str]) {
            let wide: Vec<u16> = paths
                .iter()
                .flat_map(|path| path.encode_utf16().chain([0]))
                .chain([0])
                .collect();
            unsafe {
                let memory = GlobalAlloc(
                    GMEM_MOVEABLE | GMEM_ZEROINIT,
                    size_of::<DROPFILES>() + wide.len() * 2,
                );
                assert!(!memory.is_null());
                let pointer = GlobalLock(memory).cast::<u8>();
                assert!(!pointer.is_null());
                let header = DROPFILES {
                    pFiles: size_of::<DROPFILES>() as u32,
                    fWide: 1,
                    ..Default::default()
                };
                ptr::write(pointer.cast::<DROPFILES>(), header);
                ptr::copy_nonoverlapping(
                    wide.as_ptr(),
                    pointer.add(size_of::<DROPFILES>()).cast::<u16>(),
                    wide.len(),
                );
                GlobalUnlock(memory);
                SendMessageW(hwnd, WM_DROPFILES, memory as usize, 0); // Receiver owns/frees HDROP.
            }
        }

        #[test]
        fn real_window_drop_decodes_paths_gates_modals_and_detaches() {
            unsafe {
                for destroy_first in [false, true] {
                    let hwnd = CreateWindowExW(
                        0,
                        windows_sys::core::w!("STATIC"),
                        windows_sys::core::w!("drop test"),
                        0,
                        0,
                        0,
                        1,
                        1,
                        HWND_MESSAGE,
                        ptr::null_mut(),
                        ptr::null_mut(),
                        ptr::null(),
                    );
                    assert!(!hwnd.is_null());
                    let hook = Hook::install(hwnd, egui::Context::default()).unwrap();
                    deliver(hwnd, &["C:\\测试\\a.exe"]);
                    assert!(hook.receiver.try_recv().unwrap().is_err());
                    hook.data.as_ref().unwrap().enabled.set(true);
                    deliver(hwnd, &["C:\\测试\\a.exe", "C:\\with space\\b.lnk"]);
                    assert_eq!(
                        hook.receiver.try_recv().unwrap().unwrap(),
                        vec![
                            PathBuf::from("C:\\测试\\a.exe"),
                            PathBuf::from("C:\\with space\\b.lnk")
                        ]
                    );
                    if destroy_first {
                        assert_ne!(DestroyWindow(hwnd), 0);
                    }
                    drop(hook);
                    if !destroy_first {
                        assert_ne!(DestroyWindow(hwnd), 0);
                    }
                }
            }
        }
    }
}
