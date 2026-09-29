use super::*;
use crate::dialogs::test_support::{click, frame, text_rect};
use crate::theme::SIZE;

#[test]
fn shared_close_button_respects_write_lock() {
    for closable in [true, false] {
        let ctx = egui::Context::default();
        let show = |ctx: &egui::Context| {
            Dialog::new("test-dialog", "Settings").show(ctx, closable, |ui| {
                ui.label("Body");
            })
        };
        for _ in 0..12 {
            assert!(!frame(&ctx, SIZE, vec![], show).0);
        }
        let (_, output) = frame(&ctx, SIZE, vec![], show);
        let pos = text_rect(&output, "×").center();
        assert!(!frame(&ctx, SIZE, click(pos, true), show).0);
        assert_eq!(frame(&ctx, SIZE, click(pos, false), show).0, closable);
    }
}
