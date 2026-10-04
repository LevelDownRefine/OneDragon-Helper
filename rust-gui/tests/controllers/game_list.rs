use super::*;

use super::super::tests::{Scene, only_request};
#[test]
fn batch_button_uses_only_manual_selection_and_empty_is_local() {
    let mut scene = Scene::new();
    let request = only_request(scene.click(Id::new(("icon", "启动手动勾选的脚本"))));
    assert_eq!(request.method, "run.view");
    assert_eq!(request.params, json!({"script_names":["test"]}));
    scene.ui.disabled.insert("test".into());
    assert!(
        scene
            .click(Id::new(("icon", "启动手动勾选的脚本")))
            .is_empty()
    );
    assert!(scene.ui.toast.as_ref().unwrap().0.contains("没有勾选"));
}

#[test]
fn manual_selection_is_local_and_follows_identity() {
    let mut scene = Scene::new();
    assert!(
        scene
            .click(Id::new(("icon", "选择手动运行的脚本")))
            .is_empty()
    );
    scene.frame(vec![]);
    assert!(scene.click(Id::new(("script", "test"))).is_empty());
    assert!(scene.ui.disabled.contains("test"));
    assert!(scene.click(Id::new(("manual-action", 0_usize))).is_empty());
    assert!(scene.ui.disabled.is_empty());
    assert!(scene.click(Id::new(("manual-action", 1_usize))).is_empty());
    scene.ui.rename_script("test", "new");
    assert_eq!(scene.ui.disabled, HashSet::from(["new".into()]));
    scene.ui.reconcile_scripts(&scene.scripts);
    assert!(scene.ui.disabled.is_empty());
    let actions = scene.click(Id::new(("manual-action", 2_usize)));
    assert!(matches!(actions.as_slice(), [Action::AddScript]));
    assert!(!scene.ui.control_mode);
    assert!(Scene::new().ui.disabled.is_empty());
}

#[test]
fn drag_reorders_or_requests_delete_confirmation() {
    for delete in [None, Some(pos2(40.0, 632.0)), Some(pos2(60.0, 632.0))] {
        let mut scene = Scene::new();
        let mut second = scene.scripts[0].clone();
        second.script_name = "second".into();
        scene.scripts.push(second);
        scene.frame(vec![]);
        let start = scene
            .ctx
            .read_response(Id::new(("script", "test")))
            .unwrap()
            .rect
            .center();
        let end = delete.unwrap_or_else(|| {
            scene
                .ctx
                .read_response(Id::new(("script", "second")))
                .unwrap()
                .rect
                .center()
        });
        scene.frame(vec![
            egui::Event::PointerMoved(start),
            egui::Event::PointerButton {
                pos: start,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: Default::default(),
            },
        ]);
        scene.frame(vec![egui::Event::PointerMoved(end)]);
        let actions = scene.frame(vec![egui::Event::PointerButton {
            pos: end,
            button: egui::PointerButton::Primary,
            pressed: false,
            modifiers: Default::default(),
        }]);
        if delete.is_some() {
            assert!(matches!(actions.as_slice(),[Action::RemoveScript(name)] if name == "test"));
        } else {
            let request = only_request(actions);
            assert_eq!(request.method, "script.reorder");
            assert_eq!(request.params, json!({"script_names":["second","test"]}));
        }
        assert!(scene.ui.dragging.is_none());
    }
}

#[test]
fn context_menu_deletes_its_script_only_after_confirmation_intent() {
    for (busy, count) in [(false, 2), (true, 2), (false, 1)] {
        let mut scene = Scene::new();
        if count == 2 {
            let mut second = scene.scripts[0].clone();
            second.script_name = "second".into();
            second.display_name = "Second".into();
            scene.scripts.push(second);
        }
        scene.editing_blocked = busy;
        scene.frame(vec![]);
        let name = if count == 2 { "second" } else { "test" };
        let position = scene
            .ctx
            .read_response(Id::new(("script", name)))
            .unwrap()
            .rect
            .center();
        for pressed in [true, false] {
            assert!(
                scene
                    .frame(vec![
                        egui::Event::PointerMoved(position),
                        egui::Event::PointerButton {
                            pos: position,
                            button: egui::PointerButton::Secondary,
                            pressed,
                            modifiers: Default::default(),
                        },
                    ])
                    .is_empty()
            );
        }
        scene.frame(vec![]);
        let position = scene
            .output
            .shapes
            .iter()
            .find_map(|shape| {
                if let egui::Shape::Text(text) = &shape.shape
                    && text.galley.text() == "删除脚本…"
                {
                    Some(text.pos + text.galley.size() / 2.0)
                } else {
                    None
                }
            })
            .expect("visible delete command");
        let mut actions = Vec::new();
        for pressed in [true, false] {
            actions.extend(scene.frame(vec![
                egui::Event::PointerMoved(position),
                egui::Event::PointerButton {
                    pos: position,
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: Default::default(),
                },
            ]));
        }
        if !busy && count == 2 {
            assert!(matches!(actions.as_slice(), [Action::RemoveScript(name)] if name == "second"));
        } else {
            assert!(actions.is_empty(), "busy/last script must not delete");
        }
    }
}
