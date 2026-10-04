use super::*;

#[test]
fn targets_keep_path_characters_and_reject_other_schemes() {
    let root = tempfile::tempdir().unwrap();
    let value = root
        .path()
        .join("中文 & test config.yml")
        .to_string_lossy()
        .into_owned();
    assert_eq!(
        Target::Path {
            value: value.clone()
        }
        .value()
        .unwrap(),
        value
    );
    assert!(
        Target::Path {
            value: "relative.yml".into()
        }
        .value()
        .is_err()
    );
    for value in [
        "file:///run.exe",
        "javascript:alert(1)",
        "https://example.org/\0x",
    ] {
        assert!(
            Target::Url {
                value: value.into()
            }
            .value()
            .is_err()
        );
    }
    assert_eq!(
        Target::Url {
            value: "https://example.org/?a=1&b=2".into()
        }
        .value()
        .unwrap(),
        "https://example.org/?a=1&b=2"
    );
}

#[test]
fn unavailable_target_completes_without_opening_a_program() {
    let job = OpenJob::start(
        Target::Unavailable {
            reason: "未安装".into(),
        },
        || {},
    );
    let result = job
        .0
        .recv_timeout(std::time::Duration::from_secs(2))
        .unwrap();
    assert_eq!(result.unwrap_err(), "未安装");
}

use super::super::tests::{Scene, only_request};
#[test]
fn hovering_game_only_queries_icon_once_per_entry() {
    let mut scene = Scene::new();
    let pos = scene
        .ctx
        .read_response(Id::new(("icon", "启动游戏")))
        .unwrap()
        .rect
        .center();
    let actions = scene.frame(vec![egui::Event::PointerMoved(pos)]);
    assert_eq!(only_request(actions).method, "script.icon_path");
    assert!(scene.frame(vec![]).is_empty());
    scene.ui.set_game_icon("test".into(), None);
    assert!(scene.frame(vec![]).is_empty());
    scene.frame(vec![egui::Event::PointerMoved(pos2(500.0, 100.0))]);
    scene.editing_blocked = true;
    assert!(scene.frame(vec![egui::Event::PointerMoved(pos)]).is_empty());
    scene.editing_blocked = false;
    assert_eq!(only_request(scene.frame(vec![])).method, "script.icon_path");
}

#[test]
fn navigation_buttons_request_current_script_targets() {
    let mut scene = Scene::new();
    for (label, target) in [
        ("游戏官网", "home"),
        ("脚本目录", "folder"),
        ("运行日志", "log"),
        ("脚本配置文件", "configfile"),
        ("哔哩哔哩", "bili"),
        ("GitHub", "github"),
    ] {
        let request = only_request(scene.click(Id::new(("icon", label))));
        assert_eq!(request.method, "script.target");
        assert_eq!(
            request.params,
            json!({"script_name": "test", "target": target})
        );
    }
    let request = only_request(scene.click(Id::new(("icon", "启动游戏"))));
    assert_eq!(request.method, "script.launch_target");
    assert_eq!(
        request.params,
        json!({"script_name":"test","target":"game"})
    );
    let request = only_request(scene.click(Id::new(("icon", "更换壁纸"))));
    assert_eq!(request.method, "wallpaper.view");
    assert_eq!(request.params, json!({"script_name":"test"}));
}
