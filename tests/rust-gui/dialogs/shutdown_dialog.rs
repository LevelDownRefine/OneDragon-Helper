use super::*;

#[test]
fn countdown_starts_when_shown_and_cancellation_wins_at_zero() {
    let ctx = egui::Context::default();
    for cancel in [false, true] {
        let mut countdown = Countdown {
            seconds: 2,
            started: None,
            decision: None,
        };
        let now = Instant::now();
        for (elapsed, expected) in [(0, None), (1, None), (2, Some(!cancel)), (3, Some(!cancel))] {
            let mut output = ctx.run_ui(Default::default(), |ui| {
                countdown.show(
                    ui,
                    now + Duration::from_secs(elapsed),
                    cancel && elapsed == 2,
                )
            });
            output.textures_delta.clear();
            assert_eq!(countdown.decision, expected);
        }
    }
}

#[test]
fn escape_cancels_and_invalid_arguments_never_open_a_window() {
    let ctx = egui::Context::default();
    let mut countdown = Countdown {
        seconds: 1,
        started: None,
        decision: None,
    };
    let mut input = egui::RawInput::default();
    input.events.push(egui::Event::Key {
        key: egui::Key::Escape,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: Default::default(),
    });
    let mut output = ctx.run_ui(input, |ui| countdown.show(ui, Instant::now(), false));
    output.textures_delta.clear();
    assert_eq!(countdown.decision, Some(false));
    for value in ["0", "-1", "86401", "x"] {
        assert!(run(vec![value.into()]).is_err());
    }
    assert!(run(vec!["1".into(), "--unknown".into()]).is_err());
}
