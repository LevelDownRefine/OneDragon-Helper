use super::*;
use serde_json::json;
fn data() -> SettingsView {
    serde_json::from_value(json!({"startup":{"enabled":true,"delay_seconds":60},"daily_enabled":false,"shutdown_supported":false,"run_options":{"shutdown_enabled":false,"shutdown_delay":0,"mute_enabled":false,"unmute_enabled":false,"close_running_enabled":false,"rerun_enabled":false,"notify_enabled":false,"email":"","smtp_host":"","smtp_port":"","auth_code":""}})).unwrap()
}
#[test]
fn startup_disabled_for_daily_plan_and_escape_cancels() {
    let mut data = data();
    data.daily_enabled = true;
    assert!(StartupDialog::from_settings(&data).is_none());
    data.daily_enabled = false;
    let mut dialog = StartupDialog::from_settings(&data).unwrap();
    let ctx = egui::Context::default();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            assert!(dialog.show(ui.ctx()).is_none());
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
    let mut output = ctx.run_ui(input, |ui| assert_eq!(dialog.show(ui.ctx()), Some(false)));
    output.textures_delta.clear();
}
