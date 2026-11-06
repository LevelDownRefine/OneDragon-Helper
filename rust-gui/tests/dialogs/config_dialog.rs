use super::*;
use crate::dialogs::test_support::text_rect;
fn data() -> SettingsView {
    serde_json::from_value(json!({"startup":{"enabled":true,"delay_seconds":60},"daily_enabled":false,"shutdown_supported":false,"run_options":{"shutdown_enabled":false,"shutdown_delay":0,"mute_enabled":false,"unmute_enabled":false,"close_running_enabled":false,"rerun_enabled":false,"notify_enabled":false,"email":"","smtp_host":"","smtp_port":"","auth_code":""}})).unwrap()
}

#[test]
fn daily_list_footer_follows_content_without_empty_save() {
    let ctx = egui::Context::default();
    theme::configure(&ctx);
    let mut dialog = SettingsDialog::new(data());
    let plan = json!({"plans":[{"id":"default","name":"默认计划","plan":{"enabled":false,"target_time":"04:10","run_options":dialog.data.run_options},"state":null,"state_error":null}],"supported":true});
    dialog.set_daily(serde_json::from_value(plan).unwrap());
    let mut output = egui::FullOutput::default();
    for _ in 0..12 {
        output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, theme::SIZE)),
                ..Default::default()
            },
            |ui| {
                dialog.show(ui.ctx(), false);
            },
        );
        output.textures_delta.clear();
    }
    let row = text_rect(&output, "默认计划  每天 04:10  已停用");
    let back = text_rect(&output, "返回");
    assert!(
        back.top() - row.bottom() < 100.0,
        "footer too far below list: {row:?} {back:?}"
    );
    assert!(!output.shapes.iter().any(
        |shape| matches!(&shape.shape, egui::Shape::Text(text) if text.galley.text() == "保存")
    ));
    let modal = output
        .shapes
        .iter()
        .filter_map(|shape| match &shape.shape {
            egui::Shape::Rect(rect)
                if rect.fill == egui::Color32::from_rgb(17, 27, 42)
                    && rect.rect.contains(back.center()) =>
            {
                Some(rect.rect)
            }
            _ => None,
        })
        .min_by(|a, b| a.area().total_cmp(&b.area()))
        .expect("dialog frame");
    assert!(
        modal.bottom() - back.bottom() < 70.0,
        "footer too far above bottom: {modal:?} {back:?}"
    );
}

#[test]
fn daily_list_keeps_footer_visible_with_many_plans_on_small_screen() {
    let ctx = egui::Context::default();
    theme::configure(&ctx);
    let mut dialog = SettingsDialog::new(data());
    let plans: Vec<_> = (0..30).map(|i| json!({
        "id": format!("plan-{i}"), "name": format!("计划{i}"),
        "plan": {"enabled":false,"target_time":"04:10","run_options":dialog.data.run_options},
        "state":null, "state_error":null
    })).collect();
    dialog.set_daily(serde_json::from_value(json!({"plans":plans,"supported":true})).unwrap());
    let screen = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 480.0));
    let mut output = egui::FullOutput::default();
    for _ in 0..12 {
        output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(screen),
                ..Default::default()
            },
            |ui| {
                dialog.show(ui.ctx(), false);
            },
        );
        output.textures_delta.clear();
    }
    assert!(screen.contains_rect(text_rect(&output, "返回")));
    assert!(screen.contains_rect(text_rect(&output, "刷新")));
}

#[test]
fn daily_list_keeps_actions_visible_with_long_plan_name() {
    let ctx = egui::Context::default();
    theme::configure(&ctx);
    let mut dialog = SettingsDialog::new(data());
    let plan = json!({"plans":[{"id":"default","name":"非常长的计划名称".repeat(30),"plan":{"enabled":false,"target_time":"04:10","run_options":dialog.data.run_options},"state":null,"state_error":null}],"supported":true});
    dialog.set_daily(serde_json::from_value(plan).unwrap());
    let screen = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 480.0));
    let mut output = egui::FullOutput::default();
    for _ in 0..12 {
        output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(screen),
                ..Default::default()
            },
            |ui| {
                dialog.show(ui.ctx(), false);
            },
        );
        output.textures_delta.clear();
    }
    let back = text_rect(&output, "返回");
    let modal = output
        .shapes
        .iter()
        .filter_map(|shape| match &shape.shape {
            egui::Shape::Rect(rect)
                if rect.fill == egui::Color32::from_rgb(17, 27, 42)
                    && rect.rect.contains(back.center()) =>
            {
                Some(rect.rect)
            }
            _ => None,
        })
        .min_by(|a, b| a.area().total_cmp(&b.area()))
        .expect("dialog frame");
    for label in ["编辑", "复制", "删除"] {
        assert!(
            modal.contains_rect(text_rect(&output, label)),
            "{label} outside dialog"
        );
    }
}

fn frame(
    ctx: &egui::Context,
    dialog: &mut SettingsDialog,
    events: Vec<egui::Event>,
    busy: bool,
) -> Option<SettingsAction> {
    let mut action = None;
    let mut output = ctx.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, theme::SIZE)),
            events,
            ..Default::default()
        },
        |ui| action = dialog.show(ui.ctx(), busy),
    );
    output.textures_delta.clear();
    action
}

fn click(
    ctx: &egui::Context,
    dialog: &mut SettingsDialog,
    id: &str,
    busy: bool,
) -> Option<SettingsAction> {
    let pos = ctx
        .read_response(egui::Id::new(("settings-action", id)))
        .expect("visible settings action")
        .rect
        .center();
    frame(ctx, dialog, vec![egui::Event::PointerMoved(pos)], busy);
    assert_eq!(
        ctx.read_response(egui::Id::new(("settings-action", id)))
            .unwrap()
            .rect
            .center(),
        pos,
        "moved after hover"
    );
    frame(
        ctx,
        dialog,
        vec![
            egui::Event::PointerMoved(pos),
            egui::Event::PointerButton {
                pos,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: Default::default(),
            },
        ],
        busy,
    );
    frame(
        ctx,
        dialog,
        vec![egui::Event::PointerButton {
            pos,
            button: egui::PointerButton::Primary,
            pressed: false,
            modifiers: Default::default(),
        }],
        busy,
    )
}

#[test]
fn settings_cards_route_to_existing_actions_and_busy_blocks_them() {
    for busy in [false, true] {
        for id in [
            "run-options",
            "daily-plan",
            "备份配置",
            "恢复配置",
            "app-update",
        ] {
            let ctx = egui::Context::default();
            theme::configure(&ctx);
            let mut dialog = SettingsDialog::new(data());
            for _ in 0..12 {
                frame(&ctx, &mut dialog, vec![], busy);
            }
            let action = click(&ctx, &mut dialog, id, busy);
            if busy {
                assert!(action.is_none());
                assert!(dialog.run_draft.is_none());
                continue;
            }
            match id {
                "run-options" => {
                    assert!(action.is_none());
                    assert!(
                        dialog.run_draft.is_some(),
                        "response: {:?}",
                        ctx.read_response(egui::Id::new(("settings-action", id)))
                    );
                }
                "备份配置" => {
                    assert!(matches!(action, Some(SettingsAction::Backup(false))))
                }
                "恢复配置" => assert!(matches!(action, Some(SettingsAction::Backup(true)))),
                _ => {
                    let Some(SettingsAction::Request(request)) = action else {
                        panic!("missing request: {id}");
                    };
                    assert_eq!(
                        request.method,
                        if id == "daily-plan" {
                            "plans.list"
                        } else {
                            "update.view"
                        }
                    );
                    assert_eq!(request.params, json!({}));
                }
            }
        }
    }
}

#[test]
fn settings_card_supports_keyboard_and_failed_save_keeps_actions_disabled() {
    let ctx = egui::Context::default();
    let mut dialog = SettingsDialog::new(data());
    for _ in 0..12 {
        frame(&ctx, &mut dialog, vec![], false);
    }
    ctx.memory_mut(|memory| {
        memory.request_focus(egui::Id::new(("settings-action", "run-options")))
    });
    let action = frame(
        &ctx,
        &mut dialog,
        vec![egui::Event::Key {
            key: egui::Key::Enter,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: Default::default(),
        }],
        false,
    );
    assert!(action.is_none());
    assert!(dialog.run_draft.is_some());
    dialog.run_draft = None;
    dialog.failure("partial save".into(), true);
    for _ in 0..12 {
        frame(&ctx, &mut dialog, vec![], false);
    }
    assert!(click(&ctx, &mut dialog, "run-options", false).is_none());
    assert!(dialog.run_draft.is_none());
}

#[test]
fn daily_refresh_preserves_startup_and_cancel_keeps_saved_plan_state() {
    let mut dialog = SettingsDialog::new(data());
    dialog.data.startup.delay_seconds = 99;
    let plan = json!({"plans":[{"id":"default","name":"默认计划","plan":{"enabled":true,"target_time":"04:10","run_options":dialog.data.run_options},"state":null,"state_error":"denied"}],"supported":true});
    dialog.set_daily(serde_json::from_value(plan).unwrap());
    assert!(dialog.data.daily_enabled);
    dialog.daily_draft.as_mut().unwrap().plans[0]
        .plan
        .run_options
        .form_defaults();
    assert_eq!(
        dialog.daily_draft.as_ref().unwrap().plans[0]
            .plan
            .run_options
            .smtp_host,
        "smtp.qq.com"
    );
    assert_eq!(dialog.data.startup.delay_seconds, 99);
    dialog.daily_draft.as_mut().unwrap().plans[0].plan.enabled = false;
    let ctx = egui::Context::default();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            dialog.show(ui.ctx(), false);
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
        assert!(dialog.show(ui.ctx(), false).is_none());
    });
    output.textures_delta.clear();
    assert!(dialog.daily_draft.is_none());
    assert!(
        dialog.data.daily_enabled,
        "cancel must retain saved daily state"
    );
}

#[test]
fn nested_save_preserves_startup_draft_and_clears_credential() {
    let mut dialog = SettingsDialog::new(data());
    dialog.data.startup.delay_seconds = 99;
    dialog.run_draft = Some(dialog.data.run_options.clone());
    dialog.run_draft.as_mut().unwrap().auth_code = "secret".into();
    dialog.refresh_run(data());
    assert_eq!(dialog.data.startup.delay_seconds, 99);
    assert!(dialog.run_draft.is_none());
    assert!(dialog.data.run_options.auth_code.is_empty());
}
