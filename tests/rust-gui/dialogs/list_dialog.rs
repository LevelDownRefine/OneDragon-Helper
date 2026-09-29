use super::*;

#[test]
fn escape_cancels_add_and_delete_without_a_request() {
    for mut dialog in [
        ListDialog::add(),
        ListDialog::remove("script".into(), "示例".into()),
    ] {
        let ctx = egui::Context::default();
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
                cancelled = matches!(dialog.show(ui.ctx(), false), Some(ListAction::Cancel));
            },
        );
        output.textures_delta.clear();
        assert!(cancelled);
    }
}
