use crate::theme::*;
use eframe::egui::{self, Color32, FontId, vec2};

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

pub fn danger_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).color(TEXT).strong())
        .fill(DANGER_FILL)
        .stroke(egui::Stroke::new(1.0, DANGER))
        .min_size(vec2(104.0, 34.0))
}

#[cfg(test)]
#[path = "../../tests/dialogs/common.rs"]
mod tests;
