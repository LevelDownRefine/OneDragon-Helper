use onedragon_rust_gui::{
    backend::{Backend, Session},
    model::ScriptView,
};
use serde_json::{Value, json};
use std::{
    env,
    path::PathBuf,
    process::Command,
    sync::atomic::AtomicBool,
    time::{Duration, Instant},
};

fn python(code: &str) -> Command {
    let mut command = Command::new(env::var_os("ODH_TEST_PYTHON").unwrap_or("python".into()));
    command.args(["-u", "-c", code]);
    command.current_dir(PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap());
    command
        .env("PYTHONUTF8", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1");
    command
}

fn call(session: &mut Session, method: &str, params: Value) -> Value {
    session
        .request(
            method,
            params,
            Duration::from_secs(15),
            &AtomicBool::new(false),
        )
        .unwrap_or_else(|error| panic!("{}\n{}", error.message, session.diagnostics()))
}

#[test]
fn real_cli_round_trip_types_external_changes_and_shutdown() {
    let root = tempfile::tempdir().unwrap();
    let mut command = python(include_str!("fixtures/real_backend.py"));
    command.arg(root.path());
    let mut session = Session::spawn(command).unwrap();
    let pid = session.pid();
    let snapshot = call(&mut session, "app.snapshot", json!({}));
    assert_eq!(snapshot["scripts"][0]["display_name"], "鸣潮");
    let saved = call(
        &mut session,
        "daily.select",
        json!({
            "script_name": "ok-ww", "daily_name": "每日任务", "task_name": "凝素领域", "sequence": 1
        }),
    );
    assert!(saved.is_null());
    let view = call(&mut session, "script.view", json!({"script_name": "ok-ww"}));
    let view: ScriptView = serde_json::from_value(view).unwrap();
    assert_eq!(view.dailies[0].sequence, json!(1));
    assert_eq!(view.dailies[0].label(), "凝素领域 · 梦州-迅刀");
    let native = root
        .path()
        .join("scripts/data/apps/ok-ww/working/configs/DailyTask.json");
    let mut data: Value = serde_json::from_slice(&std::fs::read(&native).unwrap()).unwrap();
    assert_eq!(data["Which Forgery Challenge to Farm"], 1);
    assert_eq!(data["untouched"], json!({"中文": [1, 2, 3]}));
    data["Which Forgery Challenge to Farm"] = json!(2);
    std::fs::write(&native, serde_json::to_vec(&data).unwrap()).unwrap();
    let view = call(&mut session, "script.view", json!({"script_name": "ok-ww"}));
    assert_eq!(view["dailies"][0]["sequence"], 2);
    let saved = call(
        &mut session,
        "weekly.start",
        json!({
            "script_name": "ok-ww", "weekly_name": "幻梦游园", "start_day": 0
        }),
    );
    assert!(saved.is_null());
    let view = call(&mut session, "script.view", json!({"script_name": "ok-ww"}));
    assert_eq!(view["weeklies"][0]["start_day"], 0);
    let saved = call(
        &mut session,
        "daily.select",
        json!({
            "script_name": "March7th-Launcher", "daily_name": "每日任务",
            "task_name": "每日任务", "sequence": true
        }),
    );
    assert!(saved.is_null());
    let view = call(
        &mut session,
        "script.view",
        json!({"script_name": "March7th-Launcher"}),
    );
    assert!(
        view["dailies"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["sequence"] == json!(true))
    );
    assert_eq!(pid, session.pid());
    let yaml = std::fs::read_to_string(root.path().join("scripts/config.yaml")).unwrap();
    assert!(yaml.contains("build_target_enable: true"), "{yaml}");
    let rejected = session.request("daily.select", json!({
        "script_name": "March7th-Launcher", "daily_name": "每日任务", "task_name": "每日任务", "sequence": 1
    }), Duration::from_secs(10), &AtomicBool::new(false)).unwrap_err();
    assert_eq!(rejected.code, "operation_failed");
    assert!(rejected.refresh_required);
    call(&mut session, "script.view", json!({"script_name": "ok-ww"}));
    let mut command = python(
        "import sys\nfrom pathlib import Path\nfrom src.update.runtime import FileLease\nwith FileLease(Path(sys.argv[1])): pass",
    );
    let lock = root.path().join(".update/runtime.lock");
    assert!(lock.is_file());
    command.arg(lock);
    assert!(!command.output().unwrap().status.success());
    drop(session);
    // The same exclusive lease must succeed only after the child releases it.
    let result = command.output().unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn stderr_flood_does_not_block_utf8_responses() {
    let command = python(
        "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n sys.stderr.write('诊断'*100000);sys.stderr.flush()\n print(json.dumps({'protocol_version':1,'id':r['id'],'result':{'名称':'中文'}},ensure_ascii=False),flush=True)",
    );
    let mut session = Session::spawn(command).unwrap();
    assert_eq!(
        call(&mut session, "app.snapshot", json!({}))["名称"],
        "中文"
    );
    assert!(session.diagnostics().len() <= 65536);
}

#[test]
fn timeout_invalidates_connection_without_replaying_write() {
    let command = python("import sys,time\nfor line in sys.stdin:\n time.sleep(10)");
    let mut session = Session::spawn(command).unwrap();
    let start = Instant::now();
    let result = session.request(
        "daily.select",
        json!({}),
        Duration::from_millis(100),
        &AtomicBool::new(false),
    );
    assert_eq!(result.unwrap_err().code, "transport_failed");
    assert!(
        session
            .request(
                "app.snapshot",
                json!({}),
                Duration::from_secs(1),
                &AtomicBool::new(false)
            )
            .is_err()
    );
    drop(session);
    assert!(start.elapsed() < Duration::from_secs(3));
}

#[test]
fn malformed_or_wrong_id_response_fails_closed() {
    for response in ["broken", r#"{"protocol_version":1,"id":999,"result":{}}"#] {
        let mut command = python("import sys\nsys.stdin.readline()\nprint(sys.argv[1],flush=True)");
        command.arg(response);
        let mut session = Session::spawn(command).unwrap();
        assert_eq!(
            session
                .request(
                    "app.snapshot",
                    json!({}),
                    Duration::from_secs(5),
                    &AtomicBool::new(false)
                )
                .unwrap_err()
                .code,
            "transport_failed"
        );
    }
}

#[test]
fn closing_backend_cancels_pending_request() {
    let backend = Backend::start(
        python("import sys,time\nsys.stdin.readline()\ntime.sleep(10)"),
        || {},
    );
    backend
        .requests
        .send(onedragon_rust_gui::backend::Request {
            method: "app.snapshot".into(),
            params: json!({}),
        })
        .unwrap();
    std::thread::sleep(Duration::from_millis(100));
    let started = Instant::now();
    drop(backend);
    assert!(started.elapsed() < Duration::from_secs(3));
}

#[test]
fn blocked_large_write_times_out_and_close_stays_responsive() {
    for cancel in [false, true] {
        let command = python("import time\ntime.sleep(30)");
        let params = json!({"data":"x".repeat(1024 * 1024)});
        let started = Instant::now();
        if cancel {
            let backend = Backend::start(command, || {});
            backend
                .requests
                .send(onedragon_rust_gui::backend::Request {
                    method: "blocked".into(),
                    params,
                })
                .unwrap();
            std::thread::sleep(Duration::from_millis(150));
            drop(backend);
        } else {
            let mut session = Session::spawn(command).unwrap();
            let error = session
                .request(
                    "blocked",
                    params,
                    Duration::from_millis(150),
                    &AtomicBool::new(false),
                )
                .unwrap_err();
            assert!(error.message.contains("超时"));
            drop(session);
        }
        assert!(started.elapsed() < Duration::from_secs(3));
    }
}

#[test]
fn real_cli_stores_large_wallpaper_cache_and_rejects_stale_token() {
    use base64::Engine;
    let root = tempfile::tempdir().unwrap();
    let mut command = python(include_str!("fixtures/real_backend.py"));
    command.arg(root.path());
    let mut session = Session::spawn(command).unwrap();
    call(&mut session, "app.snapshot", json!({}));
    let source = root.path().join("壁纸.jpg");
    let image = image::RgbImage::from_fn(256, 256, |x, y| {
        image::Rgb([(x * y) as u8, x as u8, y as u8])
    });
    let mut jpeg = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg, 90)
        .encode_image(&image)
        .unwrap();
    assert!(jpeg.len() > 4096);
    std::fs::write(&source, &jpeg).unwrap();
    call(
        &mut session,
        "wallpaper.set",
        json!({"script_name":"ok-ww","file_path":source}),
    );
    let state = call(
        &mut session,
        "wallpaper.view",
        json!({"script_name":"ok-ww"}),
    );
    assert_eq!(
        call(
            &mut session,
            "wallpaper.cache",
            json!({"script_name":"ok-ww","token":state["token"],"jpeg_base64":base64::engine::general_purpose::STANDARD.encode(&jpeg)})
        ),
        true
    );
    let state = call(
        &mut session,
        "wallpaper.current",
        json!({"script_name":"ok-ww"}),
    );
    assert_eq!(
        std::fs::read(state["cache"].as_str().unwrap()).unwrap(),
        jpeg
    );
    assert_eq!(
        call(
            &mut session,
            "wallpaper.cache",
            json!({"script_name":"ok-ww","token":"stale","jpeg_base64":base64::engine::general_purpose::STANDARD.encode(&jpeg)})
        ),
        false
    );
    assert_eq!(std::fs::read(source).unwrap(), jpeg);
}

#[test]
fn idle_exit_is_reported_without_another_request() {
    let backend = Backend::start(
        python(
            "import sys,json,time\nr=json.loads(sys.stdin.readline())\nprint(json.dumps({'protocol_version':1,'id':r['id'],'result':{}}),flush=True)\ntime.sleep(0.1)",
        ),
        || {},
    );
    backend
        .requests
        .send(onedragon_rust_gui::backend::Request {
            method: "app.snapshot".into(),
            params: json!({}),
        })
        .unwrap();
    assert!(
        backend
            .replies
            .recv_timeout(Duration::from_secs(5))
            .unwrap()
            .result
            .is_ok()
    );
    let reply = backend
        .replies
        .recv_timeout(Duration::from_secs(5))
        .unwrap();
    assert_eq!(reply.method, "session");
    assert_eq!(reply.result.unwrap_err().code, "transport_failed");
}
