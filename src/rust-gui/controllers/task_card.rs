use super::*;
use onedragon_rust_gui::model::{Daily, Weekly, start_label};

impl View {
    pub(super) fn toggle(&mut self, kind: MenuKind, anchor: Rect) {
        if self.menu.as_ref().is_some_and(|menu| menu.kind == kind) {
            self.menu = None;
        } else {
            self.menu = Some(Menu {
                kind,
                anchor,
                parent: None,
            });
        }
    }

    pub(super) fn card(&mut self, ui: &mut Ui, data: &Presentation<'_>, actions: &mut Vec<Action>) {
        let count = data
            .view
            .map_or(0, |view| view.dailies.len() + view.weeklies.len());
        let height =
            (84.0 + count as f32 * ROW_HEIGHT).min(ui.max_rect().bottom() - CARD_ORIGIN.y - 16.0);
        let card = Rect::from_min_size(CARD_ORIGIN, vec2(480.0, height));
        ui.painter().rect_filled(
            card.translate(vec2(0.0, 5.0)),
            20,
            egui::Color32::from_black_alpha(40),
        );
        panel(ui, card, 20, PANEL);
        let badge = rect(card.left() + 32.0, card.top() + 18.0, 36.0, 36.0);
        ui.painter().rect_filled(badge, 10, ACCENT_SOFT);
        self.assets.icon(
            ui,
            "game",
            Rect::from_center_size(badge.center(), vec2(28.0, 28.0)),
        );
        let title = data
            .scripts
            .iter()
            .find(|script| Some(script.script_name.as_str()) == data.selected)
            .map_or("暂无脚本", |script| script.display_name.as_str());
        label(
            ui,
            rect(card.left() + 78.0, card.top() + 23.0, 164.0, 26.0),
            title,
            18.0,
            TEXT,
        );
        let refresh = rect(card.right() - 207.0, card.top() + 23.0, 175.0, 26.0);
        let response = ui.interact(refresh, Id::new("refresh"), Sense::click());
        label(
            ui,
            refresh,
            &format!("{} · 刷新", data.status),
            11.0,
            if response.hovered() { ACCENT } else { MUTED },
        );
        if response.clicked() && !data.busy {
            self.menu = None;
            actions.push(Action::Refresh);
        }
        if count == 0 {
            return;
        }
        ui.painter().line_segment(
            [card.min + vec2(20.0, 56.0), card.min + vec2(460.0, 56.0)],
            egui::Stroke::new(1.0, DIVIDER),
        );
        let rows = rect(card.left() + 20.0, card.top() + 68.0, 440.0, height - 84.0);
        if let Some(view) = data.view {
            ui.scope_builder(egui::UiBuilder::new().max_rect(rows), |ui| {
                ui.spacing_mut().item_spacing.y = 0.0;
                egui::ScrollArea::vertical()
                    .id_salt(("task-rows", data.selected))
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for daily in &view.dailies {
                            let (row, _) =
                                ui.allocate_exact_size(vec2(440.0, ROW_HEIGHT), Sense::hover());
                            self.row_heading(ui, row, "日", &daily.name);
                            let chip = Rect::from_min_size(
                                row.min + vec2(181.0, 10.0),
                                vec2(CHIP_WIDTH, 36.0),
                            );
                            let response = self.chip(
                                ui,
                                chip,
                                &daily.label(),
                                Id::new(("daily", &daily.name)),
                                daily.enabled != Some(false),
                            );
                            if response.clicked() && !data.busy {
                                self.toggle(MenuKind::Daily(daily.name.clone()), chip);
                            }
                        }
                        for weekly in &view.weeklies {
                            let (row, _) =
                                ui.allocate_exact_size(vec2(440.0, ROW_HEIGHT), Sense::hover());
                            self.row_heading(ui, row, "周", &weekly.name);
                            let has_choices = weekly
                                .options
                                .as_ref()
                                .is_some_and(|options| !options.values.is_empty());
                            let start_width = if has_choices { 106.0 } else { CHIP_WIDTH };
                            let chip = Rect::from_min_size(
                                row.min + vec2(181.0, 10.0),
                                vec2(start_width, 36.0),
                            );
                            let response = self.chip(
                                ui,
                                chip,
                                start_label(weekly.start_day),
                                Id::new(("start", &weekly.name)),
                                true,
                            );
                            if response.clicked() && !data.busy {
                                self.toggle(MenuKind::Start(weekly.name.clone()), chip);
                            }
                            if has_choices {
                                let chip = Rect::from_min_size(
                                    row.min + vec2(295.0, 10.0),
                                    vec2(106.0, 36.0),
                                );
                                let response = self.chip(
                                    ui,
                                    chip,
                                    weekly.task.as_deref().unwrap_or("选择副本"),
                                    Id::new(("weekly", &weekly.name)),
                                    true,
                                );
                                if response.clicked() && !data.busy {
                                    self.toggle(MenuKind::Weekly(weekly.name.clone()), chip);
                                }
                            }
                        }
                    });
            });
        }
    }

    pub(super) fn row_heading(&self, ui: &Ui, row: Rect, badge: &str, name: &str) {
        let icon = Rect::from_min_size(row.min + vec2(12.0, 10.0), vec2(36.0, 36.0));
        ui.painter().rect_filled(icon, 10, ACCENT_SOFT);
        centered(ui, icon, badge, 13.0, ACCENT);
        label(
            ui,
            Rect::from_min_size(row.min + vec2(58.0, 15.0), vec2(112.0, 26.0)),
            name,
            14.0,
            TEXT,
        );
    }

    pub(super) fn chip(
        &self,
        ui: &mut Ui,
        bounds: Rect,
        text: &str,
        id: Id,
        active: bool,
    ) -> egui::Response {
        let response = ui.interact(bounds, id, Sense::click());
        panel(
            ui,
            bounds,
            10,
            if response.hovered() { HOVER } else { CONTROL },
        );
        label(
            ui,
            rect(
                bounds.left() + 12.0,
                bounds.top(),
                bounds.width() - 36.0,
                bounds.height(),
            ),
            text,
            13.0,
            if active { ACCENT } else { MUTED },
        );
        self.assets.icon(
            ui,
            "chevron_down",
            rect(bounds.right() - 24.0, bounds.top() + 10.0, 16.0, 16.0),
        );
        response.on_hover_text(text)
    }

    pub(super) fn popup(
        &mut self,
        ctx: &egui::Context,
        view: &ScriptView,
        actions: &mut Vec<Action>,
    ) {
        let Some(mut menu) = self.menu.clone() else {
            return;
        };
        let entries = menu_entries(view, &menu.kind);
        if entries.is_empty() {
            self.menu = None;
            return;
        }
        let left_width = (entries
            .iter()
            .map(|entry| {
                ctx.fonts_mut(|fonts| {
                    fonts
                        .layout_no_wrap(entry.label.clone(), egui::FontId::proportional(13.0), TEXT)
                        .size()
                        .x
                })
            })
            .fold(60.0, f32::max)
            + 34.0)
            .min(240.0);
        let children = menu
            .parent
            .and_then(|index| entries.get(index))
            .map(|entry| entry.children.as_slice())
            .unwrap_or(&[]);
        let width = left_width + 10.0 + if children.is_empty() { 0.0 } else { 204.0 };
        // Reserve space for every group so hovering never moves the popup.
        let rows = entries
            .iter()
            .fold(entries.len(), |rows, entry| rows.max(entry.children.len()));
        let desired = (rows as f32 * 32.0 + 8.0).min(360.0);
        let screen = ctx.content_rect();
        let bounds = popup_bounds(menu.anchor, vec2(width, desired), screen);
        let outside = ctx.input(|input| {
            input.key_pressed(egui::Key::Escape)
                || (input.pointer.any_pressed()
                    && input
                        .pointer
                        .interact_pos()
                        .is_some_and(|pos| !bounds.contains(pos) && !menu.anchor.contains(pos)))
        });
        if outside {
            self.menu = None;
            return;
        }
        let mut selected = None;
        let before = menu.parent;
        egui::Area::new(Id::new("task-popup"))
            .order(egui::Order::Foreground)
            .fixed_pos(bounds.min)
            .default_size(bounds.size())
            .constrain(false)
            .show(ctx, |ui| {
                // Area caches its last size; default_size only applies to its first frame.
                // Reuse the current popup bounds for both placement and clipping.
                ui.set_min_size(bounds.size());
                ui.set_max_size(bounds.size());
                egui::Frame::new()
                    .fill(CONTROL)
                    .stroke(egui::Stroke::new(1.0, BORDER))
                    .corner_radius(10)
                    .inner_margin(4)
                    .show(ui, |ui| {
                        ui.set_min_height(bounds.height() - 10.0);
                        ui.spacing_mut().item_spacing = vec2(4.0, 2.0);
                        ui.horizontal_top(|ui| {
                            egui::ScrollArea::vertical()
                                .id_salt("menu-primary")
                                .max_width(left_width)
                                .max_height(bounds.height() - 8.0)
                                .min_scrolled_height(0.0)
                                .show(ui, |ui| {
                                    ui.with_layout(
                                        egui::Layout::top_down(egui::Align::Min),
                                        |ui| {
                                            for (index, entry) in entries.iter().enumerate() {
                                                let response = menu_item(
                                                    ui,
                                                    &entry.label,
                                                    left_width,
                                                    Id::new(("primary", index)),
                                                    menu.parent == Some(index),
                                                    !entry.children.is_empty(),
                                                );
                                                if response.hovered() && !entry.children.is_empty()
                                                {
                                                    menu.parent = Some(index);
                                                }
                                                if response.clicked() {
                                                    if entry.children.is_empty() {
                                                        selected = Some(entry);
                                                    } else {
                                                        menu.parent = Some(index);
                                                    }
                                                }
                                            }
                                        },
                                    );
                                });
                            if !children.is_empty() {
                                egui::ScrollArea::vertical()
                                    .id_salt(("menu-children", before))
                                    .max_width(200.0)
                                    .max_height(bounds.height() - 8.0)
                                    .min_scrolled_height(0.0)
                                    .show(ui, |ui| {
                                        ui.with_layout(
                                            egui::Layout::top_down(egui::Align::Min),
                                            |ui| {
                                                for (index, entry) in children.iter().enumerate() {
                                                    if menu_item(
                                                        ui,
                                                        &entry.label,
                                                        200.0,
                                                        Id::new(("child", index)),
                                                        false,
                                                        false,
                                                    )
                                                    .clicked()
                                                    {
                                                        selected = Some(entry);
                                                    }
                                                }
                                            },
                                        );
                                    });
                            }
                        });
                    });
            });
        if let Some(entry) = selected {
            if let Some(request) = &entry.request {
                actions.push(Action::Request(Request {
                    method: request.method.clone(),
                    params: request.params.clone(),
                }));
            }
            self.menu = None;
        } else {
            if before != menu.parent {
                ctx.request_repaint();
            }
            self.menu = Some(menu);
        }
    }
}

fn menu_item(
    ui: &mut Ui,
    text: &str,
    width: f32,
    id: Id,
    selected: bool,
    children: bool,
) -> egui::Response {
    let (bounds, _) = ui.allocate_exact_size(vec2(width, 30.0), Sense::hover());
    let response = ui.interact(bounds, id, Sense::click());
    if response.hovered() || selected {
        ui.painter().rect_filled(bounds, 6, ACCENT_SOFT);
    }
    label(ui, bounds.shrink2(vec2(10.0, 0.0)), text, 13.0, TEXT);
    if children {
        centered(
            ui,
            rect(bounds.right() - 22.0, bounds.top(), 16.0, 30.0),
            "›",
            18.0,
            MUTED,
        );
    }
    response
}

fn popup_bounds(anchor: Rect, desired: Vec2, screen: Rect) -> Rect {
    let below = screen.bottom() - anchor.bottom() - 12.0;
    let above = anchor.top() - screen.top() - 12.0;
    let down = desired.y <= below || below >= above;
    let height = desired.y.min(if down { below } else { above }).max(0.0);
    let width = desired.x.min(screen.width() - 16.0);
    let x = anchor
        .left()
        .min(screen.right() - width - 8.0)
        .max(screen.left() + 8.0);
    let y = if down {
        anchor.bottom() + 4.0
    } else {
        anchor.top() - height - 4.0
    };
    Rect::from_min_size(pos2(x, y), vec2(width, height))
}

struct Entry {
    label: String,
    children: Vec<Entry>,
    request: Option<Request>,
}

fn leaf(label: String, method: &str, params: serde_json::Value) -> Entry {
    Entry {
        label,
        children: Vec::new(),
        request: Some(Request {
            method: method.into(),
            params,
        }),
    }
}

fn daily_entries(script: &str, daily: &Daily) -> Vec<Entry> {
    let mut entries = Vec::new();
    for choice in &daily.options.values {
        let params = |sequence| json!({"script_name": script, "daily_name": daily.name, "task_name": choice.display_name, "sequence": sequence});
        if let Some(options) = &choice.options {
            let children = options
                .values
                .iter()
                .map(|child| {
                    leaf(
                        child.display_name.clone(),
                        "daily.select",
                        params(child.physical_name.clone()),
                    )
                })
                .collect();
            if daily.has_single_group() {
                entries.extend(children);
            } else {
                entries.push(Entry {
                    label: choice.display_name.clone(),
                    children,
                    request: None,
                });
            }
        } else {
            entries.push(leaf(
                choice.display_name.clone(),
                "daily.select",
                params(serde_json::Value::Null),
            ));
        }
    }
    if daily.enabled.is_some() {
        entries.push(leaf(
            "不启用".into(),
            "daily.enable",
            json!({"script_name": script, "daily_name": daily.name, "enabled": false}),
        ));
    }
    entries
}

fn weekly_entries(script: &str, weekly: &Weekly, start: bool) -> Vec<Entry> {
    if start {
        (0..=7)
            .map(|day| {
                leaf(
                    start_label(Some(day)).into(),
                    "weekly.start",
                    json!({
                        "script_name": script, "weekly_name": weekly.name, "start_day": day
                    }),
                )
            })
            .collect()
    } else {
        weekly
            .options
            .as_ref()
            .map(|options| {
                options.values.iter().map(|choice|
            leaf(choice.display_name.clone(), "weekly.select", json!({
                "script_name": script, "weekly_name": weekly.name, "task_name": choice.display_name
            }))
        ).collect()
            })
            .unwrap_or_default()
    }
}

fn menu_entries(view: &ScriptView, kind: &MenuKind) -> Vec<Entry> {
    match kind {
        MenuKind::Daily(name) => view
            .dailies
            .iter()
            .find(|daily| &daily.name == name)
            .map(|daily| daily_entries(&view.script.script_name, daily))
            .unwrap_or_default(),
        MenuKind::Weekly(name) | MenuKind::Start(name) => view
            .weeklies
            .iter()
            .find(|weekly| &weekly.name == name)
            .map(|weekly| {
                weekly_entries(
                    &view.script.script_name,
                    weekly,
                    matches!(kind, MenuKind::Start(_)),
                )
            })
            .unwrap_or_default(),
    }
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/controllers/task_card.rs"]
mod tests;
