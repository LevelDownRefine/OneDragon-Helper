use super::*;

fn paths(root: &std::path::Path) -> Vec<PathBuf> {
    ["一.EXE", "two.bat", "three.py"]
        .map(|name| {
            let path = root.join(name);
            std::fs::write(&path, "never execute").unwrap();
            path
        })
        .into()
}

#[test]
fn escape_waits_for_import_then_closes_results() {
    let root = tempfile::tempdir().unwrap();
    let mut dialog = DropDialog::new(paths(root.path())).unwrap();
    let ctx = egui::Context::default();
    for finished in [false, true] {
        if finished {
            while dialog.next().is_some() {
                dialog.receive(Ok(json!({"script_name":"saved"})));
            }
        }
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(!dialog.show(ui.ctx(), false));
            });
            output.textures_delta.clear();
        }
        let mut output = ctx.run_ui(
            egui::RawInput {
                events: vec![egui::Event::Key {
                    key: egui::Key::Escape,
                    physical_key: None,
                    pressed: true,
                    repeat: false,
                    modifiers: Default::default(),
                }],
                ..Default::default()
            },
            |ui| {
                assert_eq!(dialog.show(ui.ctx(), false), finished);
            },
        );
        output.textures_delta.clear();
    }
}

#[test]
fn rejects_mixed_drop_before_start_and_preserves_files() {
    let root = tempfile::tempdir().unwrap();
    let mut paths = paths(root.path());
    paths.push(root.path().join("missing.exe"));
    assert!(DropDialog::new(paths.clone()).is_err());
    paths.pop();
    paths.push(root.path().to_path_buf());
    assert!(DropDialog::new(paths).is_err());
    assert_eq!(
        std::fs::read_to_string(root.path().join("一.EXE")).unwrap(),
        "never execute"
    );
}

#[test]
fn serial_import_counts_failures_and_stops_unknown_writes() {
    let root = tempfile::tempdir().unwrap();
    let mut dialog = DropDialog::new(paths(root.path())).unwrap();
    assert_eq!(dialog.next().unwrap().method, "script.add");
    assert!(dialog.next().is_none());
    assert!(!dialog.receive(Ok(json!({"script_name":"first"}))));
    dialog.next().unwrap();
    dialog.receive(Err(Failure {
        code: "invalid_params".into(),
        message: "invalid shortcut".into(),
        refresh_required: false,
    }));
    dialog.next().unwrap();
    dialog.receive(Ok(json!({"script_name":"third"})));
    assert!(!dialog.active());
    assert_eq!((dialog.added, dialog.failed), (2, 1));
    for failure in [
        Failure::transport("lost"),
        Failure {
            code: "operation_failed".into(),
            message: "init failed".into(),
            refresh_required: true,
        },
    ] {
        let mut dialog = DropDialog::new(paths(root.path())).unwrap();
        dialog.next().unwrap();
        dialog.receive(Err(failure));
        assert!(!dialog.active());
        assert!(dialog.next().is_none(), "must not replay unknown writes");
        assert_eq!((dialog.failed, dialog.stopped), (1, 2));
    }
}

#[test]
fn repeated_paths_are_imported_as_separate_entries() {
    let root = tempfile::tempdir().unwrap();
    let path = paths(root.path())[0].clone();
    let mut dialog = DropDialog::new(vec![path.clone(), path.clone()]).unwrap();
    for name in ["一", "一_2"] {
        let request = dialog.next().unwrap();
        assert_eq!(request.method, "script.add");
        assert_eq!(request.params, json!({"file_path": path.to_str().unwrap()}));
        assert!(!dialog.receive(Ok(json!({"script_name": name}))));
    }
    assert!(!dialog.active());
    assert_eq!((dialog.added, dialog.failed, dialog.stopped), (2, 0, 0));
    assert_eq!(dialog.results[0].1, "已添加：一");
    assert_eq!(dialog.results[1].1, "已添加：一_2");
}
