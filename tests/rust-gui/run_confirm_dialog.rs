use super::*;
fn dialog() -> RunDialog {
    RunDialog::new(serde_json::from_value(json!({
        "script_names":["demo"],"invalid":[{"name":"demo","reason":"missing"}],"shutdown_supported":false,
        "options":{"shutdown_enabled":false,"shutdown_delay":60,"mute_enabled":false,"unmute_enabled":false,"close_running_enabled":true,"rerun_enabled":false,"notify_enabled":false,"email":"","smtp_host":"","smtp_port":"","auth_code":""}
    })).unwrap())
}
#[test]
fn confirmation_blocks_invalid_scripts_and_unavailable_shutdown() {
    let mut dialog = dialog();
    assert!(dialog.request().is_err());
    dialog.confirm_invalid = true;
    let request = dialog.request().unwrap();
    assert_eq!(request.method, "run.prepare");
    assert_eq!(request.params["confirm_invalid"], true);
    assert_eq!(request.params["options"]["smtp_port"], "465");
    dialog.data.options.shutdown_enabled = true;
    assert!(dialog.request().is_err());
}
#[test]
fn escape_cancels_without_saving_or_starting() {
    let ctx = egui::Context::default();
    let mut dialog = dialog();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            assert!(dialog.show(ui.ctx(), false).is_none());
        });
        output.textures_delta.clear();
    }
    let mut cancelled = false;
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
            cancelled = matches!(dialog.show(ui.ctx(), false), Some(RunAction::Cancel));
        },
    );
    output.textures_delta.clear();
    assert!(cancelled);
}
