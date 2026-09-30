use super::*;
#[test]
fn video_decode_failure_preserves_existing_preview_or_gradient() {
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("broken.mp4");
    std::fs::write(&source, "not a video").unwrap();
    let preview = root.path().join("preview.jpg");
    image::RgbImage::from_pixel(4, 4, image::Rgb([255, 0, 0]))
        .save(&preview)
        .unwrap();
    for cache in [None, Some(preview.clone())] {
        let ctx = egui::Context::default();
        let mut backdrop = Backdrop::new(ctx.clone());
        let mut state = state(source.clone());
        state.mode = Mode::Video;
        state.cache = cache.clone();
        backdrop.set(state);
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        loop {
            if let Some(error) = backdrop.poll(&ctx) {
                assert!(error.contains("视频无法播放"));
                break;
            }
            assert!(std::time::Instant::now() < deadline);
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        assert!(backdrop.ready);
        assert_eq!(backdrop.texture.is_some(), cache.is_some());
        assert!(backdrop.take_cache().is_none());
        backdrop.select("另一脚本");
        assert!(backdrop.texture.is_none());
        assert!(backdrop.poll(&ctx).is_none());
    }
}

fn state(path: PathBuf) -> Wallpaper {
    Wallpaper {
        script_name: "test".into(),
        display_name: "测试".into(),
        mode: Mode::Image,
        source: path,
        custom_path: None,
        token: Some("current".into()),
        cache: None,
    }
}

#[test]
fn formats_resize_and_cache_recovery_keep_source_unchanged() {
    let root = tempfile::tempdir().unwrap();
    for extension in ["png", "jpg", "webp", "bmp"] {
        let path = root.path().join(format!("中文.{extension}"));
        image::RgbImage::from_pixel(3200, 20, image::Rgb([60, 100, 180]))
            .save(&path)
            .unwrap();
        let before = std::fs::read(&path).unwrap();
        let mut state = state(path.clone());
        let corrupt = root.path().join("corrupt.jpg");
        std::fs::write(&corrupt, "bad cache").unwrap();
        state.cache = Some(corrupt);
        let loaded = load(&state).unwrap();
        assert_eq!(loaded.image.size, [1920, 12]);
        let jpeg = loaded.jpeg.unwrap();
        assert!(jpeg.starts_with(&[0xff, 0xd8]));
        assert!(jpeg.len() < 4 * 1024 * 1024);
        assert_eq!(std::fs::read(path).unwrap(), before);
    }
}

#[test]
fn missing_corrupt_and_oversized_images_fail_with_no_texture() {
    let root = tempfile::tempdir().unwrap();
    assert!(load(&state(root.path().join("missing.png"))).is_err());
    let path = root.path().join("bad.png");
    std::fs::write(&path, "not a PNG").unwrap();
    assert!(load(&state(path.clone())).is_err());
    image::RgbImage::new(16385, 1).save(&path).unwrap();
    assert!(load(&state(path)).is_err());
}

#[test]
fn selection_discards_old_decode_and_pending_cache() {
    let ctx = egui::Context::default();
    let mut backdrop = Backdrop::new(ctx.clone());
    let (sender, receiver) = mpsc::sync_channel(1);
    backdrop.receiver = receiver;
    let old_generation = backdrop.generation;
    backdrop.select("新脚本");
    sender
        .send((
            old_generation,
            Ok(Loaded {
                image: egui::ColorImage::new([1, 1], vec![egui::Color32::WHITE]),
                jpeg: Some(vec![1]),
            }),
        ))
        .unwrap();
    assert!(backdrop.poll(&ctx).is_none());
    assert!(backdrop.texture.is_none());
    assert!(backdrop.take_cache().is_none());
    assert_eq!(backdrop.placeholder.as_deref(), Some("新"));
}
