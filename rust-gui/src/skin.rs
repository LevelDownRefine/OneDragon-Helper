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

/// Scoped form styling; the wallpaper and main window keep their own layout.
fn dialog_style(ui: &mut egui::Ui) {
    let style = ui.style_mut();
    style.spacing.item_spacing = vec2(10.0, 8.0);
    style.spacing.button_padding = vec2(14.0, 7.0);
    style.spacing.interact_size.y = 30.0;
    style.visuals.text_edit_bg_color = Some(Color32::from_rgb(13, 23, 38));
    style.visuals.widgets.inactive.bg_fill = CONTROL;
    style.visuals.widgets.inactive.weak_bg_fill = CONTROL;
    style.visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.0, BORDER);
    style.visuals.widgets.inactive.corner_radius = 7.into();
    style.visuals.widgets.hovered.bg_fill = HOVER;
    style.visuals.widgets.hovered.weak_bg_fill = HOVER;
    style.visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.0, ACCENT);
    style.visuals.widgets.hovered.corner_radius = 7.into();
    style.visuals.widgets.active.bg_fill = ACCENT_SOFT;
    style.visuals.widgets.active.weak_bg_fill = ACCENT_SOFT;
    style.visuals.widgets.active.corner_radius = 7.into();
    style
        .text_styles
        .insert(egui::TextStyle::Body, FontId::proportional(14.0));
    style
        .text_styles
        .insert(egui::TextStyle::Button, FontId::proportional(14.0));
}

fn dialog_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(Color32::from_rgb(17, 27, 42))
        .stroke(egui::Stroke::new(1.0, BORDER))
        .corner_radius(18)
        .inner_margin(22)
}

/// Shared shell; each caller retains its own save and cancellation semantics.
pub struct Dialog<'a> {
    id: egui::Id,
    title: &'a str,
    description: &'a str,
    width: f32,
}

impl<'a> Dialog<'a> {
    pub fn new(id: &str, title: &'a str) -> Self {
        Self {
            id: egui::Id::new(id),
            title,
            description: "",
            width: 520.0,
        }
    }

    pub fn description(mut self, description: &'a str) -> Self {
        self.description = description;
        self
    }

    pub fn width(mut self, width: f32) -> Self {
        self.width = width;
        self
    }

    /// Returns a close intent only when closing is allowed by the caller.
    pub fn show(
        self,
        ctx: &egui::Context,
        closable: bool,
        contents: impl FnOnce(&mut egui::Ui),
    ) -> bool {
        let mut close = false;
        let modal = egui::Modal::new(self.id)
            .frame(dialog_frame())
            .show(ctx, |ui| {
                ui.set_width(
                    self.width
                        .min((ctx.content_rect().width() - 80.0).max(280.0)),
                );
                dialog_style(ui);
                ui.horizontal(|ui| {
                    let title_width = ui.available_width() - 44.0;
                    ui.allocate_ui_with_layout(
                        vec2(title_width, 32.0),
                        egui::Layout::left_to_right(egui::Align::Center),
                        |ui| {
                            ui.set_min_width(title_width);
                            ui.add(
                                egui::Label::new(
                                    egui::RichText::new(self.title).size(22.0).strong(),
                                )
                                .truncate(),
                            )
                            .on_hover_text(self.title);
                        },
                    );
                    close = ui
                        .add_enabled(closable, egui::Button::new("×").frame(false))
                        .on_hover_text("关闭")
                        .clicked();
                });
                if !self.description.is_empty() {
                    ui.label(
                        egui::RichText::new(self.description)
                            .size(12.0)
                            .color(MUTED),
                    );
                }
                ui.add_space(6.0);
                contents(ui);
            });
        closable && (close || modal.should_close())
    }
}

/// Only the body scrolls, keeping the title and actions visible.
pub fn dialog_body(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui)) {
    egui::ScrollArea::vertical()
        .max_height((ui.ctx().content_rect().height() - 230.0).clamp(140.0, 490.0))
        .auto_shrink([false, true])
        .show(ui, contents);
}

/// Actions are ordered from the primary action at the right edge.
pub fn dialog_footer(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui)) {
    ui.add_space(4.0);
    ui.separator();
    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
        ui.set_min_height(34.0);
        contents(ui);
    });
}

pub fn dialog_status(ui: &mut egui::Ui, error: Option<&str>, notice: Option<&str>) {
    if error.is_some() || notice.is_some() {
        egui::ScrollArea::vertical()
            .id_salt("dialog-status")
            .max_height(40.0)
            .min_scrolled_height(0.0)
            .show(ui, |ui| {
                if let Some(error) = error {
                    ui.colored_label(Color32::LIGHT_RED, error);
                }
                if let Some(notice) = notice {
                    ui.label(notice);
                }
            });
    }
}

pub fn text_input(text: &mut String) -> egui::TextEdit<'_> {
    egui::TextEdit::singleline(text).margin(vec2(8.0, 6.0))
}

pub fn secondary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(text).min_size(vec2(78.0, 34.0))
}

/// Equal-width label and input columns within a section.
pub fn form_grid(ui: &mut egui::Ui, id: &str, contents: impl FnOnce(&mut egui::Ui)) {
    let input_width = (ui.available_width() - 104.0).max(120.0);
    ui.scope(|ui| {
        ui.spacing_mut().text_edit_width = input_width;
        ui.spacing_mut().combo_width = input_width;
        egui::Grid::new(id)
            .num_columns(2)
            .min_col_width(92.0)
            .spacing([12.0, 10.0])
            .show(ui, contents);
    });
}

pub fn path_input(ui: &mut egui::Ui, path: &mut String) -> (bool, bool) {
    ui.horizontal(|ui| {
        let changed = ui
            .add(text_input(path).desired_width((ui.available_width() - 86.0).max(80.0)))
            .changed();
        (
            changed,
            ui.add_sized([76.0, 32.0], egui::Button::new("浏览…"))
                .clicked(),
        )
    })
    .inner
}

pub fn form_section(ui: &mut egui::Ui, title: &str, content: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(Color32::from_rgb(22, 34, 51))
        .stroke(egui::Stroke::new(1.0, DIVIDER))
        .corner_radius(10)
        .inner_margin(14)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(egui::RichText::new(title).size(14.0).strong().color(ACCENT));
            content(ui);
        });
}

pub fn primary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).color(TEXT).strong())
        .fill(PRIMARY)
        .stroke(egui::Stroke::new(1.0, Color32::from_rgb(80, 122, 174)))
        .min_size(vec2(92.0, 34.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame<T>(
        ctx: &egui::Context,
        size: Vec2,
        events: Vec<egui::Event>,
        show: impl FnOnce(&egui::Context) -> T,
    ) -> (T, egui::FullOutput) {
        let mut result = None;
        let mut show = Some(show);
        let mut output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(Rect::from_min_size(Pos2::ZERO, size)),
                events,
                ..Default::default()
            },
            |ui| result = Some(show.take().expect("single pass")(ui.ctx())),
        );
        output.textures_delta.clear();
        (result.unwrap(), output)
    }

    fn text_rect(output: &egui::FullOutput, label: &str) -> Rect {
        output
            .shapes
            .iter()
            .find_map(|shape| {
                if let egui::Shape::Text(text) = &shape.shape
                    && text.galley.text() == label
                {
                    let rect = Rect::from_min_size(text.pos, text.galley.size());
                    assert!(shape.clip_rect.contains_rect(rect), "{label} is clipped");
                    Some(rect)
                } else {
                    None
                }
            })
            .unwrap_or_else(|| panic!("missing visible label: {label}"))
    }

    fn click(pos: Pos2, pressed: bool) -> Vec<egui::Event> {
        vec![
            egui::Event::PointerMoved(pos),
            egui::Event::PointerButton {
                pos,
                button: egui::PointerButton::Primary,
                pressed,
                modifiers: Default::default(),
            },
        ]
    }

    #[test]
    fn shared_close_button_respects_write_lock() {
        for closable in [true, false] {
            let ctx = egui::Context::default();
            let show = |ctx: &egui::Context| {
                Dialog::new("test-dialog", "Settings").show(ctx, closable, |ui| {
                    ui.label("Body");
                })
            };
            for _ in 0..12 {
                assert!(!frame(&ctx, SIZE, vec![], show).0);
            }
            let (_, output) = frame(&ctx, SIZE, vec![], show);
            let pos = text_rect(&output, "×").center();
            assert!(!frame(&ctx, SIZE, click(pos, true), show).0);
            assert_eq!(frame(&ctx, SIZE, click(pos, false), show).0, closable);
        }
    }

    #[test]
    fn long_script_form_keeps_save_visible_and_blocks_duplicate_writes() {
        use crate::script_editor::{EditAction, ScriptEditor};
        use serde_json::json;
        for size in [SIZE, vec2(1000.0, 600.0)] {
            for (busy, reload) in [(false, false), (true, false), (false, true)] {
                let ctx = egui::Context::default();
                let mut editor = ScriptEditor::new(serde_json::from_value(json!({
                    "script_name": "demo",
                    "script": {"display_name": "long title ".repeat(60), "script_path": "demo.exe"},
                    "weekly_timeouts": [60,60,60,60,60,60,60],
                    "switches": (0..100).map(|i| json!({"name":format!("Task {i}"),"enabled":true})).collect::<Vec<_>>()
                })).unwrap());
                if reload {
                    editor.failure("read before saving ".repeat(100), true);
                }
                for _ in 0..12 {
                    assert!(
                        frame(&ctx, size, vec![], |ctx| editor.show(ctx, busy))
                            .0
                            .is_none()
                    );
                }
                let (_, output) = frame(&ctx, size, vec![], |ctx| editor.show(ctx, busy));
                let rect = ctx
                    .memory(|m| m.area_rect(egui::Id::new("script-editor")))
                    .unwrap();
                assert!(
                    Rect::from_min_size(Pos2::ZERO, size).contains_rect(rect),
                    "{rect:?}"
                );
                let pos = text_rect(&output, "保存").center();
                assert!(
                    frame(&ctx, size, click(pos, true), |ctx| editor.show(ctx, busy))
                        .0
                        .is_none()
                );
                let (action, _) =
                    frame(&ctx, size, click(pos, false), |ctx| editor.show(ctx, busy));
                if busy || reload {
                    assert!(action.is_none());
                } else {
                    let Some(EditAction::Save(request)) = action else {
                        panic!("expected save");
                    };
                    assert_eq!(request.method, "script.edit_save");
                    assert_eq!(request.params["switches"].as_object().unwrap().len(), 100);
                    assert_eq!(request.params["config_patch"]["script_type"], "external");
                }
            }
        }
    }
}
