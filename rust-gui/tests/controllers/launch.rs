use super::*;

#[test]
fn runner_launch_preserves_arguments_and_survives_gui_owner_drop() {
    let root = tempfile::tempdir().unwrap();
    let marker = root.path().join("中文 & marker.txt");
    let python = std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into());
    let python = Path::new(&python)
        .canonicalize()
        .expect("absolute test Python");
    let target=LaunchTarget::Command {program:python.to_string_lossy().into(),
        args:vec!["-c".into(),"import sys,time,os;from pathlib import Path;time.sleep(.3);Path(sys.argv[1]).write_text(sys.argv[2]+os.environ['ODH_LAUNCH_TEST'],encoding='utf-8')".into(),marker.to_string_lossy().into(),"原样 & 空格".into()],
        cwd:root.path().to_string_lossy().into(),env:HashMap::from([("ODH_LAUNCH_TEST".into(),"环境".into())]),input:None,console:false};
    let job = LaunchJob::start(target, eframe::egui::Context::default());
    let child = job
        .0
        .recv_timeout(std::time::Duration::from_secs(10))
        .unwrap()
        .unwrap()
        .unwrap();
    drop(job);
    drop(child); // GUI exit drops handles; it must not terminate external work.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    while !marker.exists() && std::time::Instant::now() < deadline {
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    assert_eq!(std::fs::read_to_string(marker).unwrap(), "原样 & 空格环境");
}

#[test]
fn bootstrap_stdin_reaches_child_and_closes_at_eof() {
    let root = tempfile::tempdir().unwrap();
    let marker = root.path().join("payload.json");
    let python = Path::new(&std::env::var_os("ODH_TEST_PYTHON").expect("test Python"))
        .canonicalize()
        .unwrap();
    let target=LaunchTarget::Command {
        program:python.to_string_lossy().into(),
        args:vec!["-c".into(),"import sys;from pathlib import Path;sys.stdin.reconfigure(encoding='utf-8');Path(sys.argv[1]).write_text(sys.stdin.read(),encoding='utf-8')".into(),marker.to_string_lossy().into()],
        cwd:root.path().to_string_lossy().into(),env:HashMap::new(),input:Some("{\"script_names\":[\"中文, & 脚本\"]}".into()),console:false,
    };
    let mut child = target.start().unwrap().unwrap();
    assert!(child.wait().unwrap().success());
    assert_eq!(
        std::fs::read_to_string(marker).unwrap(),
        "{\"script_names\":[\"中文, & 脚本\"]}"
    );
}

#[test]
fn unavailable_and_invalid_targets_fail_before_launch() {
    assert!(
        LaunchTarget::Association {
            path: "relative.exe".into(),
            arguments: String::new()
        }
        .start()
        .is_err()
    );
    assert!(
        LaunchTarget::Unavailable {
            reason: "未安装".into()
        }
        .start()
        .is_err()
    );
    assert!(absolute_path("C:/invalid\0file").is_err());
}

use super::super::tests::{Scene, only_request};
#[test]
fn script_settings_opens_edit_form_for_current_script() {
    let mut scene = Scene::new();
    let request = only_request(scene.click(Id::new(("icon", "脚本配置"))));
    assert_eq!(request.method, "script.edit_view");
    assert_eq!(request.params, json!({"script_name": "test"}));
    let request = only_request(scene.click(Id::new(("icon", "配置"))));
    assert_eq!(request.method, "settings.view");
    assert_eq!(request.params, json!({}));
    scene.busy = true;
    assert!(scene.click(Id::new(("icon", "配置"))).is_empty());
}
