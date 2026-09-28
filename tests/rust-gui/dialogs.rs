use super::*;
use eframe::egui::{Pos2, Rect, Vec2};

fn editor() -> ScriptEditor {
    ScriptEditor::new(serde_json::from_value(json!({
        "script_name": "demo", "script": {"display_name": "示例", "script_path": "demo.exe"},
        "weekly_timeouts": [60,60,60,60,60,60,60], "switches": [{"name": "任务", "enabled": true}],
    })).unwrap())
}

#[test]
fn form_preserves_null_timeouts_and_boolean_switches() {
    let mut editor = editor();
    editor.timeouts[0].clear();
    editor.timeouts[6] = "86400".into();
    let request = editor.request().unwrap();
    assert_eq!(request.method, "script.edit_save");
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

fn frame<T>(
    ctx: &egui::Context,
    size: Vec2,
    events: Vec<egui::Event>,
    show: impl FnOnce(&egui::Context) -> T,
) -> (T, egui::FullOutput) {
    let mut result = None;
    let mut show = Some(show);
    let mut output = ctx.run_ui(
        egui::RawInput {
            screen_rect: Some(Rect::from_min_size(Pos2::ZERO, size)),
            events,
            ..Default::default()
        },
        |ui| result = Some(show.take().expect("single pass")(ui.ctx())),
    );
    output.textures_delta.clear();
    (result.unwrap(), output)
}

fn text_rect(output: &egui::FullOutput, label: &str) -> Rect {
    output
        .shapes
        .iter()
        .find_map(|shape| {
            if let egui::Shape::Text(text) = &shape.shape
                && text.galley.text() == label
            {
                let rect = Rect::from_min_size(text.pos, text.galley.size());
                assert!(shape.clip_rect.contains_rect(rect), "{label} is clipped");
                Some(rect)
            } else {
                None
            }
        })
        .unwrap_or_else(|| panic!("missing visible label: {label}"))
}

fn click(pos: Pos2, pressed: bool) -> Vec<egui::Event> {
    vec![
        egui::Event::PointerMoved(pos),
        egui::Event::PointerButton {
            pos,
            button: egui::PointerButton::Primary,
            pressed,
            modifiers: Default::default(),
        },
    ]
}

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

#[test]
fn long_script_form_keeps_save_visible_and_blocks_duplicate_writes() {
    use crate::dialogs::{EditAction, ScriptEditor};
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
