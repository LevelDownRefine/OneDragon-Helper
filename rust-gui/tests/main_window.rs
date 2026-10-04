use super::*;
use std::time::Duration;

fn waiting_app(root: &std::path::Path) -> App {
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-c", "import sys; sys.stdin.read()"]);
    test_app(command, root, python)
}

fn icon_reply() -> Reply {
    Reply {
        method: "script.icon_path".into(),
        result: Ok(json!({"script_name":"test","path":null})),
        diagnostics: String::new(),
        pid: 0,
    }
}

#[test]
fn native_completion_and_reply_release_only_their_own_locks() {
    for launch in [false, true] {
        for reply_first in [false, true] {
            let root = tempfile::tempdir().unwrap();
            let mut app = waiting_app(root.path());
            if launch {
                app.launch_job = Some(LaunchJob::start(
                    controllers::launch::LaunchTarget::Unavailable {
                        reason: "test".into(),
                    },
                    app.ctx.clone(),
                ));
            } else {
                app.open_job = Some(OpenJob::start(
                    Target::Unavailable {
                        reason: "test".into(),
                    },
                    || {},
                ));
            }
            assert!(!app.request_pending);
            assert!(app.dialog_blocked());
            app.request("script.icon_path", json!({"script_name":"test"}));
            assert!(app.request_pending);
            if reply_first {
                app.receive(icon_reply());
                assert!(!app.request_pending);
                assert!(app.dialog_blocked(), "native job still owns its lock");
            }
            let status = app.status.clone();
            let deadline = Instant::now() + Duration::from_secs(10);
            while app.local_operation_active() {
                app.poll_local_jobs();
                assert!(Instant::now() < deadline, "native result timed out");
                std::thread::yield_now();
            }
            if !reply_first {
                assert!(
                    app.request_pending,
                    "native completion cannot unlock the request"
                );
                assert_eq!(app.status, status);
                assert!(app.dialog_blocked());
                app.receive(icon_reply());
            }
            assert!(!app.request_pending);
            assert!(!app.editing_blocked());
        }
    }
}

#[test]
fn transport_failure_preserves_native_results_and_error_status() {
    let root = tempfile::tempdir().unwrap();
    let mut app = waiting_app(root.path());
    app.open_job = Some(OpenJob::start(
        Target::Unavailable {
            reason: "test".into(),
        },
        || {},
    ));
    app.launch_job = Some(LaunchJob::start(
        controllers::launch::LaunchTarget::Unavailable {
            reason: "test".into(),
        },
        app.ctx.clone(),
    ));
    app.request("script.icon_path", json!({"script_name":"test"}));
    app.fail(Failure::transport("connection lost"));
    assert!(!app.request_pending);
    assert!(app.backend.is_none());
    assert!(app.open_job.is_some() && app.launch_job.is_some());
    let status = app.status.clone();
    let deadline = Instant::now() + Duration::from_secs(10);
    while app.local_operation_active() {
        app.poll_local_jobs();
        assert!(Instant::now() < deadline, "native result timed out");
        std::thread::yield_now();
    }
    assert_eq!(app.status, status);
    assert_eq!(app.error.as_deref(), Some("connection lost"));
}

#[test]
fn running_backup_blocks_editing_between_polls_until_terminal_reply() {
    let root = tempfile::tempdir().unwrap();
    let mut app = waiting_app(root.path());
    let mut dialog = BackupDialog::new(false);
    dialog.started(json!({"id":"backup"})).unwrap();
    app.backup_dialog = Some(dialog);
    assert!(!app.request_pending);
    assert!(!app.dialog_blocked());
    assert!(app.editing_blocked());
    app.request("job.poll", json!({"job_id":"backup"}));
    app.receive(Reply {
        method: "job.poll".into(),
        result: Ok(json!({"id":"backup","kind":"backup","state":"running"})),
        diagnostics: String::new(),
        pid: 0,
    });
    assert!(!app.request_pending);
    assert!(app.editing_blocked());
    assert_eq!(app.status, "处理中");
    app.request("job.poll", json!({"job_id":"backup"}));
    app.receive(Reply {
        method: "job.poll".into(),
        result: Ok(json!({"id":"backup","kind":"backup","state":"succeeded","result":{"file_count":1,"path":"backup.zip"}})),
        diagnostics: String::new(),
        pid: 0,
    });
    assert!(!app.request_pending);
    assert!(!app.editing_blocked());
}

#[test]
fn refresh_after_transport_failure_starts_new_session_without_replaying_write() {
    let root = tempfile::tempdir().unwrap();
    let package = root.path().join("python-backend/src");
    std::fs::create_dir_all(&package).unwrap();
    std::fs::write(package.join("__init__.py"), "").unwrap();
    std::fs::write(package.join("headless.py"), r#"
import json,sys
for line in sys.stdin:
    request = json.loads(line)
    with open('requests.jsonl', 'a') as history:
        history.write(request['method'] + '\n')
    script = {'script_name':'test', 'display_name':'Test', 'script_path':'test.exe', 'adapted':False}
    result = {'scripts':[script]} if request['method'] == 'app.snapshot' else {'script':script, 'dailies':[], 'weeklies':[]}
    print(json.dumps({'jsonrpc':'2.0', 'id':request['id'], 'result':result}), flush=True)
"#).unwrap();
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-c", "import sys; sys.stdin.read()"]);
    let mut app = test_app(command, root.path(), python);
    app.request("daily.select", json!({"script_name":"test"}));
    app.receive(Reply {
        method: "daily.select".into(),
        pid: 0,
        diagnostics: String::new(),
        result: Err(Failure::transport("write outcome unknown")),
    });
    assert!(app.backend.is_none());
    assert!(app.view.is_none());
    app.connect();
    for method in ["app.snapshot", "script.view"] {
        let reply = app
            .backend
            .as_ref()
            .unwrap()
            .replies
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(reply.method, method);
        app.receive(reply);
    }
    assert_eq!(app.view.as_ref().unwrap().script.script_name, "test");
    assert!(!app.request_pending);
    assert_eq!(
        std::fs::read_to_string(root.path().join("python-backend/requests.jsonl"))
            .unwrap()
            .lines()
            .collect::<Vec<_>>(),
        ["app.snapshot", "script.view"]
    );
}

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
        request_pending: false,
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
    print(json.dumps({'jsonrpc': '2.0','id':request['id'],'error':{'code': -32002,'message':'read failed','data': {'refresh_required': False}}}),flush=True)
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
    assert!(!app.request_pending);
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
    assert!(!app.request_pending);
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
    print(json.dumps({'jsonrpc': '2.0','id':request['id'],'error':{'code': -32002,'message':'init failed','data': {'refresh_required': True}}}),flush=True)
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
    app.request_pending = true;
    app.start_drop(Ok(paths.clone()));
    assert!(app.drop_dialog.is_none());
    app.request_pending = false;
    app.list_dialog = Some(ListDialog::add());
    app.start_drop(Ok(paths.clone()));
    assert!(app.drop_dialog.is_none());
    app.list_dialog = None;
    app.start_drop(Ok(paths));
    assert!(app.background_task_active());
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
    assert!(!app.background_task_active());
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
    print(json.dumps({'jsonrpc': '2.0','id':request['id'],'error':{'code': -32002,'message':'read failed','data': {'refresh_required': False}}}),flush=True)
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
        assert_eq!(app.request_pending, !skip);
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
        assert!(
            !app.request_pending,
            "refresh must not repeat startup after a failure"
        );
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
    print(json.dumps({'jsonrpc': '2.0','id':request['id'],'result':result}), flush=True)
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
    for (method, scenario) in [
        ("daily.select", "ok"),
        ("daily.enable", "ok"),
        ("weekly.select", "ok"),
        ("weekly.start", "ok"),
        ("daily.select", "error"),
        ("daily.select", "malformed"),
        ("daily.select", "wrong-script"),
    ] {
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
    response = {'jsonrpc': '2.0', 'id': request['id']}
    if request['method'] != 'script.view':
        response['result'] = None
    elif sys.argv[2] == 'error':
        response['error'] = {'code': -32002, 'message': 'read failed', 'data': {'refresh_required': False}}
    elif sys.argv[2] == 'malformed':
        response['result'] = None
    else:
        response['result'] = {'script': {'script_name': 'another' if sys.argv[2] == 'wrong-script' else 'test', 'display_name': 'Test', 'script_path': 'test.exe', 'adapted': True}, 'dailies': [{'name':'每日任务', 'options': {'values':[]}, 'task':'已保存的副本', 'sequence':2, 'enabled':True}], 'weeklies': []}
    print(json.dumps(response), flush=True)
"#]);
        command.arg(&history).arg(scenario);
        let mut app = test_app(command, root.path(), python);
        let old_view: ScriptView = serde_json::from_value(json!({
            "script": {"script_name":"test", "display_name":"Test", "script_path":"test.exe", "adapted":true},
            "dailies":[{"name":"每日任务", "options":{"values":[]}, "task":"原副本", "sequence":1, "enabled":true}],
            "weeklies":[]
        })).unwrap();
        app.scripts = vec![old_view.script.clone()];
        app.view = Some(old_view);
        let before = task_row_rect(&mut app);
        app.request(method, json!({"script_name": "test"}));
        assert_eq!(task_row_rect(&mut app), before);
        for stage in 0..2 {
            let reply = app
                .backend
                .as_ref()
                .unwrap()
                .replies
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
            app.receive(reply);
            if stage == 0 {
                assert!(app.request_pending && app.write_confirmed);
                let view = app.view.as_ref().expect("keep the card while reading back");
                assert_eq!(view.dailies[0].task.as_deref(), Some("原副本"));
                assert_eq!(task_row_rect(&mut app), before);
            }
        }
        assert!(!app.request_pending);
        assert!(!app.write_confirmed);
        if scenario == "ok" {
            assert_eq!(
                app.view.as_ref().unwrap().dailies[0].task.as_deref(),
                Some("已保存的副本")
            );
            assert_eq!(task_row_rect(&mut app), before);
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
        assert_eq!(requests[0]["method"], method);
        assert_eq!(requests[1]["method"], "script.view");
        assert_eq!(requests[1]["params"]["script_name"], "test");
    }
}

fn task_row_rect(app: &mut App) -> egui::Rect {
    let mut output = app.ctx.clone().run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                crate::theme::SIZE,
            )),
            ..Default::default()
        },
        |ui| {
            app.ui.show(
                ui,
                Presentation {
                    scripts: &app.scripts,
                    selected: app.selected.as_deref(),
                    view: app.view.as_ref(),
                    editing_blocked: app.editing_blocked(),
                    block_close: false,
                    status: &app.status,
                    demo: true,
                },
            );
        },
    );
    output.textures_delta.clear();
    app.ctx
        .read_response(egui::Id::new(("daily", "每日任务")))
        .expect("task row remains visible")
        .rect
}

#[test]
fn changing_script_clears_the_old_card_before_reading() {
    let root = tempfile::tempdir().unwrap();
    let python = PathBuf::from(std::env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    let mut command = Command::new(&python);
    command.args(["-u", "-c", "import sys,json\nfor line in sys.stdin:\n r=json.loads(line); print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':None}),flush=True)"]);
    let mut app = test_app(command, root.path(), python);
    for selected in [Some("another"), None] {
        app.view = Some(serde_json::from_value(json!({
            "script":{"script_name":"test","display_name":"Test","script_path":"test.exe","adapted":true},
            "dailies":[], "weeklies":[]
        })).unwrap());
        app.selected = selected.map(str::to_owned);
        app.refresh_view();
        assert!(
            app.view.is_none(),
            "must not show the previous script's tasks"
        );
        if selected.is_some() {
            let reply = app
                .backend
                .as_ref()
                .unwrap()
                .replies
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
            assert_eq!(reply.method, "script.view");
            app.request_pending = false;
        }
    }
}
