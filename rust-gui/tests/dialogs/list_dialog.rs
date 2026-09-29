use super::*;
use crate::dialogs::test_support::{click, frame, text_rect};

#[test]
fn delete_confirmation_is_explicit_and_blocks_busy_or_stale_actions() {
    for (busy, stale) in [(false, false), (true, false), (false, true)] {
        let ctx = egui::Context::default();
        let mut dialog = ListDialog::remove("script-id".into(), "示例脚本".into());
        if stale {
            dialog.failure("写入结果未知".into(), true);
        }
        for _ in 0..2 {
            frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
                dialog.show(ctx, busy)
            });
        }
        let (action, output) = frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
            dialog.show(ctx, busy)
        });
        assert!(action.is_none());
        text_rect(&output, "示例脚本");
        text_rect(&output, "script-id");
        text_rect(&output, "将删除助手中的脚本条目及每周设置。");
        text_rect(&output, "脚本文件保留在原位置，可以重新添加。");
        let position = text_rect(&output, "确认删除脚本").center();
        frame(&ctx, crate::theme::SIZE, click(position, true), |ctx| {
            dialog.show(ctx, busy)
        });
        let (action, _) = frame(&ctx, crate::theme::SIZE, click(position, false), |ctx| {
            dialog.show(ctx, busy)
        });
        if busy || stale {
            assert!(action.is_none());
        } else {
            let Some(ListAction::Request(request)) = action else {
                panic!("confirmed delete");
            };
            assert_eq!(request.method, "script.remove");
            assert_eq!(request.params, json!({"script_name":"script-id"}));
        }
    }
}

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
