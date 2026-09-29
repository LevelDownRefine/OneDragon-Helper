use super::*;
#[test]
fn escape_cancels_before_start_and_is_ignored_during_writes() {
    for active in [false, true] {
        let ctx = egui::Context::default();
        let mut dialog = BackupDialog::new(false);
        if active {
            dialog.start_request().unwrap();
        }
        for _ in 0..2 {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                assert!(dialog.show(ui.ctx(), false).is_none());
            });
            output.textures_delta.clear();
        }
        let mut input = egui::RawInput::default();
        input.events.push(egui::Event::Key {
            key: egui::Key::Escape,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: Default::default(),
        });
        let mut output = ctx.run_ui(input, |ui| {
            let result = dialog.show(ui.ctx(), false);
            assert_eq!(matches!(result, Some(BackupAction::Close)), !active);
        });
        output.textures_delta.clear();
    }
}

#[test]
fn restore_requires_confirmation_and_poll_does_not_replay_start() {
    let mut dialog = BackupDialog::new(true);
    assert!(dialog.start_request().is_err());
    dialog.path = "中文 backup.zip".into();
    assert!(dialog.start_request().is_err());
    dialog.confirmed = true;
    let request = dialog.start_request().unwrap();
    assert_eq!(request.method, "restore.start");
    assert!(dialog.active());
    dialog.started(json!({"id":"job"})).unwrap();
    assert_eq!(dialog.poll().unwrap().method, "job.poll");
    assert!(dialog.poll().is_none());
    dialog
        .receive(
            json!({"id":"job","kind":"restore","state":"failed","error":"已恢复 1 个文件，未回滚"}),
        )
        .unwrap();
    assert!(!dialog.active());
    assert!(dialog.poll().is_none());
    assert!(dialog.error.as_ref().unwrap().contains("未回滚"));
}
