//! Visual constants mirror src/gui/qml/{Theme,Layout}.js.
use eframe::egui::{self, Color32, FontId, Pos2, Rect, Vec2, pos2, vec2};
use std::collections::HashMap;

pub const SIZE: Vec2 = vec2(1280.0, 720.0);
pub const CARD_ORIGIN: Pos2 = pos2(128.0, 392.0);
pub const ROW_HEIGHT: f32 = 56.0;
pub const CHIP_WIDTH: f32 = 220.0;
pub const CANVAS: Color32 = Color32::from_rgb(11, 18, 32);
pub const PANEL: Color32 = Color32::from_rgba_premultiplied(17, 27, 42, 235);
pub const CONTROL: Color32 = Color32::from_rgb(29, 43, 64);
pub const HOVER: Color32 = Color32::from_rgb(43, 64, 92);
pub const BORDER: Color32 = Color32::from_rgb(54, 70, 94);
pub const DIVIDER: Color32 = Color32::from_rgb(41, 56, 78);
pub const TEXT: Color32 = Color32::from_rgb(242, 246, 252);
pub const MUTED: Color32 = Color32::from_rgb(164, 179, 200);
pub const ACCENT: Color32 = Color32::from_rgb(140, 185, 255);
pub const ACCENT_SOFT: Color32 = Color32::from_rgb(36, 60, 94);
pub const PRIMARY: Color32 = Color32::from_rgb(43, 77, 115);
pub const BATCH: Color32 = Color32::from_rgb(255, 222, 33);

pub struct Assets {
    pub background: egui::TextureHandle,
    pub gradient: egui::TextureHandle,
    pub icons: HashMap<&'static str, egui::TextureHandle>,
}

fn texture(ctx: &egui::Context, name: &str, bytes: &[u8]) -> egui::TextureHandle {
    let image = image::load_from_memory(bytes).expect("valid bundled image");
    let max_side = ctx.input(|input| input.max_texture_side) as u32;
    let image = if image.width().max(image.height()) > max_side {
        image.thumbnail(max_side, max_side)
    } else {
        image
    };
    let rgba = image.to_rgba8();
    let size = [rgba.width() as usize, rgba.height() as usize];
    ctx.load_texture(
        name,
        egui::ColorImage::from_rgba_unmultiplied(size, &rgba),
        egui::TextureOptions::LINEAR,
    )
}

impl Assets {
    pub fn new(ctx: &egui::Context) -> Self {
        let background = texture(
            ctx,
            "default-wallpaper",
            include_bytes!("../../assets/ds.jpg"),
        );
        let mut icons = HashMap::new();
        macro_rules! icon {
            ($name:literal) => {
                icons.insert(
                    $name,
                    texture(
                        ctx,
                        $name,
                        include_bytes!(concat!("../assets/icons/", $name, ".png")),
                    ),
                );
            };
        }
        icon!("home");
        icon!("game");
        icon!("folder");
        icon!("bili");
        icon!("github");
        icon!("wallpaper");
        icon!("settings");
        icon!("min");
        icon!("close");
        icon!("log");
        icon!("configfile");
        icon!("play");
        icon!("play_all");
        icon!("chevron_down");
        icon!("grid");
        icon!("script");
        let gradient = ctx.load_texture(
            "wallpaper-gradient",
            egui::ColorImage::new([1, 2], vec![Color32::from_rgb(58, 63, 82), CANVAS]),
            egui::TextureOptions::LINEAR,
        );
        Self {
            background,
            gradient,
            icons,
        }
    }

    pub fn icon(&self, ui: &egui::Ui, name: &str, rect: Rect) {
        assert!(self.icons.contains_key(name), "bundled icon must exist");
        let handle = &self.icons[name];
        ui.painter().image(
            handle.id(),
            rect,
            Rect::from_min_max(Pos2::ZERO, pos2(1.0, 1.0)),
            Color32::WHITE,
        );
    }
}

pub fn rect(x: f32, y: f32, width: f32, height: f32) -> Rect {
    Rect::from_min_size(pos2(x, y), vec2(width, height))
}

pub fn panel(ui: &egui::Ui, rect: Rect, radius: u8, fill: Color32) {
    ui.painter().rect(
        rect,
        radius,
        fill,
        egui::Stroke::new(1.0, BORDER),
        egui::StrokeKind::Inside,
    );
}

pub fn label(ui: &egui::Ui, rect: Rect, text: &str, size: f32, color: Color32) {
    let mut job =
        egui::text::LayoutJob::simple_singleline(text.into(), FontId::proportional(size), color);
    job.wrap.max_width = rect.width();
    job.wrap.max_rows = 1;
    job.wrap.break_anywhere = true;
    let galley = ui.painter().layout_job(job);
    ui.painter().galley(
        pos2(rect.left(), rect.center().y - galley.size().y / 2.0),
        galley,
        color,
    );
}

pub fn centered(ui: &egui::Ui, rect: Rect, text: &str, size: f32, color: Color32) {
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        text,
        FontId::proportional(size),
        color,
    );
}

pub fn configure(ctx: &egui::Context) {
    ctx.set_theme(egui::Theme::Dark);
    ctx.set_visuals_of(egui::Theme::Dark, egui::Visuals::dark());
    ctx.style_mut_of(egui::Theme::Dark, |style| {
        style.spacing.item_spacing = vec2(4.0, 2.0);
        style.spacing.button_padding = vec2(10.0, 5.0);
        style.visuals.override_text_color = Some(TEXT);
        style.visuals.panel_fill = CANVAS;
        style.visuals.selection.bg_fill = ACCENT_SOFT;
        style.visuals.selection.stroke.color = ACCENT;
        style
            .text_styles
            .insert(egui::TextStyle::Body, FontId::proportional(13.0));
        style
            .text_styles
            .insert(egui::TextStyle::Button, FontId::proportional(13.0));
    });
}
