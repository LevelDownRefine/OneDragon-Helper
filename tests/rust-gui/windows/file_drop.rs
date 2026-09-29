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
