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
    editor.data.script.game_arguments = " --profile \"中文 空格\" ".into();
    editor.timeouts[0].clear();
    editor.timeouts[6] = "86400".into();
    let request = editor.request().unwrap();
    assert_eq!(request.method, "script.edit_save");
    assert_eq!(
        request.params["config_patch"]["game_arguments"],
        "--profile \"中文 空格\""
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
fn task_options_preserve_types_and_submit_only_changes() {
    let mut editor = ScriptEditor::new(serde_json::from_value(json!({
        "script_name": "demo", "script": {"display_name": "示例", "script_path": "demo.exe"},
        "weekly_timeouts": [60,60,60,60,60,60,60], "switches": [],
        "task_options": [
            {"id":"flag", "group":"领奖", "display_name":"邮件", "type":"bool", "value":true, "choices":[]},
            {"id":"mode", "group":"喷泉", "display_name":"方式", "type":"choice", "value":"coin", "choices":[{"display_name":"捞币", "physical_name":"coin"}]},
            {"id":"targets", "group":"梦魇", "display_name":"目标", "type":"multi", "value":["b","a"], "choices":[]}
        ]
    })).unwrap());
    assert_eq!(editor.request().unwrap().params["task_options"], json!({}));
    editor.data.task_options[2].value = OptionValue::Multi(vec!["a".into(), "b".into()]);
    assert_eq!(editor.request().unwrap().params["task_options"], json!({}));
    editor.data.task_options[0].value = OptionValue::Bool(false);
    editor.data.task_options[2].value = OptionValue::Multi(vec!["a".into()]);
    assert_eq!(
        editor.request().unwrap().params["task_options"],
        json!({"flag":false,"targets":["a"]})
    );
}

#[test]
fn task_option_response_rejects_wrong_type() {
    assert!(serde_json::from_value::<TaskOption>(json!({
        "id":"flag", "group":"领奖", "display_name":"邮件", "type":"bool", "value":1, "choices":[]
    })).is_err());
}

#[test]
fn tasks_stack_in_order_and_save_clicked_state() {
    let ctx = egui::Context::default();
    let mut editor = editor();
    editor.data.switches = (0..3)
        .map(|index| TaskSwitch {
            name: format!("Task {index}"),
            enabled: index != 1,
        })
        .collect();
    for _ in 0..12 {
        frame(&ctx, vec2(1000.0, 1600.0), vec![], |ctx| {
            egui::Area::new(egui::Id::new("switch-test")).show(ctx, |ui| editor.fields_ui(ui))
        });
    }
    let (_, output) = frame(&ctx, vec2(1000.0, 1600.0), vec![], |ctx| {
        egui::Area::new(egui::Id::new("switch-test")).show(ctx, |ui| editor.fields_ui(ui))
    });
    let first = text_rect(&output, "Task 0");
    let second = text_rect(&output, "Task 1");
    let third = text_rect(&output, "Task 2");
    assert!(second.top() > first.bottom());
    assert!((second.left() - first.left()).abs() < 1.0);
    assert!((first.left() - third.left()).abs() < 1.0);
    assert!(third.top() > first.bottom());
    frame(
        &ctx,
        vec2(1000.0, 1600.0),
        click(second.center(), true),
        |ctx| egui::Area::new(egui::Id::new("switch-test")).show(ctx, |ui| editor.fields_ui(ui)),
    );
    frame(
        &ctx,
        vec2(1000.0, 1600.0),
        click(second.center(), false),
        |ctx| egui::Area::new(egui::Id::new("switch-test")).show(ctx, |ui| editor.fields_ui(ui)),
    );
    assert_eq!(
        editor.request().unwrap().params["switches"],
        json!({"Task 0": true, "Task 1": true, "Task 2": true})
    );
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

#[test]
fn task_groups_attach_options_without_creating_switches() {
    let mut editor = editor();
    editor.data.task_options = serde_json::from_value(json!([
        {"id":"child", "group":"奖励", "tasks":["任务"], "display_name":"邮件", "type":"bool", "value":false, "choices":[]},
        {"id":"orphan", "group":"整理", "tasks":[], "display_name":"存放", "type":"bool", "value":true, "choices":[]}
    ])).unwrap();
    let groups = task_groups(&editor.data);
    assert_eq!(groups.len(), 2);
    assert_eq!(groups[0].switches, vec![0]);
    assert_eq!(groups[0].options, vec![0]);
    assert!(groups[1].switches.is_empty());
    assert_eq!(groups[1].options, vec![1]);
}

#[test]
fn task_settings_expand_and_preserve_changed_child_value() {
    let ctx = egui::Context::default();
    let mut editor = editor();
    editor.data.task_options = serde_json::from_value(json!([
        {"id":"child", "group":"任务", "display_name":"Child flag", "type":"bool", "value":false, "choices":[]}
    ])).unwrap();
    for _ in 0..12 {
        frame(&ctx, vec2(1000.0, 1600.0), vec![], |ctx| {
            egui::Area::new(egui::Id::new("settings-test")).show(ctx, |ui| editor.fields_ui(ui))
        });
    }
    let (_, output) = frame(&ctx, vec2(1000.0, 1600.0), vec![], |ctx| {
        egui::Area::new(egui::Id::new("settings-test")).show(ctx, |ui| editor.fields_ui(ui))
    });
    assert!(!output.shapes.iter().any(|shape| matches!(&shape.shape, egui::Shape::Text(text) if text.galley.text() == "Child flag")));
    let button = text_rect(&output, "设置").center();
    for pressed in [true, false] {
        frame(&ctx, vec2(1000.0, 1600.0), click(button, pressed), |ctx| {
            egui::Area::new(egui::Id::new("settings-test")).show(ctx, |ui| editor.fields_ui(ui))
        });
    }
    let (_, output) = frame(&ctx, vec2(1000.0, 1600.0), vec![], |ctx| {
        egui::Area::new(egui::Id::new("settings-test")).show(ctx, |ui| editor.fields_ui(ui))
    });
    let child = text_rect(&output, "Child flag").center();
    for pressed in [true, false] {
        frame(&ctx, vec2(1000.0, 1600.0), click(child, pressed), |ctx| {
            egui::Area::new(egui::Id::new("settings-test")).show(ctx, |ui| editor.fields_ui(ui))
        });
    }
    assert_eq!(
        editor.request().unwrap().params["task_options"]["child"],
        true
    );
}
