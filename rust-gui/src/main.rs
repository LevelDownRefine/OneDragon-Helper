#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]
mod app;
mod backup_dialog;
mod daily_plan;
mod drop_dialog;
mod file_drop;
mod file_picker;
mod launch;
mod list_dialog;
mod native_icons;
mod opener;
mod run_dialog;
mod runtime;
mod script_editor;
mod settings_dialog;
mod shutdown;
mod skin;
mod update_dialog;
mod video;
mod view;
mod wallpaper;

use std::{env, ffi::OsString, path::PathBuf, time::Instant};

fn settings() -> Result<(app::Settings, Vec<OsString>), String> {
    let mut args = env::args_os().skip(1);
    let mut project = None;
    let mut python = None;
    let mut font = None;
    let mut demo = false;
    let mut skip_startup = false;
    let mut cli_arguments = Vec::new();
    #[cfg(feature = "capture")]
    let mut capture = None;
    #[cfg(feature = "capture")]
    let mut capture_editor = false;
    #[cfg(feature = "capture")]
    let mut capture_list = false;
    #[cfg(feature = "capture")]
    let mut capture_run = false;
    #[cfg(feature = "capture")]
    let mut capture_settings = false;
    #[cfg(feature = "capture")]
    let mut capture_plan = false;
    #[cfg(feature = "capture")]
    let mut capture_restore = false;
    #[cfg(feature = "capture")]
    let mut capture_drop = Vec::new();
    #[cfg(feature = "capture")]
    let mut capture_game_icon = false;
    #[cfg(feature = "capture")]
    let mut capture_wallpaper = false;
    #[cfg(feature = "capture")]
    let mut capture_update = false;
    while let Some(argument) = args.next() {
        match argument.to_str() {
            Some("--project-root") => {
                project = Some(PathBuf::from(args.next().ok_or("--project-root 缺少路径")?))
            }
            Some("--python") => {
                python = Some(PathBuf::from(args.next().ok_or("--python 缺少路径")?))
            }
            Some("--font") => font = Some(PathBuf::from(args.next().ok_or("--font 缺少路径")?)),
            Some("--demo-label") => demo = true,
            Some("--after-update") => skip_startup = true,
            #[cfg(feature = "capture")]
            Some("--capture") => {
                capture = Some(PathBuf::from(args.next().ok_or("--capture 缺少路径")?))
            }
            #[cfg(feature = "capture")]
            Some("--capture-editor") => capture_editor = true,
            #[cfg(feature = "capture")]
            Some("--capture-list") => capture_list = true,
            #[cfg(feature = "capture")]
            Some("--capture-game-icon") => capture_game_icon = true,
            #[cfg(feature = "capture")]
            Some("--capture-wallpaper") => capture_wallpaper = true,
            #[cfg(feature = "capture")]
            Some("--capture-update") => capture_update = true,
            #[cfg(feature = "capture")]
            Some("--capture-drop") => {
                capture_drop.push(PathBuf::from(args.next().ok_or("--capture-drop 缺少路径")?))
            }
            #[cfg(feature = "capture")]
            Some("--capture-run") => capture_run = true,
            #[cfg(feature = "capture")]
            Some("--capture-settings") => capture_settings = true,
            #[cfg(feature = "capture")]
            Some("--capture-restore") => {
                capture_settings = true;
                capture_restore = true;
            }
            #[cfg(feature = "capture")]
            Some("--capture-plan") => {
                capture_settings = true;
                capture_plan = true;
            }
            Some("-h") => {
                cli_arguments.push("--help".into());
                cli_arguments.extend(args);
                break;
            }
            _ => {
                cli_arguments.push(argument);
                cli_arguments.extend(args);
                break;
            }
        }
    }
    let (root, backend) = runtime::resolve(
        project,
        python,
        &env::current_exe().map_err(|error| error.to_string())?,
        &env::current_dir().map_err(|error| error.to_string())?,
        env::var_os("VIRTUAL_ENV").map(PathBuf::from),
    )?;
    #[cfg(feature = "capture")]
    {
        skip_startup |= capture.is_some();
    }
    skip_startup |= demo;
    Ok((
        app::Settings {
            project_root: root,
            backend,
            font,
            demo,
            skip_startup,
            #[cfg(feature = "capture")]
            capture,
            #[cfg(feature = "capture")]
            capture_editor,
            #[cfg(feature = "capture")]
            capture_list,
            #[cfg(feature = "capture")]
            capture_run,
            #[cfg(feature = "capture")]
            capture_settings,
            #[cfg(feature = "capture")]
            capture_plan,
            #[cfg(feature = "capture")]
            capture_restore,
            #[cfg(feature = "capture")]
            capture_drop,
            #[cfg(feature = "capture")]
            capture_game_icon,
            #[cfg(feature = "capture")]
            capture_wallpaper,
            #[cfg(feature = "capture")]
            capture_update,
        },
        cli_arguments,
    ))
}

fn main() -> eframe::Result {
    let started = Instant::now();
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    if env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--shutdown-confirm")) {
        let code = shutdown::run(env::args_os().skip(2).collect()).unwrap_or_else(|error| {
            log::error!("关机确认失败：{error}");
            2
        });
        std::process::exit(code);
    }
    let (settings, cli_arguments) = match settings() {
        Ok(settings) => settings,
        Err(error) => {
            runtime::startup_error(&error);
            std::process::exit(2);
        }
    };
    if !cli_arguments.is_empty() {
        let code = settings
            .backend
            .run_cli(&settings.project_root, &cli_arguments)
            .unwrap_or_else(|error| {
                runtime::startup_error(&error);
                2
            });
        std::process::exit(code);
    }
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size(skin::SIZE)
            .with_resizable(false)
            .with_decorations(false)
            .with_transparent(true),
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
