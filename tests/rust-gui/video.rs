use super::*;
#[cfg(windows)]
#[test]
fn dropping_player_releases_worker_and_media() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("close.mp4");
    std::fs::write(&path, include_bytes!("../fixtures/rust-gui/wallpaper.mp4")).unwrap();
    let player = Player::new(egui::Context::default());
    let weak = Arc::downgrade(&player.0);
    player.set(1, Some(path.clone()));
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(output) = player.poll() {
            output.result.unwrap();
            break;
        }
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(10));
    }
    drop(player);
    let deadline = Instant::now() + Duration::from_secs(3);
    while weak.upgrade().is_some() {
        assert!(Instant::now() < deadline, "decoder worker did not exit");
        std::thread::sleep(Duration::from_millis(10));
    }
    std::fs::remove_file(path).unwrap();
}
#[cfg(windows)]
#[test]
fn playback_delays_loops_and_stops_on_selection_change() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("loop.mp4");
    std::fs::write(&path, include_bytes!("../fixtures/rust-gui/wallpaper.mp4")).unwrap();
    let player = Player::new(egui::Context::default());
    let started = Instant::now();
    player.set(1, Some(path.clone()));
    std::thread::sleep(Duration::from_millis(100));
    assert!(player.poll().is_none());
    let mut cached = 0;
    let mut received = 0;
    while started.elapsed() < Duration::from_secs(3) {
        if let Some(output) = player.poll() {
            assert_eq!(output.generation, 1);
            let frame = output.result.unwrap();
            cached += usize::from(frame.jpeg.is_some());
            received += 1;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    assert!(
        received >= 12,
        "expected multiple loops, received {received}"
    );
    assert_eq!(cached, 1);
    player.set(2, None);
    assert!(player.poll().is_none());
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        match std::fs::remove_file(&path) {
            Ok(()) => break,
            Err(error) if Instant::now() < deadline => {
                log::debug!("waiting for decoder release: {error}");
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("video file remained open: {error}"),
        }
    }
}
#[test]
fn frame_slot_is_bounded_preserves_cache_and_rejects_old_generation() {
    let shared = Shared {
        state: Mutex::new(State::default()),
        changed: Condvar::new(),
    };
    let ctx = egui::Context::default();
    for n in 0..100 {
        shared.publish(
            &ctx,
            Output {
                generation: 0,
                result: Ok(Frame {
                    image: egui::ColorImage::new([1, 1], vec![egui::Color32::from_gray(n)]),
                    jpeg: (n == 0).then(|| vec![1, 2, 3]),
                }),
            },
        );
    }
    let mut state = shared.state.lock().unwrap();
    let output = state.output.take().unwrap().result.unwrap();
    assert_eq!(output.image.pixels[0], egui::Color32::from_gray(99));
    assert_eq!(output.jpeg.unwrap(), [1, 2, 3]);
    state.generation = 1;
    drop(state);
    shared.publish(
        &ctx,
        Output {
            generation: 0,
            result: Err("old error".into()),
        },
    );
    assert!(shared.state.lock().unwrap().output.is_none());
    assert!(!shared.wait_until(0, Instant::now() + Duration::from_secs(60)));
}
