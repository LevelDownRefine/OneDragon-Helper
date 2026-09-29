use super::*;
use std::ffi::OsStr;

fn package(root: &Path) -> PathBuf {
    std::fs::write(
        root.join("version.json"),
        r#"{"frontend":"rust","version":"1.0.0"}"#,
    )
    .unwrap();
    std::fs::write(root.join(CLI_EXE), []).unwrap();
    std::fs::create_dir(root.join("_internal")).unwrap();
    root.join(GUI_EXE)
}

#[test]
fn bundled_backend_ignores_cwd_and_virtual_environment() {
    let temp = tempfile::tempdir().unwrap();
    let executable = package(temp.path());
    let cwd = tempfile::tempdir().unwrap();
    let (root, backend) = resolve(
        None,
        None,
        &executable,
        cwd.path(),
        Some("missing-env".into()),
    )
    .unwrap();
    assert_eq!(root, temp.path().canonicalize().unwrap());
    let command = backend.command(&root);
    assert_eq!(command.get_program(), root.join(CLI_EXE).as_os_str());
    assert_eq!(
        command.get_args().collect::<Vec<_>>(),
        [OsStr::new("serve"), OsStr::new("--stdio")]
    );
    assert_eq!(command.get_current_dir(), Some(root.as_path()));
    assert!(!root.join("src").exists());
}

#[test]
fn broken_package_does_not_fall_back_to_python() {
    for missing in ["version.json", CLI_EXE, "_internal"] {
        let temp = tempfile::tempdir().unwrap();
        let executable = package(temp.path());
        let path = temp.path().join(missing);
        if path.is_dir() {
            std::fs::remove_dir(path).unwrap();
        } else {
            std::fs::remove_file(path).unwrap();
        }
        assert!(resolve(None, None, &executable, temp.path(), None).is_err());
        assert!(
            resolve(
                None,
                None,
                &temp.path().join(GUI_EXE.to_lowercase()),
                temp.path(),
                None
            )
            .is_err()
        );
    }
    for metadata in [
        r#"{"version":"1.0.0"}"#,
        r#"{"version":"1.0.0","frontend":"qt"}"#,
        r#"{"version":"","frontend":"rust"}"#,
    ] {
        let temp = tempfile::tempdir().unwrap();
        let executable = package(temp.path());
        std::fs::write(temp.path().join("version.json"), metadata).unwrap();
        assert!(resolve(None, None, &executable, temp.path(), None).is_err());
    }
}

#[test]
fn explicit_source_root_retains_development_arguments() {
    let temp = tempfile::tempdir().unwrap();
    let executable = package(temp.path());
    let source = temp.path().join("source project");
    std::fs::create_dir_all(source.join("python-backend/src")).unwrap();
    std::fs::write(source.join("python-backend/src/headless.py"), []).unwrap();
    let interpreter = temp.path().join("python.exe");
    std::fs::write(&interpreter, []).unwrap();
    assert!(
        resolve(
            None,
            Some(interpreter.clone()),
            &executable,
            temp.path(),
            None
        )
        .is_err()
    );
    let (root, backend) = resolve(
        Some("source project".into()),
        Some(interpreter.clone()),
        &executable,
        temp.path(),
        None,
    )
    .unwrap();
    let command = backend.command(&root);
    assert_eq!(
        command.get_current_dir(),
        Some(root.join("python-backend").as_path())
    );
    assert_eq!(
        command.get_program(),
        interpreter.canonicalize().unwrap().as_os_str()
    );
    assert_eq!(
        command.get_args().collect::<Vec<_>>(),
        ["-m", "src.headless", "serve", "--stdio"].map(OsStr::new)
    );
}

#[test]
fn cli_preserves_arguments_working_directory_and_exit_code() {
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(temp.path().join("python-backend/src")).unwrap();
    std::fs::write(temp.path().join("python-backend/src/__init__.py"), []).unwrap();
    std::fs::write(
        temp.path().join("python-backend/src/headless.py"),
        "import json, os, sys\nfrom pathlib import Path\nPath('result.json').write_text(json.dumps({'args':sys.argv[1:], 'ui':os.environ['ODH_SHUTDOWN_UI']}), encoding='utf-8')\nsys.exit(7)\n",
    ).unwrap();
    let python = std::env::var_os("ODH_TEST_PYTHON").unwrap_or_else(|| "python".into());
    let arguments = ["--get-script", "中文 空格", r#"C:\quoted "name"\"#].map(OsString::from);
    assert_eq!(
        BackendProgram::Source(python.into())
            .run_cli(temp.path(), &arguments)
            .unwrap(),
        7
    );
    let result: serde_json::Value = serde_json::from_slice(
        &std::fs::read(temp.path().join("python-backend/result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        result["args"],
        serde_json::json!([
            "legacy",
            "--",
            "--get-script",
            "中文 空格",
            r#"C:\quoted "name"\"#
        ])
    );
    assert_eq!(
        PathBuf::from(result["ui"].as_str().unwrap()),
        std::env::current_exe().unwrap()
    );
}
