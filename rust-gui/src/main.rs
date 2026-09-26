#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]
mod app;

use std::{env, path::PathBuf, time::Instant};

fn settings() -> Result<Option<app::Settings>, String> {
    let mut args = env::args_os().skip(1);
    let mut root = env::current_dir().map_err(|err| err.to_string())?;
    let mut python = None;
    let mut font = None;
    let mut demo = false;
    #[cfg(feature = "capture")]
    let mut capture = None;
    while let Some(argument) = args.next() {
        match argument.to_str() {
            Some("--project-root") => root = args.next().ok_or("--project-root 缺少路径")?.into(),
            Some("--python") => {
                python = Some(PathBuf::from(args.next().ok_or("--python 缺少路径")?))
            }
            Some("--font") => font = Some(PathBuf::from(args.next().ok_or("--font 缺少路径")?)),
            Some("--demo-label") => demo = true,
            #[cfg(feature = "capture")]
            Some("--capture") => {
                capture = Some(PathBuf::from(args.next().ok_or("--capture 缺少路径")?))
            }
            Some("--help" | "-h") => {
                log::info!(
                    "onedragon-rust-gui [--project-root 项目根目录] [--python Python路径] [--font 字体路径]"
                );
                return Ok(None);
            }
            _ => return Err(format!("未知参数：{}", argument.to_string_lossy())),
        }
    }
    if !root.join("src/headless.py").is_file() {
        return Err("请从项目根运行，或用 --project-root 指定含 src/headless.py 的目录".into());
    }
    let root = root.canonicalize().map_err(|err| err.to_string())?;
    let python = python.unwrap_or_else(|| {
        let suffix = if cfg!(windows) {
            "Scripts/python.exe"
        } else {
            "bin/python"
        };
        env::var_os("VIRTUAL_ENV")
            .map(PathBuf::from)
            .map(|directory| directory.join(suffix))
            .unwrap_or_else(|| {
                let local = root.join(".venv").join(suffix);
                if local.is_file() {
                    local
                } else {
                    PathBuf::from("python")
                }
            })
    });
    // An explicit relative executable is resolved before changing the child's cwd.
    let python = if python.components().count() > 1 {
        python
            .canonicalize()
            .map_err(|err| format!("Python 路径无效：{err}"))?
    } else {
        python
    };
    Ok(Some(app::Settings {
        project_root: root,
        python,
        font,
        demo,
        #[cfg(feature = "capture")]
        capture,
    }))
}

fn main() -> eframe::Result {
    let started = Instant::now();
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    let settings = match settings() {
        Ok(Some(settings)) => settings,
        Ok(None) => return Ok(()),
        Err(error) => {
            log::error!("{error}");
            std::process::exit(2);
        }
    };
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([1020.0, 740.0])
            .with_min_inner_size([800.0, 560.0]),
        renderer: eframe::Renderer::Glow,
        persist_window: false,
        ..Default::default()
    };
    eframe::run_native(
        "OneDragon · Rust Preview",
        options,
        Box::new(move |cc| Ok(Box::new(app::App::new(cc, settings, started)))),
    )
}
