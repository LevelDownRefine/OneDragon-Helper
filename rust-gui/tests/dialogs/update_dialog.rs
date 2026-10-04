use super::*;

fn dialog() -> UpdateDialog {
    UpdateDialog::new(
        serde_json::from_value(json!({
            "version":"1.0.0","unavailable_reason":"","previous_result":null,
            "releases_url":"https://github.com/LevelDownRefine/OneDragon-Helper/releases",
            "release":{"version":"2.0.0","notes":"notes","size":100},
            "prepared_version":null,"handoff_ready":false
        }))
        .unwrap(),
    )
}

#[test]
fn cancellation_waits_for_terminal_state_and_rejects_stale_job() {
    let mut dialog = dialog();
    assert_eq!(dialog.start("update.download").method, "update.download");
    assert!(dialog.active());
    dialog
        .started("update.download", json!({"id":"job"}))
        .unwrap();
    assert!(
        dialog
            .receive(json!({"id":"old","kind":"update.download","state":"running"}))
            .is_err()
    );
    assert!(!dialog.receive(json!({"id":"job","kind":"update.download","state":"running","progress":{"received":7,"total":10}})).unwrap());
    assert_eq!(dialog.progress, Some((7, 10)));
    assert!(dialog.close().is_none());
    let cancel = dialog.poll().expect("expected queued cancel");
    assert_eq!(cancel.method, "job.cancel");
    assert_eq!(cancel.params, json!({"job_id":"job"}));
    assert!(dialog.close().is_none());
    assert!(dialog.active());
    assert!(
        dialog
            .receive(json!({"id":"job","kind":"update.download","state":"cancelled"}))
            .unwrap()
    );
    assert!(!dialog.active());
    assert!(dialog.poll().is_none());
}

#[test]
fn cancellation_before_job_id_is_sent_once_then_keeps_polling() {
    let mut dialog = dialog();
    dialog.start("update.check");
    assert!(dialog.close().is_none());
    assert!(dialog.close_pending);
    assert!(dialog.poll().is_none());
    dialog.started("update.check", json!({"id":"job"})).unwrap();
    assert_eq!(dialog.poll().unwrap().method, "job.cancel");
    assert_eq!(dialog.poll().unwrap().method, "job.poll");
    assert!(
        !dialog
            .receive(json!({"id":"job","kind":"update.check","state":"running"}))
            .unwrap()
    );
    assert!(dialog.close().is_none());
    dialog.next_poll = Instant::now();
    assert_eq!(dialog.poll().unwrap().method, "job.poll");
    assert!(dialog.receive(json!({"id":"job","kind":"update.check","state":"succeeded","result":{"release":null}})).unwrap());
    assert!(dialog.poll().is_none());
}

#[test]
fn cancel_button_stays_enabled_during_polls_and_queues_busy_click() {
    use crate::dialogs::test_support::{click, frame, text_rect};
    let ctx = egui::Context::default();
    let mut dialog = dialog();
    dialog.start("update.download");
    dialog
        .started("update.download", json!({"id":"job"}))
        .unwrap();
    for _ in 0..12 {
        frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
            dialog.show(ctx, false, false)
        });
    }
    let mut idle_color = None;
    for busy in [false, true, false, true] {
        let (_, output) = frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
            dialog.show(ctx, busy, false)
        });
        let text = output
            .shapes
            .iter()
            .find_map(|shape| match &shape.shape {
                egui::Shape::Text(text) if text.galley.text() == "取消更新" => Some(text),
                _ => None,
            })
            .unwrap();
        let color = text.galley.job.sections[0].format.color;
        assert_eq!(*idle_color.get_or_insert(color), color);
    }
    let (_, output) = frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
        dialog.show(ctx, true, false)
    });
    let pos = text_rect(&output, "取消更新").center();
    frame(&ctx, crate::theme::SIZE, click(pos, true), |ctx| {
        dialog.show(ctx, true, false)
    });
    let (action, _) = frame(&ctx, crate::theme::SIZE, click(pos, false), |ctx| {
        dialog.show(ctx, true, false)
    });
    assert!(
        action.is_none(),
        "busy click must not send a concurrent request"
    );
    assert!(dialog.close_pending);
    assert_eq!(dialog.poll().unwrap().method, "job.cancel");
    assert_eq!(dialog.poll().unwrap().method, "job.poll");
}

#[test]
fn escape_queues_cancellation_during_request_but_not_native_operation() {
    use crate::dialogs::test_support::frame;
    let ctx = egui::Context::default();
    let mut dialog = dialog();
    dialog.start("update.check");
    for _ in 0..12 {
        frame(&ctx, crate::theme::SIZE, vec![], |ctx| {
            dialog.show(ctx, true, true)
        });
    }
    for local_operation_active in [true, false] {
        let (action, _) = frame(
            &ctx,
            crate::theme::SIZE,
            vec![egui::Event::Key {
                key: egui::Key::Escape,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: Default::default(),
            }],
            |ctx| dialog.show(ctx, true, local_operation_active),
        );
        assert!(action.is_none());
        assert_eq!(dialog.close_pending, !local_operation_active);
    }
    assert!(dialog.poll().is_none());
    dialog.started("update.check", json!({"id":"job"})).unwrap();
    assert_eq!(dialog.poll().unwrap().method, "job.cancel");
}

#[test]
fn download_failure_keeps_release_without_automatic_retry() {
    let mut dialog = dialog();
    dialog.start("update.download");
    dialog
        .started("update.download", json!({"id":"job"}))
        .unwrap();
    assert!(
        !dialog
            .receive(
                json!({"id":"job","kind":"update.download","state":"failed","error":"网络中断"})
            )
            .unwrap()
    );
    assert_eq!(dialog.error.as_deref(), Some("网络中断"));
    assert!(dialog.data.release.is_some());
    assert!(!dialog.active());
    assert!(dialog.poll().is_none());
    dialog.failure("连接中断".into(), true);
    assert!(dialog.needs_reload);
    assert!(matches!(dialog.close(), Some(UpdateAction::Close)));
}

#[test]
fn install_waits_for_matching_ready_and_cannot_be_cancelled() {
    let mut dialog = dialog();
    dialog.data.prepared_version = Some("2.0.0".into());
    let request = dialog.start("update.install");
    assert_eq!(request.params, json!({}));
    assert!(dialog.close().is_none());
    dialog
        .started("update.install", json!({"id":"install"}))
        .unwrap();
    assert!(dialog.close().is_none());
    assert!(!dialog.ready());
    for result in [
        json!({"ready":false,"version":"2.0.0"}),
        json!({"ready":true,"version":"other"}),
    ] {
        assert!(dialog.receive(json!({"id":"install","kind":"update.install","state":"succeeded","result":result})).is_err());
        assert!(!dialog.ready());
    }
    assert!(!dialog.receive(json!({"id":"install","kind":"update.install","state":"succeeded","result":{"ready":true,"version":"2.0.0"}})).unwrap());
    assert!(dialog.ready());
    assert!(!dialog.active());
    assert!(dialog.poll().is_none());
    assert!(dialog.close().is_none());
}

#[test]
fn failed_install_keeps_prepared_version_and_does_not_exit_or_retry() {
    let mut dialog = dialog();
    dialog.data.prepared_version = Some("2.0.0".into());
    dialog.start("update.install");
    dialog
        .started("update.install", json!({"id":"install"}))
        .unwrap();
    assert!(
        !dialog
            .receive(
                json!({"id":"install","kind":"update.install","state":"failed","error":"仍有任务"})
            )
            .unwrap()
    );
    assert!(!dialog.ready());
    assert!(!dialog.active());
    assert_eq!(dialog.data.prepared_version.as_deref(), Some("2.0.0"));
    assert!(dialog.poll().is_none());
    assert_eq!(dialog.start("update.install").method, "update.install");
    dialog.failure("连接中断".into(), true);
    assert!(!dialog.ready());
    assert!(dialog.needs_reload);
}

#[test]
fn escape_closes_idle_dialog_without_check_or_download() {
    let ctx = egui::Context::default();
    let mut dialog = dialog();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            assert!(dialog.show(ui.ctx(), false, false).is_none());
        });
        output.textures_delta.clear();
    }
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
            assert!(matches!(
                dialog.show(ui.ctx(), false, false),
                Some(UpdateAction::Close)
            ));
        },
    );
    output.textures_delta.clear();
    assert!(!dialog.active());
}
