use eframe::egui::{self, Pos2, Rect, Vec2};

pub(super) fn frame<T>(
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

pub(super) fn text_rect(output: &egui::FullOutput, label: &str) -> Rect {
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

pub(super) fn click(pos: Pos2, pressed: bool) -> Vec<egui::Event> {
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
