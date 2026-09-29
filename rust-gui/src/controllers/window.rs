use super::*;

impl View {
    pub(super) fn window_controls(
        &mut self,
        ui: &mut Ui,
        screen: Rect,
        data: &Presentation<'_>,
        actions: &mut Vec<Action>,
    ) {
        let dx = screen.width() - SIZE.x;
        let window = rect(1136.0 + dx, 16.0, 128.0, 44.0);
        panel(ui, window, 14, PANEL);
        for (index, (icon, hint)) in [("settings", "配置"), ("min", "最小化"), ("close", "关闭")]
            .iter()
            .enumerate()
        {
            let bounds = rect(window.left() + 6.0 + index as f32 * 40.0, 22.0, 36.0, 32.0);
            if self.icon_button(ui, icon, bounds, hint, true) && (index != 0 || !data.busy) {
                match index {
                    0 => actions.push(Action::Request(Request {
                        method: "settings.view".into(),
                        params: json!({}),
                    })),
                    1 => ui
                        .ctx()
                        .send_viewport_cmd(egui::ViewportCommand::Minimized(true)),
                    _ if data.block_close => self.toast("操作进行中，请等待完成后关闭"),
                    _ => ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close),
                }
            }
        }
        let badge = rect(128.0, 24.0, if data.demo { 186.0 } else { 154.0 }, 28.0);
        panel(ui, badge, 9, PANEL);
        centered(
            ui,
            badge,
            if data.demo {
                "Rust 预览 · 演示配置"
            } else {
                "Rust 界面预览"
            },
            11.0,
            MUTED,
        );
        if ui
            .interact(badge, Id::new("diagnostics"), Sense::click())
            .on_hover_text("连接诊断")
            .clicked()
        {
            actions.push(Action::Diagnostics);
        }
    }
}
