//! Standalone confirmation only. The Python post-run action owns actual shutdown.
use crate::{main_window::install_font, theme};
use eframe::egui;
use std::{
    ffi::OsString,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

const CONFIRMED: i32 = 42;

struct Countdown {
    seconds: u64,
    started: Option<Instant>,
    decision: Option<bool>,
}

impl Countdown {
    fn show(&mut self, ui: &mut egui::Ui, now: Instant, closing: bool) {
        let started = *self.started.get_or_insert(now);
        let remaining = self
            .seconds
            .saturating_sub(now.duration_since(started).as_secs());
        ui.vertical_centered(|ui| {
            ui.add_space(20.0);
            ui.heading("即将关机");
            ui.add_space(14.0);
            ui.label(format!("系统将在 {remaining} 秒后关机"));
            ui.add_space(18.0);
            let (cancel, confirm) = ui
                .horizontal(|ui| {
                    ui.add_space((ui.available_width() - 224.0).max(0.0) / 2.0);
                    let cancel = ui
                        .add_sized([104.0, 34.0], egui::Button::new("取消关机"))
                        .clicked();
                    let confirm = ui
                        .add_sized(
                            [104.0, 34.0],
                            egui::Button::new("立即关机").fill(theme::PRIMARY),
                        )
                        .clicked();
                    (cancel, confirm)
                })
                .inner;
            // Closing or cancelling wins even when the same frame reaches zero.
            if self.decision.is_none() {
                if closing || cancel || ui.input(|input| input.key_pressed(egui::Key::Escape)) {
                    self.decision = Some(false);
                } else if confirm || remaining == 0 {
                    self.decision = Some(true);
                }
            }
        });
    }
}

struct ShutdownApp {
    countdown: Countdown,
    confirmed: Arc<AtomicBool>,
    #[cfg(feature = "capture")]
    capture: Option<std::path::PathBuf>,
    #[cfg(feature = "capture")]
    captured: bool,
}

impl eframe::App for ShutdownApp {
    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        theme::CANVAS.to_normalized_gamma_f32()
    }

    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        #[cfg(feature = "capture")]
        if let Some(path) = &self.capture {
            for event in ctx.input(|input| input.events.clone()) {
                if let egui::Event::Screenshot { image, .. } = event {
                    let bytes: Vec<u8> = image.pixels.iter().flat_map(|p| p.to_array()).collect();
                    if let Err(error) = image::save_buffer(
                        path,
                        &bytes,
                        image.size[0] as u32,
                        image.size[1] as u32,
                        image::ColorType::Rgba8,
                    ) {
                        log::error!("保存截图失败：{error}");
                    }
                    self.countdown.decision = Some(false);
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
        }
        ctx.request_repaint_after(Duration::from_millis(100));
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let closing = ui.input(|input| input.viewport().close_requested());
        self.countdown.show(ui, Instant::now(), closing);
        if let Some(confirmed) = self.countdown.decision {
            self.confirmed.store(confirmed, Ordering::SeqCst);
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
        }
        #[cfg(feature = "capture")]
        if self.capture.is_some() && !self.captured {
            self.captured = true;
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
        }
    }
}

pub fn run(args: Vec<OsString>) -> Result<i32, String> {
    let mut args = args.into_iter();
    let seconds = args
        .next()
        .and_then(|value| value.to_str().and_then(|value| value.parse::<u64>().ok()))
        .filter(|seconds| (1..=86400).contains(seconds))
        .ok_or("关机倒计时须为 1～86400 秒")?;
    #[cfg(feature = "capture")]
    let capture = {
        let mut capture = None;
        if let Some(arg) = args.next() {
            if arg != "--capture" {
                return Err("未知的关机确认参数".into());
            }
            capture = Some(args.next().ok_or("--capture 缺少路径")?.into());
        }
        capture
    };
    if args.next().is_some() {
        return Err("未知的关机确认参数".into());
    }
    let confirmed = Arc::new(AtomicBool::new(false));
    let outcome = Arc::clone(&confirmed);
    eframe::run_native(
        "OneDragon · 即将关机",
        crate::rendering::options(
            egui::ViewportBuilder::default()
                .with_inner_size([420.0, 240.0])
                .with_resizable(false)
                .with_always_on_top(),
        ),
        Box::new(move |cc| {
            theme::configure(&cc.egui_ctx);
            install_font(&cc.egui_ctx, None).map_err(std::io::Error::other)?;
            Ok(Box::new(ShutdownApp {
                countdown: Countdown {
                    seconds,
                    started: None,
                    decision: None,
                },
                confirmed,
                #[cfg(feature = "capture")]
                capture,
                #[cfg(feature = "capture")]
                captured: false,
            }))
        }),
    )
    .map_err(|error| error.to_string())?;
    Ok(if outcome.load(Ordering::SeqCst) {
        CONFIRMED
    } else {
        0
    })
}

#[cfg(test)]
#[path = "../../tests/rust-gui/shutdown_dialog.rs"]
mod tests;
