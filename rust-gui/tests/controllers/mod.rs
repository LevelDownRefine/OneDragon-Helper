use super::*;

pub(super) struct Scene {
    pub(super) ctx: egui::Context,
    pub(super) ui: View,
    pub(super) view: ScriptView,
    pub(super) scripts: Vec<Script>,
    pub(super) time: f64,
    pub(super) editing_blocked: bool,
    pub(super) output: egui::FullOutput,
    pub(super) screen_size: Vec2,
    pub(super) pixels_per_point: f32,
}

impl Scene {
    pub(super) fn new() -> Self {
        let ctx = egui::Context::default();
        crate::theme::configure(&ctx);
        let ui = View::new(&ctx);
        let view: ScriptView = serde_json::from_value(json!({
            "script": {"script_name": "test", "display_name": "演示", "script_path": "test.exe", "adapted": true},
            "dailies": [{"name": "每日任务", "enabled": true,
                "task": "材料", "sequence": 1,
                "options": {"values": [
                    {"display_name": "材料", "physical_name": "material", "options": {"values":
                        (1..=40).map(|i| json!({"display_name": format!("副本 {i}"), "physical_name": i})).collect::<Vec<_>>() }},
                    {"display_name": "布尔", "physical_name": "boolean", "options": {"values": [
                        {"display_name": "开启", "physical_name": true}, {"display_name": "关闭", "physical_name": false}]}},
                    {"display_name": "单项", "physical_name": "single"}
                ]}}
            ],
            "weeklies": [{"name": "周常", "options": null, "task": null, "start_day": null}]
        })).unwrap();
        let scripts = vec![view.script.clone()];
        let mut scene = Self {
            ctx,
            ui,
            view,
            scripts,
            time: 0.0,
            editing_blocked: false,
            output: Default::default(),
            screen_size: SIZE,
            pixels_per_point: 1.0,
        };
        scene.frame(vec![]);
        scene.frame(vec![]);
        scene
    }

    pub(super) fn frame(&mut self, events: Vec<egui::Event>) -> Vec<Action> {
        self.time += 0.1;
        let mut input = egui::RawInput {
            screen_rect: Some(Rect::from_min_size(egui::Pos2::ZERO, self.screen_size)),
            time: Some(self.time),
            events,
            ..Default::default()
        };
        input
            .viewports
            .get_mut(&egui::ViewportId::ROOT)
            .unwrap()
            .native_pixels_per_point = Some(self.pixels_per_point);
        let mut actions = Vec::new();
        let mut output = self.ctx.run_ui(input, |ui| {
            actions.extend(self.ui.show(
                ui,
                Presentation {
                    scripts: &self.scripts,
                    selected: Some("test"),
                    view: Some(&self.view),
                    editing_blocked: self.editing_blocked,
                    block_close: false,
                    status: "已同步",
                    demo: true,
                },
            ))
        });
        // The input-only harness does not upload textures to a GPU.
        output.textures_delta.clear();
        self.output = output;
        actions
    }

    pub(super) fn click(&mut self, id: Id) -> Vec<Action> {
        let pos = self
            .ctx
            .read_response(id)
            .expect("visible control")
            .rect
            .center();
        self.frame(vec![
            egui::Event::PointerMoved(pos),
            egui::Event::PointerButton {
                pos,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: Default::default(),
            },
        ]);
        self.frame(vec![egui::Event::PointerButton {
            pos,
            button: egui::PointerButton::Primary,
            pressed: false,
            modifiers: Default::default(),
        }])
    }

    pub(super) fn daily(&mut self, parent: usize) {
        assert!(self.click(Id::new(("daily", "每日任务"))).is_empty());
        self.frame(vec![]);
        let pos = self
            .ctx
            .read_response(Id::new(("primary", parent)))
            .unwrap()
            .rect
            .center();
        self.frame(vec![egui::Event::PointerMoved(pos)]);
        self.frame(vec![]);
        assert_eq!(
            self.ui.menu.as_ref().unwrap().parent,
            Some(parent),
            "pointer {pos:?}, response {:?}, layer {:?}",
            self.ctx.read_response(Id::new(("primary", parent))),
            self.ctx.layer_id_at(pos),
        );
    }
}

pub(super) fn only_request(actions: Vec<Action>) -> Request {
    assert_eq!(actions.len(), 1, "one click must emit one action");
    match actions.into_iter().next().unwrap() {
        Action::Request(request) => request,
        _ => panic!("expected backend request"),
    }
}
