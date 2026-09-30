use super::*;
use crate::dialogs::test_support::{click, frame, text_rect};
use crate::theme::SIZE;
use eframe::egui::{Pos2, Rect, vec2};

fn editor() -> ScriptEditor {
    ScriptEditor::new(serde_json::from_value(json!({
        "script_name": "demo", "script": {"display_name": "示例", "script_path": "demo.exe"},
        "weekly_timeouts": [60,60,60,60,60,60,60], "switches": [{"name": "任务", "enabled": true}],
    })).unwrap())
}

#[test]
fn form_preserves_null_timeouts_and_boolean_switches() {
    let mut editor = editor();
    editor.data.script.game_command =
        " \"D:/Game Folder/game.exe\" --profile \"中文 空格\" ".into();
    editor.timeouts[0].clear();
    editor.timeouts[6] = "86400".into();
    let request = editor.request().unwrap();
    assert_eq!(request.method, "script.edit_save");
    assert_eq!(
        request.params["config_patch"]["game_command"],
        "\"D:/Game Folder/game.exe\" --profile \"中文 空格\""
    );
    assert_eq!(
        request.params["weekly_timeouts"],
        json!([null, 60, 60, 60, 60, 60, 86400])
    );
    assert_eq!(request.params["switches"]["任务"], true);
    assert_eq!(request.params["config_patch"]["block"], true);
    editor.timeouts[0] = "86401".into();
    assert!(editor.request().is_err());
    editor.timeouts[0] = "1.5".into();
    assert!(editor.request().is_err());
}

#[test]
fn escape_cancels_without_emitting_save() {
    let ctx = egui::Context::default();
    let mut editor = editor();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            assert!(editor.show(ui.ctx(), false).is_none());
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
            cancelled = matches!(editor.show(ui.ctx(), false), Some(EditAction::Cancel));
        },
    );
    output.textures_delta.clear();
    assert!(cancelled);
}

#[test]
fn long_script_form_keeps_save_visible_and_blocks_duplicate_writes() {
    use serde_json::json;
    for size in [SIZE, vec2(1000.0, 600.0)] {
        for (busy, reload) in [(false, false), (true, false), (false, true)] {
            let ctx = egui::Context::default();
            let mut editor = ScriptEditor::new(serde_json::from_value(json!({
                "script_name": "demo",
                "script": {"display_name": "long title ".repeat(60), "script_path": "demo.exe"},
                "weekly_timeouts": [60,60,60,60,60,60,60],
                "switches": (0..100).map(|i| json!({"name":format!("Task {i}"),"enabled":true})).collect::<Vec<_>>()
            })).unwrap());
            if reload {
                editor.failure("read before saving ".repeat(100), true);
            }
            for _ in 0..12 {
                assert!(
                    frame(&ctx, size, vec![], |ctx| editor.show(ctx, busy))
                        .0
                        .is_none()
                );
            }
            let (_, output) = frame(&ctx, size, vec![], |ctx| editor.show(ctx, busy));
            let rect = ctx
                .memory(|m| m.area_rect(egui::Id::new("script-editor")))
                .unwrap();
            assert!(
                Rect::from_min_size(Pos2::ZERO, size).contains_rect(rect),
                "{rect:?}"
            );
            let pos = text_rect(&output, "保存").center();
            assert!(
                frame(&ctx, size, click(pos, true), |ctx| editor.show(ctx, busy))
                    .0
                    .is_none()
            );
            let (action, _) = frame(&ctx, size, click(pos, false), |ctx| editor.show(ctx, busy));
            if busy || reload {
                assert!(action.is_none());
            } else {
                let Some(EditAction::Save(request)) = action else {
                    panic!("expected save");
                };
                assert_eq!(request.method, "script.edit_save");
                assert_eq!(request.params["switches"].as_object().unwrap().len(), 100);
                assert_eq!(request.params["config_patch"]["script_type"], "external");
            }
            let pos = text_rect(&output, "刷新").center();
            assert!(
                frame(&ctx, size, click(pos, true), |ctx| editor.show(ctx, busy))
                    .0
                    .is_none()
            );
            let (action, _) = frame(&ctx, size, click(pos, false), |ctx| editor.show(ctx, busy));
            if busy {
                assert!(action.is_none());
            } else {
                assert!(matches!(action, Some(EditAction::Reload)));
            }
        }
    }
}
