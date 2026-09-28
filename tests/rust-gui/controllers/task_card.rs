use super::*;

use super::super::tests::{Scene, only_request};
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
