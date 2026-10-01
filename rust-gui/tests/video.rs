use super::*;
#[cfg(windows)]
#[test]
fn dropping_player_releases_worker_and_media() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("close.mp4");
    std::fs::write(&path, include_bytes!("fixtures/wallpaper.mp4")).unwrap();
    let player = Player::new(egui::Context::default());
    let weak = Arc::downgrade(&player.0);
    player.set(1, Some(path.clone()));
    let deadline = Instant::now() + Duration::from_secs(30);
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
    std::fs::write(&path, include_bytes!("fixtures/wallpaper.mp4")).unwrap();
    let player = Player::new(egui::Context::default());
    let started = Instant::now();
    player.set(1, Some(path.clone()));
    std::thread::sleep(Duration::from_millis(100));
    assert!(player.poll().is_none());
    // Decoder startup can be slow on a cold Windows runner. Measure playback
    // only after its first frame, while retaining a bounded startup deadline.
    let startup_deadline = started + Duration::from_secs(30);
    let mut playback_started = None;
    let mut cached = 0;
    let mut received = 0;
    loop {
        let now = Instant::now();
        if let Some(first) = playback_started {
            if now.duration_since(first) >= Duration::from_secs(3) {
                break;
            }
        } else {
            assert!(now < startup_deadline, "decoder produced no first frame");
        }
        if let Some(output) = player.poll() {
            assert_eq!(output.generation, 1);
            let frame = output.result.unwrap();
            cached += usize::from(frame.jpeg.is_some());
            received += 1;
            playback_started.get_or_insert_with(Instant::now);
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
