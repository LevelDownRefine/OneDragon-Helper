use super::*;
#[test]
fn native_resizes_large_frames_and_applies_rotation() {
    let root = tempfile::tempdir().unwrap();
    let _runtime = Runtime::new().unwrap();
    for (name, bytes, size) in [
        (
            "wide.mp4",
            include_bytes!("../fixtures/wallpaper-wide.mp4").as_slice(),
            (1920, 64),
        ),
        (
            "rotated.mp4",
            include_bytes!("../fixtures/wallpaper-rotated.mp4").as_slice(),
            (64, 96),
        ),
    ] {
        let path = root.path().join(name);
        std::fs::write(&path, bytes).unwrap();
        let mut decoder = Decoder::open(&path).unwrap();
        let frame = decoder.next().unwrap().unwrap().1;
        assert_eq!(frame.dimensions(), size, "{name}");
        if name == "rotated.mp4" {
            let red = frame.get_pixel(58, 85).0;
            assert!(red[0] as i16 - red[2] as i16 > 150, "rotated red: {red:?}");
        }
    }
}
#[test]
fn native_h264_decodes_muted_seeks_and_releases_file() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("带声音的视频.mp4");
    std::fs::write(&path, include_bytes!("../fixtures/wallpaper.mp4")).unwrap();
    let _runtime = Runtime::new().unwrap();
    let mut decoder = Decoder::open(&path).unwrap();
    assert!(
        !unsafe {
            decoder
                .reader
                .GetStreamSelection(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32)
        }
        .unwrap()
        .as_bool()
    );
    let mut frames = Vec::new();
    while let Some(frame) = decoder.next().unwrap() {
        frames.push(frame);
    }
    assert_eq!(frames.len(), 6);
    assert_eq!(frames[0].1.dimensions(), (96, 64));
    assert!(frames.windows(2).all(|frames| frames[1].0 > frames[0].0));
    // Known lower bands avoid testsrc2's moving overlays near the top edge.
    let red = frames[0].1.get_pixel(10, 58).0;
    let blue = frames[0].1.get_pixel(50, 58).0;
    assert!(red[0] as i16 - red[2] as i16 > 150, "red: {red:?}");
    assert!(blue[2] as i16 - blue[0] as i16 > 150, "blue: {blue:?}");
    decoder.rewind().unwrap();
    let first = decoder.next().unwrap().unwrap();
    assert_eq!(first, frames[0]);
    drop(decoder);
    std::fs::remove_file(path).unwrap();
}
#[test]
fn signed_stride_padding_and_bounds_are_checked() {
    let bytes = [0, 0, 255, 0, 9, 9, 9, 9, 255, 0, 0, 0, 9, 9, 9, 9];
    let top_down = copy_bgra(&bytes, 0, 8, 1, 2).unwrap();
    assert_eq!(top_down.get_pixel(0, 0).0, [255, 0, 0]);
    assert_eq!(top_down.get_pixel(0, 1).0, [0, 0, 255]);
    let bottom_up = copy_bgra(&bytes, 8, -8, 1, 2).unwrap();
    assert_eq!(bottom_up.get_pixel(0, 0).0, [0, 0, 255]);
    assert!(copy_bgra(&bytes, 0, -8, 1, 2).is_err());
    assert!(copy_bgra(&bytes, 0, 2, 1, 2).is_err());
    assert!(copy_bgra(&bytes, 0, 8, 1, 3).is_err());
}
