use super::*;
use std::time::Duration;

fn test_app(command: Command, root: &std::path::Path, python: PathBuf) -> App {
    let ctx = egui::Context::default();
    App {
        settings: Settings {
            project_root: root.into(),
            backend: BackendProgram::Source(python),
            font: None,
            demo: true,
            skip_startup: true,
            #[cfg(feature = "capture")]
            capture: None,
            #[cfg(feature = "capture")]
            capture_editor: false,
            #[cfg(feature = "capture")]
            capture_list: false,
            #[cfg(feature = "capture")]
            capture_run: false,
            #[cfg(feature = "capture")]
            capture_settings: false,
            #[cfg(feature = "capture")]
            capture_plan: false,
            #[cfg(feature = "capture")]
            capture_restore: false,
            #[cfg(feature = "capture")]
            capture_drop: Vec::new(),
            #[cfg(feature = "capture")]
            capture_game_icon: false,
            #[cfg(feature = "capture")]
            capture_wallpaper: false,
            #[cfg(feature = "capture")]
            capture_update: false,
        },
        backend: Some(Backend::start(command, || {})),
        scripts: Vec::new(),
        selected: Some("test".into()),
        view: None,
        busy: false,
        status: String::new(),
        error: None,
        diagnostics: String::new(),
        pid: 0,
        started: Instant::now(),
        first_ui: true,
        ready_logged: false,
        write_confirmed: false,
        ui: View::new(&ctx),
        open_job: None,
        launch_job: None,
        launched: Vec::new(),
        editor: None,
        list_dialog: None,
        open_editor_after_snapshot: false,
        run_dialog: None,
        settings_dialog: None,
        backup_dialog: None,
        update_dialog: None,
        open_update_after_snapshot: false,
        startup_dialog: None,
        file_drop: None,
        drop_dialog: None,
        wallpaper_dialog: None,
        wallpaper_pending: None,
        open_wallpaper_after_snapshot: false,
        refresh_settings_run: false,
        open_settings_after_snapshot: false,
        ctx,
        #[cfg(feature = "capture")]
        capture_requested: false,
        #[cfg(feature = "capture")]
        capture_ready_at: None,
    }
}

#[test]
#[cfg(feature = "capture")]
fn pending_capture_keeps_an_idle_window_advancing() {
    let root = tempfile::tempdir().unwrap();
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-c", "import sys; sys.stdin.read()"]);
    let mut app = test_app(command, root.path(), python);
    app.backend = None;
    app.selected = None;
    let ctx = app.ctx.clone();
    let mut frame = eframe::Frame::_new_kittest();
    for capture in [false, true] {
        app.settings.capture = capture.then(|| root.path().join("frame.png"));
        app.capture_requested = capture;
        let mut delay = Duration::ZERO;
        for index in 0..5 {
            let mut output = ctx.run_ui(
                egui::RawInput {
                    time: Some(index as f64 + if capture { 10.0 } else { 0.0 }),
                    ..Default::default()
                },
                |ui| eframe::App::ui(&mut app, ui, &mut frame),
            );
            delay = output.viewport_output[&egui::ViewportId::ROOT].repaint_delay;
            output.textures_delta.clear();
        }
        if capture {
            assert!(delay <= Duration::from_millis(16));
        } else {
            assert!(delay > Duration::from_millis(16));
        }
    }
}

#[test]
fn saved_wallpaper_read_failure_keeps_dialog_without_repeating_save() {
    let root = tempfile::tempdir().unwrap();
    let history = root.path().join("requests.txt");
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request=json.loads(line)
    with open(sys.argv[1], 'a') as f: f.write(request['method']+'\n')
    print(json.dumps({'protocol_version':1,'id':request['id'],'error':{'code':'operation_failed','message':'read failed','refresh_required':False}}),flush=True)
"#]).arg(&history);
    let mut app = test_app(command, root.path(), python);
    app.wallpaper_dialog = Some(WallpaperDialog::new(serde_json::from_value(json!({"script_name":"test","display_name":"Test","mode":"image","source":"image.png","custom_path":"image.png","token":"old","cache":null})).unwrap()));
    app.receive(Reply {
        method: "wallpaper.set".into(),
        pid: 0,
        diagnostics: String::new(),
        result: Ok(Value::Null),
    });
    assert!(app.write_confirmed);
    let reply = app
        .backend
        .as_ref()
        .unwrap()
        .replies
        .recv_timeout(Duration::from_secs(10))
        .unwrap();
    assert_eq!(reply.method, "wallpaper.view");
    app.receive(reply);
    assert!(!app.busy);
    assert!(!app.write_confirmed);
    assert!(app.wallpaper_dialog.is_some());
    assert_eq!(
        std::fs::read_to_string(history)
            .unwrap()
            .lines()
            .collect::<Vec<_>>(),
        ["wallpaper.view"]
    );
}

#[test]
fn optional_icon_failure_preserves_task_card() {
    let root = tempfile::tempdir().unwrap();
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-c", "import sys; sys.stdin.read()"]);
    let mut app = test_app(command, root.path(), python);
    app.view = Some(serde_json::from_value(json!({"script":{"script_name":"test","display_name":"Test","script_path":"test.exe","adapted":false},"dailies":[],"weeklies":[]})).unwrap());
    app.receive(Reply {
        method: "script.icon_path".into(),
        pid: 0,
        diagnostics: String::new(),
        result: Err(Failure {
            code: "operation_failed".into(),
            message: "game path unavailable".into(),
            refresh_required: false,
        }),
    });
    assert!(app.view.is_some());
    assert!(app.backend.is_some());
    assert!(!app.busy);
    assert!(app.error.is_none());
}

#[test]
fn drop_ignores_busy_input_and_refreshes_partial_write_without_replay() {
    let root = tempfile::tempdir().unwrap();
    let history = root.path().join("requests.txt");
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request=json.loads(line)
    with open(sys.argv[1], 'a') as f: f.write(request['method']+'\n')
    print(json.dumps({'protocol_version':1,'id':request['id'],'error':{'code':'operation_failed','message':'init failed','refresh_required':True}}),flush=True)
"#]).arg(&history);
    let mut app = test_app(command, root.path(), python);
    app.view = Some(serde_json::from_value(json!({"script":{"script_name":"test","display_name":"Test","script_path":"test.exe","adapted":false},"dailies":[],"weeklies":[]})).unwrap());
    let paths: Vec<_> = ["a.exe", "b.py"]
        .map(|name| {
            let path = root.path().join(name);
            std::fs::write(&path, "never execute").unwrap();
            path
        })
        .into();
    app.busy = true;
    app.start_drop(Ok(paths.clone()));
    assert!(app.drop_dialog.is_none());
    app.busy = false;
    app.list_dialog = Some(ListDialog::add());
    app.start_drop(Ok(paths.clone()));
    assert!(app.drop_dialog.is_none());
    app.list_dialog = None;
    app.start_drop(Ok(paths));
    assert!(app.operation_active());
    let request = app.drop_dialog.as_mut().unwrap().next().unwrap();
    app.request(&request.method, request.params);
    let reply = app
        .backend
        .as_ref()
        .unwrap()
        .replies
        .recv_timeout(Duration::from_secs(10))
        .unwrap();
    app.receive(reply);
    assert!(!app.operation_active());
    assert!(app.launch_job.is_none());
    let reply = app
        .backend
        .as_ref()
        .unwrap()
        .replies
        .recv_timeout(Duration::from_secs(10))
        .unwrap();
    assert_eq!(reply.method, "app.snapshot");
    assert_eq!(
        std::fs::read_to_string(history)
            .unwrap()
            .lines()
            .collect::<Vec<_>>(),
        ["script.add", "app.snapshot"]
    );
    assert!(app.drop_dialog.as_mut().unwrap().next().is_none());
}

#[test]
fn startup_is_requested_once_and_update_restart_skips_it() {
    for skip in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let history = root.path().join("requests.jsonl");
        let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
        let mut command = Command::new(&python);
        command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request=json.loads(line)
    with open(sys.argv[1], 'a') as f: f.write(request['method']+'\n')
    print(json.dumps({'protocol_version':1,'id':request['id'],'error':{'code':'operation_failed','message':'read failed','refresh_required':False}}),flush=True)
"#]).arg(&history);
        let mut app = test_app(command, root.path(), python);
        app.settings.skip_startup = skip;
        app.scripts = vec![serde_json::from_value(json!({"script_name":"test","display_name":"Test","script_path":"test.exe","adapted":false})).unwrap()];
        let view = json!({"script":{"script_name":"test","display_name":"Test","script_path":"test.exe","adapted":false},"dailies":[],"weeklies":[]});
        app.receive(Reply {
            method: "script.view".into(),
            pid: 0,
            diagnostics: String::new(),
            result: Ok(view.clone()),
        });
        assert_eq!(app.busy, !skip);
        if !skip {
            let reply = app
                .backend
                .as_ref()
                .unwrap()
                .replies
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
            app.receive(reply);
        }
        app.receive(Reply {
            method: "script.view".into(),
            pid: 0,
            diagnostics: String::new(),
            result: Ok(view),
        });
        assert!(!app.busy, "refresh must not repeat startup after a failure");
        assert!(app.launch_job.is_none());
        drop(app);
        if skip {
            assert!(!history.exists());
        } else {
            assert_eq!(
                std::fs::read_to_string(history).unwrap().trim(),
                "startup.view"
            );
        }
    }
}

#[test]
fn dropping_gui_keeps_external_script_running() {
    let root = tempfile::tempdir().unwrap();
    let marker = root.path().join("finished");
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut backend = Command::new(&python);
    backend.args(["-c", "import time;time.sleep(10)"]);
    let mut app = test_app(backend, root.path(), python.clone());
    let child = Command::new(python)
        .args([
            "-c",
            "import sys,time;from pathlib import Path;time.sleep(.5);Path(sys.argv[1]).touch()",
        ])
        .arg(&marker)
        .spawn()
        .unwrap();
    app.launched.push(child);
    drop(app);
    let deadline = Instant::now() + Duration::from_secs(10);
    while !marker.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        marker.exists(),
        "closing the GUI must not kill launched scripts"
    );
}

#[test]
fn editor_failures_keep_draft_and_never_repeat_save() {
    for code in ["invalid_params", "operation_failed", "transport_failed"] {
        let root = tempfile::tempdir().unwrap();
        let history = root.path().join("requests.jsonl");
        let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
        let mut command = Command::new(&python);
        command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[1], 'a', encoding='utf-8') as history:
        history.write(json.dumps(request) + '\n')
    result = {'scripts': [{'script_name':'renamed', 'display_name':'renamed', 'script_path':'new.py', 'adapted':False}]} if request['method'] == 'app.snapshot' else {'script': {'script_name':'renamed','display_name':'renamed','script_path':'new.py','adapted':False}, 'dailies':[], 'weeklies':[]}
    print(json.dumps({'protocol_version':1,'id':request['id'],'result':result}), flush=True)
"#]).arg(&history);
        let mut app = test_app(command, root.path(), python);
        app.editor = Some(ScriptEditor::new(
            serde_json::from_value(json!({
                "script_name":"test", "script":{"display_name":"renamed", "script_path":"new.py"},
                "weekly_timeouts":[60,60,60,60,60,60,60], "switches":[]
            }))
            .unwrap(),
        ));
        app.receive(Reply {
            method: "script.edit_save".into(),
            pid: 0,
            diagnostics: String::new(),
            result: Err(Failure {
                code: code.into(),
                message: "save failed".into(),
                refresh_required: code == "operation_failed",
            }),
        });
        assert_eq!(
            app.editor.as_ref().unwrap().needs_reload,
            code != "invalid_params"
        );
        if code == "operation_failed" {
            for _ in 0..2 {
                let reply = app
                    .backend
                    .as_ref()
                    .unwrap()
                    .replies
                    .recv_timeout(Duration::from_secs(10))
                    .unwrap();
                app.receive(reply);
            }
            assert_eq!(app.selected.as_deref(), Some("renamed"));
            assert!(app.editor.as_ref().unwrap().needs_reload);
            assert!(app.error.as_ref().unwrap().contains("save failed"));
        }
        drop(app);
        if code == "operation_failed" {
            let requests: Vec<Value> = std::fs::read_to_string(history)
                .unwrap()
                .lines()
                .map(|line| serde_json::from_str(line).unwrap())
                .collect();
            assert_eq!(requests.len(), 2);
            assert_eq!(requests[0]["method"], "app.snapshot");
            assert_eq!(requests[1]["method"], "script.view");
        } else {
            assert!(!history.exists());
        }
    }
}

#[test]
fn acknowledged_write_refreshes_once_without_replay_on_read_failure() {
    for scenario in ["ok", "error", "malformed"] {
        let root = tempfile::tempdir().unwrap();
        let history = root.path().join("requests.jsonl");
        let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
        let mut command = Command::new(&python);
        command.args(["-u", "-c", r#"
import json,sys
for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[1], 'a', encoding='utf-8') as history:
        history.write(json.dumps(request) + '\n')
    response = {'protocol_version': 1, 'id': request['id']}
    if request['method'] == 'daily.select':
        response['result'] = None
    elif sys.argv[2] == 'error':
        response['error'] = {'code': 'operation_failed', 'message': 'read failed', 'refresh_required': False}
    elif sys.argv[2] == 'malformed':
        response['result'] = None
    else:
        response['result'] = {'script': {'script_name': 'test', 'display_name': 'Test', 'script_path': 'test.exe', 'adapted': True}, 'dailies': [], 'weeklies': []}
    print(json.dumps(response), flush=True)
"#]);
        command.arg(&history).arg(scenario);
        let mut app = test_app(command, root.path(), python);
        app.request("daily.select", json!({"script_name": "test"}));
        for _ in 0..2 {
            let reply = app
                .backend
                .as_ref()
                .unwrap()
                .replies
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
            app.receive(reply);
        }
        assert!(!app.busy);
        assert!(!app.write_confirmed);
        if scenario == "ok" {
            assert!(app.view.is_some());
            assert!(app.error.is_none());
        } else {
            assert!(app.view.is_none());
            assert!(
                app.error
                    .as_ref()
                    .unwrap()
                    .starts_with("已保存，但刷新失败")
            );
        }
        drop(app);
        let requests: Vec<Value> = std::fs::read_to_string(history)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(requests.len(), 2, "{scenario}: do not replay or retry");
        assert_eq!(requests[0]["method"], "daily.select");
        assert_eq!(requests[1]["method"], "script.view");
        assert_eq!(requests[1]["params"]["script_name"], "test");
    }
}
