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
