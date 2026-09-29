use super::super::*;
use super::*;

impl View {
    pub(in crate::main_window) fn enabled_names(&self, scripts: &[Script]) -> Vec<String> {
        scripts
            .iter()
            .filter(|script| !self.disabled.contains(&script.script_name))
            .map(|script| script.script_name.clone())
            .collect()
    }

    pub(in crate::main_window) fn reconcile_scripts(&mut self, scripts: &[Script]) {
        self.disabled
            .retain(|name| scripts.iter().any(|script| &script.script_name == name));
    }

    pub(in crate::main_window) fn rename_script(&mut self, old: &str, new: &str) {
        if self.disabled.remove(old) {
            self.disabled.insert(new.into());
        }
    }

    pub(super) fn sidebar(
        &mut self,
        ui: &mut Ui,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) {
        let height = ui.max_rect().height();
        let mut drop_index = None;
        if ui.input(|input| input.key_pressed(egui::Key::Escape)) {
            self.dragging = None;
        }
        ui.painter().rect_filled(
            rect(0.0, 0.0, 80.0, height),
            egui::CornerRadius {
                nw: 16,
                sw: 16,
                ne: 0,
                se: 0,
            },
            egui::Color32::from_rgba_unmultiplied(16, 25, 41, 230),
        );
        ui.painter().line_segment(
            [pos2(79.0, 0.0), pos2(79.0, height)],
            egui::Stroke::new(1.0, BORDER),
        );
        ui.scope_builder(
            egui::UiBuilder::new().max_rect(rect(0.0, 20.0, 80.0, height - 160.0)),
            |ui| {
                ui.spacing_mut().item_spacing.y = 0.0;
                egui::ScrollArea::vertical()
                    .id_salt("script-list")
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for (index, script) in data.scripts.iter().enumerate() {
                            let (row, _) = ui.allocate_exact_size(vec2(80.0, 64.0), Sense::hover());
                            let button =
                                Rect::from_min_size(row.min + vec2(12.0, 0.0), vec2(56.0, 56.0));
                            let active = data.selected == Some(script.script_name.as_str());
                            let response = ui.interact(
                                button,
                                Id::new(("script", &script.script_name)),
                                Sense::click_and_drag(),
                            );
                            if active {
                                ui.painter().rect_filled(
                                    rect(3.0, button.top() + 16.0, 3.0, 24.0),
                                    2,
                                    ACCENT,
                                );
                                panel(ui, button, 16, ACCENT_SOFT);
                                ui.painter().rect_stroke(
                                    button,
                                    16,
                                    egui::Stroke::new(1.0, ACCENT),
                                    egui::StrokeKind::Inside,
                                );
                            } else if response.hovered() {
                                ui.painter().rect_filled(button, 16, CONTROL);
                            }
                            let bounds = Rect::from_center_size(button.center(), vec2(40.0, 40.0));
                            if ui.is_rect_visible(button) {
                                let size = if ui.ctx().pixels_per_point() > 1.6 {
                                    256
                                } else {
                                    64
                                };
                                let texture =
                                    self.icons.get(script.icon_path.as_deref(), size).or_else(
                                        || self.icons.get(self.default_icon_path.as_deref(), size),
                                    );
                                if let Some(texture) = texture {
                                    egui::Image::new(&texture).paint_at(ui, bounds);
                                } else {
                                    self.assets.icon(ui, "script", bounds);
                                }
                            }
                            if self.disabled.contains(&script.script_name) {
                                ui.painter().rect_filled(
                                    button.shrink(4.0),
                                    10,
                                    egui::Color32::from_black_alpha(150),
                                );
                            }
                            if response.drag_started() && !data.busy {
                                self.dragging = Some(script.script_name.clone());
                                self.menu = None;
                            }
                            if self.dragging.is_some()
                                && ui.input(|input| {
                                    input.pointer.interact_pos().is_some_and(|pos| {
                                        button.contains(pos) && ui.clip_rect().contains(pos)
                                    })
                                })
                            {
                                drop_index = Some(index);
                                ui.painter().rect_stroke(
                                    button,
                                    16,
                                    egui::Stroke::new(2.0, ACCENT),
                                    egui::StrokeKind::Inside,
                                );
                            }
                            if response.clicked() && !data.busy {
                                self.menu = None;
                                if self.control_mode {
                                    if !self.disabled.remove(&script.script_name) {
                                        self.disabled.insert(script.script_name.clone());
                                    }
                                } else {
                                    actions.push(Action::Select(script.script_name.clone()));
                                }
                            }
                            response.context_menu(|ui| {
                                ui.label(&script.display_name);
                                if ui
                                    .add_enabled(
                                        !data.busy && data.scripts.len() > 1,
                                        egui::Button::new(
                                            egui::RichText::new("删除脚本…").color(DANGER),
                                        ),
                                    )
                                    .on_hover_text("从助手列表移除，保留脚本文件")
                                    .clicked()
                                {
                                    actions.push(Action::RemoveScript(script.script_name.clone()));
                                    ui.close();
                                }
                            });
                            response.on_hover_text(format!(
                                "{}\n右键管理 · 拖动排序或删除",
                                script.display_name
                            ));
                        }
                    });
            },
        );
        let base = height - 120.0;
        ui.painter().line_segment(
            [pos2(12.0, base), pos2(68.0, base)],
            egui::Stroke::new(1.0, DIVIDER),
        );
        let grid = rect(16.0, base + 8.0, 48.0, 48.0);
        panel(
            ui,
            grid,
            14,
            if self.control_mode {
                ACCENT_SOFT
            } else {
                CONTROL
            },
        );
        if self.dragging.is_some() {
            let target = rect(12.0, base + 4.0, 252.0, 56.0);
            let hovered = ui.input(|input| {
                input
                    .pointer
                    .interact_pos()
                    .is_some_and(|pos| target.contains(pos))
            });
            ui.painter().rect(
                target,
                12,
                if hovered {
                    DANGER_FILL
                } else {
                    egui::Color32::from_rgb(55, 29, 40)
                },
                egui::Stroke::new(if hovered { 2.0 } else { 1.0 }, DANGER),
                egui::StrokeKind::Inside,
            );
            centered(
                ui,
                rect(target.left(), target.top() + 5.0, target.width(), 24.0),
                if hovered {
                    "松开以删除脚本"
                } else {
                    "拖到这里删除脚本"
                },
                15.0,
                DANGER,
            );
            centered(
                ui,
                rect(target.left(), target.top() + 30.0, target.width(), 18.0),
                "从助手列表移除 · 保留脚本文件",
                11.0,
                MUTED,
            );
            if ui.input(|input| input.pointer.any_released()) {
                let name = self.dragging.take().expect("active drag");
                if !data.busy {
                    if ui.input(|input| {
                        input
                            .pointer
                            .interact_pos()
                            .is_some_and(|pos| target.contains(pos))
                    }) {
                        actions.push(Action::RemoveScript(name));
                    } else if let Some(index) = drop_index {
                        let mut names: Vec<String> = data
                            .scripts
                            .iter()
                            .map(|script| script.script_name.clone())
                            .collect();
                        if let Some(source) = names.iter().position(|candidate| candidate == &name)
                            && source != index
                        {
                            names.remove(source);
                            names.insert(index, name);
                            actions.push(Action::Request(Request {
                                method: "script.reorder".into(),
                                params: json!({"script_names":names}),
                            }));
                        }
                    }
                }
            }
        } else if self.icon_button(ui, "grid", grid, "选择手动运行的脚本", true) && !data.busy
        {
            self.control_mode = !self.control_mode;
            self.menu = None;
            if self.control_mode {
                self.toast("手动选择：点击图标勾选，不影响每日计划");
            }
        }
        let bubble = rect(92.0, base + 2.0, 156.0, 60.0);
        if self.control_mode && self.dragging.is_none() {
            panel(ui, bubble, 16, PANEL);
            for (index, text) in ["全", "清", "＋"].iter().enumerate() {
                let bounds = rect(
                    bubble.left() + 16.0 + 44.0 * index as f32,
                    bubble.top() + 12.0,
                    36.0,
                    36.0,
                );
                panel(ui, bounds, 10, CONTROL);
                centered(ui, bounds, text, 16.0, TEXT);
                if ui
                    .interact(bounds, Id::new(("manual-action", index)), Sense::click())
                    .clicked()
                    && !data.busy
                {
                    match index {
                        0 => self.disabled.clear(),
                        1 => {
                            self.disabled = data
                                .scripts
                                .iter()
                                .map(|script| script.script_name.clone())
                                .collect()
                        }
                        2 => {
                            self.control_mode = false;
                            actions.push(Action::AddScript);
                        }
                        _ => unreachable!(),
                    }
                }
            }
            if ui.input(|input| {
                input.key_pressed(egui::Key::Escape)
                    || (input.pointer.any_click()
                        && input
                            .pointer
                            .interact_pos()
                            .is_some_and(|pos| pos.x > 80.0 && !bubble.contains(pos)))
            }) {
                self.control_mode = false;
            }
        }
        let batch = rect(16.0, base + 64.0, 48.0, 48.0);
        ui.painter().circle_filled(batch.center(), 24.0, BATCH);
        if self.icon_button(ui, "play_all", batch, "启动手动勾选的脚本", false) && !data.busy
        {
            let names = self.enabled_names(data.scripts);
            if names.is_empty() {
                self.toast("没有勾选手动运行的脚本");
            } else {
                actions.push(Action::Request(Request {
                    method: "run.view".into(),
                    params: json!({"script_names":names}),
                }));
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn can_drop(&self) -> bool {
        !self.busy
            && self.backend.is_some()
            && self.view.is_some()
            && self.editor.is_none()
            && self.list_dialog.is_none()
            && self.run_dialog.is_none()
            && self.settings_dialog.is_none()
            && self.backup_dialog.is_none()
            && self.update_dialog.is_none()
            && self.startup_dialog.is_none()
            && self.drop_dialog.is_none()
            && self.wallpaper_dialog.is_none()
    }

    pub(in crate::main_window) fn start_drop(&mut self, paths: Result<Vec<PathBuf>, String>) {
        if !self.can_drop() {
            self.ui.toast("对话框打开或操作进行中，本次拖入已忽略");
            return;
        }
        match paths.and_then(DropDialog::new) {
            Ok(dialog) => {
                self.ui.close_menu();
                self.drop_dialog = Some(dialog);
            }
            Err(error) => self.ui.toast(error),
        }
    }

    pub(in crate::main_window) fn receive_drop(&mut self, result: Result<Value, Failure>) {
        let dialog = self.drop_dialog.as_mut().expect("drop in progress");
        if dialog.receive(result) {
            self.backend = None;
            self.view = None;
            self.status = "导入连接中断 · 请刷新核对".into();
        }
        if !dialog.active() && self.backend.is_some() {
            self.request("app.snapshot", json!({}));
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_script_config(&mut self, ui: &mut Ui) {
        if let Some(action) = self
            .editor
            .as_mut()
            .and_then(|editor| editor.show(ui.ctx(), self.busy))
        {
            match action {
                EditAction::Cancel => {
                    self.editor = None;
                    self.open_editor_after_snapshot = false;
                    if self.view.is_none() && self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                }
                EditAction::Reload => {
                    self.open_editor_after_snapshot = true;
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    } else {
                        self.connect();
                    }
                }
                EditAction::Save(request) => {
                    self.error = None;
                    self.request(&request.method, request.params);
                }
            }
        }
    }
}

impl App {
    pub(in crate::main_window) fn show_script_list(&mut self, ui: &mut Ui) {
        if let Some(action) = self
            .list_dialog
            .as_mut()
            .and_then(|dialog| dialog.show(ui.ctx(), self.busy))
        {
            match action {
                ListAction::Request(request) => {
                    self.error = None;
                    self.request(&request.method, request.params);
                }
                ListAction::Cancel => {
                    self.list_dialog = None;
                    if self.view.is_none() && self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    }
                }
                ListAction::Refresh => {
                    self.list_dialog = None;
                    if self.backend.is_some() {
                        self.request("app.snapshot", json!({}));
                    } else {
                        self.connect();
                    }
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "../../../tests/rust-gui/controllers/game_list.rs"]
mod tests;

impl App {
    pub(in crate::main_window) fn receive_script_edit(&mut self, method: &str, result: Value) {
        if method == "script.edit_view" {
            match serde_json::from_value::<EditView>(result) {
                Ok(data) if Some(&data.script_name) == self.selected.as_ref() => {
                    self.editor = Some(ScriptEditor::new(data));
                    self.status = "已同步".into();
                }
                _ => self.fail(Failure::transport("脚本配置数据无效")),
            }
        } else if matches!(method, "script.edit_save" | "script.add") {
            #[derive(serde::Deserialize)]
            struct Saved {
                script_name: String,
            }
            match serde_json::from_value::<Saved>(result) {
                Ok(saved) if !saved.script_name.is_empty() => {
                    if method == "script.edit_save"
                        && let Some(old) = &self.selected
                    {
                        self.ui.rename_script(old, &saved.script_name);
                    }
                    self.selected = Some(saved.script_name);
                    self.editor = None;
                    self.list_dialog = None;
                    self.view = None;
                    self.write_confirmed = true;
                    self.ui.toast("配置已保存");
                    self.request("app.snapshot", json!({}));
                }
                _ => self.fail(Failure::transport("脚本保存响应无效，请刷新核对")),
            }
        } else if matches!(method, "script.remove" | "script.reorder") && result.is_null() {
            self.list_dialog = None;
            self.write_confirmed = true;
            self.ui.toast("列表已保存");
            self.request("app.snapshot", json!({}));
        } else {
            self.fail(Failure::transport("写操作响应无效"));
        }
    }
}
