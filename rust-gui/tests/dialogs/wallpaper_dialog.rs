use super::*;
use crate::main_window::controllers::background::Mode;
use std::path::PathBuf;
#[test]
fn escape_cancels_wallpaper_without_saving() {
    let ctx = egui::Context::default();
    let mut dialog = WallpaperDialog::new(state("unused.png".into()));
    dialog.path = "draft.png".into();
    for _ in 0..2 {
        let mut output = ctx.run_ui(Default::default(), |ui| {
            assert!(dialog.show(ui.ctx(), false).is_none());
        });
        output.textures_delta.clear();
    }
    let mut output = ctx.run_ui(
        egui::RawInput {
            events: vec![egui::Event::Key {
                key: egui::Key::Escape,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: Default::default(),
            }],
            ..Default::default()
        },
        |ui| {
            assert!(matches!(
                dialog.show(ui.ctx(), false),
                Some(WallpaperAction::Close)
            ));
        },
    );
    output.textures_delta.clear();
}

fn state(path: PathBuf) -> Wallpaper {
    Wallpaper {
        script_name: "test".into(),
        display_name: "测试".into(),
        mode: Mode::Image,
        source: path,
        custom_path: None,
        token: Some("current".into()),
        cache: None,
    }
}
