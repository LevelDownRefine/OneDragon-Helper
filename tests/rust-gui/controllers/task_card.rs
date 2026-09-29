use super::*;

use super::super::tests::{Scene, only_request};

fn assert_popup_attached(scene: &Scene) -> Rect {
    let area = egui::AreaState::load(&scene.ctx, Id::new("task-popup"))
        .unwrap()
        .rect();
    let popup = scene
        .output
        .shapes
        .iter()
        .find_map(|shape| {
            if let egui::Shape::Rect(rect) = &shape.shape
                && rect.rect.min.distance(area.min) <= 1.0
                && rect.stroke.width == 1.0
            {
                Some(rect.rect)
            } else {
                None
            }
        })
        .expect("painted popup frame");
    let anchor = scene.ui.menu.as_ref().unwrap().anchor;
    assert!(Rect::from_min_size(egui::Pos2::ZERO, scene.screen_size).contains_rect(popup));
    assert!(
        (popup.bottom() + 4.0 - anchor.top()).abs() <= 1.0
            || (popup.top() - 4.0 - anchor.bottom()).abs() <= 1.0,
        "popup {popup:?} is detached from anchor {anchor:?}",
    );
    popup
}

#[test]
fn short_primary_menu_is_attached_before_opening_any_submenu() {
    let mut scene = Scene::new();
    scene.view.dailies[0].options.values[0]
        .options
        .as_mut()
        .unwrap()
        .values
        .truncate(2);
    scene.view.dailies[0].enabled = None;
    scene.click(Id::new(("daily", "每日任务")));
    scene.frame(vec![]);
    assert!(scene.ui.menu.as_ref().unwrap().parent.is_none());
    let popup = assert_popup_attached(&scene);
    assert!((popup.height() - 104.0).abs() <= 1.0);
}

#[test]
fn long_menu_expands_after_opening_a_single_item_menu() {
    for (size, scale) in [
        (SIZE, 1.0),
        (SIZE, 1.25),
        (SIZE, 1.5),
        (SIZE, 2.0),
        (vec2(1024.0, 640.0), 1.0),
        (vec2(1920.0, 1080.0), 1.0),
    ] {
        let mut scene = Scene::new();
        scene.screen_size = size;
        scene.pixels_per_point = scale;
        scene.view.dailies[0].enabled = None;
        scene.view.dailies[0].options = serde_json::from_value(json!({"values": [
            {"display_name": "1-7", "physical_name": "1-7"}
        ]}))
        .unwrap();
        scene.frame(vec![]);
        scene.click(Id::new(("daily", "每日任务")));
        scene.frame(vec![]);
        assert!((assert_popup_attached(&scene).height() - 40.0).abs() <= 1.0);
        scene.click(Id::new(("daily", "每日任务")));
        scene.view.dailies[0].options = serde_json::from_value(json!({"values":
            (0..17).map(|i| json!({"display_name": format!("关卡 {i}"), "physical_name": i})).collect::<Vec<_>>()
        })).unwrap();
        scene.click(Id::new(("daily", "每日任务")));
        for _ in 0..4 {
            scene.frame(vec![]);
        }
        assert!((assert_popup_attached(&scene).height() - 360.0).abs() <= 1.0);
        let last_visible = scene
            .ctx
            .read_response(Id::new(("primary", 9_usize)))
            .unwrap();
        assert!(
            last_visible
                .interact_rect
                .expand(1.0 / scale)
                .contains_rect(last_visible.rect),
            "size {size:?}, scale {scale}: {last_visible:?}"
        );
        let request = only_request(scene.click(Id::new(("primary", 9_usize))));
        assert_eq!(request.params["task_name"], json!("关卡 9"));

        scene.click(Id::new(("daily", "每日任务")));
        scene.frame(vec![]);
        let pos = scene
            .ctx
            .read_response(Id::new(("primary", 0_usize)))
            .unwrap()
            .rect
            .center();
        for _ in 0..8 {
            scene.frame(vec![
                egui::Event::PointerMoved(pos),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    delta: vec2(0.0, -240.0),
                    phase: egui::TouchPhase::Move,
                    modifiers: Default::default(),
                },
            ]);
        }
        let last = scene
            .ctx
            .read_response(Id::new(("primary", 16_usize)))
            .unwrap();
        assert!(
            last.interact_rect
                .expand(1.0 / scale)
                .contains_rect(last.rect),
            "last: {last:?}"
        );
        let request = only_request(scene.click(Id::new(("primary", 16_usize))));
        assert_eq!(request.params["task_name"], json!("关卡 16"));

        // Going back to a short menu must shrink its frame and stay next to the chip.
        scene.view.dailies[0].options.values.truncate(1);
        scene.click(Id::new(("daily", "每日任务")));
        for _ in 0..4 {
            scene.frame(vec![]);
        }
        assert!((assert_popup_attached(&scene).height() - 40.0).abs() <= 1.0);
        let first = scene
            .ctx
            .read_response(Id::new(("primary", 0_usize)))
            .unwrap();
        assert!(
            first
                .interact_rect
                .expand(1.0 / scale)
                .contains_rect(first.rect),
            "first: {first:?}"
        );
        only_request(scene.click(Id::new(("primary", 0_usize))));
    }
}

#[test]
fn submenu_height_stays_stable_when_switching_between_short_and_long_groups() {
    let mut scene = Scene::new();
    scene.daily(1);
    let short = assert_popup_attached(&scene);
    let pos = scene
        .ctx
        .read_response(Id::new(("primary", 0_usize)))
        .unwrap()
        .rect
        .center();
    scene.frame(vec![egui::Event::PointerMoved(pos)]);
    scene.frame(vec![]);
    let long = assert_popup_attached(&scene);
    assert_eq!(
        short, long,
        "hovering between groups must not move the popup"
    );
    let second = scene
        .ctx
        .read_response(Id::new(("child", 1_usize)))
        .unwrap();
    assert!(
        second.interact_rect.contains_rect(second.rect),
        "{second:?}"
    );
    let request = only_request(scene.click(Id::new(("child", 1_usize))));
    assert_eq!(request.params["sequence"], json!(2));
}

#[test]
fn single_group_choices_are_direct_and_preserve_native_values() {
    for (name, labels, values, enabled) in [
        (
            "每日任务",
            ["培养目标", "不启用培养目标"],
            [json!(true), json!(false)],
            None,
        ),
        (
            "追猎目标",
            ["音霸魔王", "无首铁驭"],
            [json!("音霸魔王"), json!("无首铁驭")],
            Some(true),
        ),
        (
            "幽境危战",
            ["第一关", "第二关"],
            [json!(1), json!(2)],
            Some(true),
        ),
    ] {
        let mut scene = Scene::new();
        scene.view.dailies[0] = serde_json::from_value(json!({
            "name": name, "task": name, "sequence": values[0], "enabled": enabled,
            "options": {"values": [{"display_name": name, "physical_name": name,
                "options": {"values": [
                    {"display_name": labels[0], "physical_name": values[0]},
                    {"display_name": labels[1], "physical_name": values[1]}
                ]}}]}
        }))
        .unwrap();
        scene.frame(vec![]);
        scene.click(Id::new(("daily", name)));
        scene.frame(vec![]);
        let entries = daily_entries("test", &scene.view.dailies[0]);
        assert_eq!(entries[0].label, labels[0]);
        assert_eq!(entries[1].label, labels[1]);
        assert!(entries.iter().all(|entry| entry.children.is_empty()));
        let second = scene
            .ctx
            .read_response(Id::new(("primary", 1_usize)))
            .unwrap();
        assert!(
            second.interact_rect.contains_rect(second.rect),
            "{second:?}"
        );
        let request = only_request(scene.click(Id::new(("primary", 1_usize))));
        assert_eq!(request.method, "daily.select");
        assert_eq!(request.params["daily_name"], name);
        assert_eq!(request.params["task_name"], name);
        assert_eq!(request.params["sequence"], values[1]);
        if enabled.is_some() {
            scene.click(Id::new(("daily", name)));
            scene.frame(vec![]);
            let request = only_request(scene.click(Id::new(("primary", 2_usize))));
            assert_eq!(request.method, "daily.enable");
            assert_eq!(request.params["enabled"], json!(false));
        }
    }
}

#[test]
fn submenu_larger_than_primary_menu_fits_without_scrolling() {
    let mut scene = Scene::new();
    scene.view.dailies[0].enabled = None;
    scene.view.dailies[0].options.values.truncate(1);
    scene.view.dailies[0].options.values[0]
        .options
        .as_mut()
        .unwrap()
        .values
        .truncate(6);
    scene.daily(0);
    let sixth = scene
        .ctx
        .read_response(Id::new(("child", 5_usize)))
        .unwrap();
    assert!(sixth.interact_rect.contains_rect(sixth.rect), "{sixth:?}");
    let request = only_request(scene.click(Id::new(("child", 5_usize))));
    assert_eq!(request.params["task_name"], "材料");
    assert_eq!(request.params["sequence"], json!(6));
}

#[test]
fn real_menu_click_preserves_boolean_and_disable_semantics() {
    let mut scene = Scene::new();
    scene.daily(1);
    let request = only_request(scene.click(Id::new(("child", 0_usize))));
    assert_eq!(request.method, "daily.select");
    assert_eq!(request.params["task_name"], "布尔");
    assert_eq!(request.params["sequence"], json!(true));
    assert!(scene.ui.menu.is_none());
    scene.click(Id::new(("daily", "每日任务")));
    scene.frame(vec![]);
    let request = only_request(scene.click(Id::new(("primary", 3_usize))));
    assert_eq!(request.method, "daily.enable");
    assert_eq!(request.params["enabled"], json!(false));
}

#[test]
fn long_submenu_can_scroll_to_last_integer_choice() {
    let mut scene = Scene::new();
    scene.daily(0);
    let pos = scene
        .ctx
        .read_response(Id::new(("child", 0_usize)))
        .unwrap()
        .rect
        .center();
    for _ in 0..12 {
        scene.frame(vec![
            egui::Event::PointerMoved(pos),
            egui::Event::MouseWheel {
                unit: egui::MouseWheelUnit::Point,
                delta: vec2(0.0, -240.0),
                phase: egui::TouchPhase::Move,
                modifiers: Default::default(),
            },
        ]);
    }
    let request = only_request(scene.click(Id::new(("child", 39_usize))));
    assert_eq!(request.params["sequence"], json!(40));
}

#[test]
fn weekly_zero_and_current_launch_are_distinct_actions() {
    let mut scene = Scene::new();
    scene.click(Id::new(("start", "周常")));
    scene.frame(vec![]);
    let request = only_request(scene.click(Id::new(("primary", 0_usize))));
    assert_eq!(request.method, "weekly.start");
    assert_eq!(request.params["start_day"], json!(0));
    let request = only_request(scene.click(Id::new("launch")));
    assert_eq!(request.method, "script.launch_target");
    assert_eq!(
        request.params,
        json!({"script_name":"test","target":"script"})
    );
}

#[test]
fn tall_popups_flip_up_and_remain_inside_window() {
    let screen = Rect::from_min_size(egui::Pos2::ZERO, SIZE);
    for y in [100.0, 460.0, 650.0] {
        let anchor = rect(1180.0, y, 80.0, 36.0);
        let popup = popup_bounds(anchor, vec2(444.0, 360.0), screen);
        assert!(screen.contains_rect(popup));
        assert!(popup.bottom() <= anchor.top() || popup.top() >= anchor.bottom());
    }
}
