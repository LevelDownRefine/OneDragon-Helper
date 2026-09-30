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
    assert!(dialog.close().is_none());
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
    let Some(UpdateAction::Request(cancel)) = dialog.close() else {
        panic!("expected cancel");
    };
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
            assert!(dialog.show(ui.ctx(), false).is_none());
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
                dialog.show(ui.ctx(), false),
                Some(UpdateAction::Close)
            ));
        },
    );
    output.textures_delta.clear();
    assert!(!dialog.active());
}
