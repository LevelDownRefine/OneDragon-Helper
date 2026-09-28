use super::*;

#[test]
fn extracts_real_resources_and_missing_files_fall_back() {
    let shell = PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join("System32/shell32.dll");
    for size in [64, 256] {
        let image = extract(&shell, size).unwrap().unwrap();
        assert_eq!(image.size, [size as usize; 2]);
        assert!(image.pixels.iter().any(|pixel| pixel.a() > 0));
        assert!(image.pixels.iter().any(|pixel| pixel.a() == 0));
    }
    let root = tempfile::tempdir().unwrap();
    assert!(
        extract(&root.path().join("missing.exe"), 64)
            .unwrap()
            .is_none()
    );
    let invalid = root.path().join("无图标.exe");
    std::fs::write(&invalid, "not an executable").unwrap();
    assert!(extract(&invalid, 64).unwrap().is_none());
}

#[test]
fn mask_and_partial_alpha_do_not_create_black_boxes() {
    for (black, white, expected) in [
        ([0, 0, 0, 255], [255, 255, 255, 255], [0, 0, 0, 0]),
        ([12, 24, 40, 255], [12, 24, 40, 255], [40, 24, 12, 255]),
        ([10, 20, 30, 255], [137, 147, 157, 255], [30, 20, 10, 128]),
    ] {
        assert_eq!(
            from_backgrounds(&black, &white, 1).pixels[0].to_array(),
            expected
        );
    }
}
