//! One decoder worker with a latest-frame slot; no audio stream is selected.
use eframe::egui;
use std::{
    path::PathBuf,
    sync::{Arc, Condvar, Mutex},
    time::{Duration, Instant},
};

pub struct Frame {
    pub image: egui::ColorImage,
    pub jpeg: Option<Vec<u8>>,
}

pub struct Output {
    pub generation: u64,
    pub result: Result<Frame, String>,
}

#[derive(Default)]
struct State {
    generation: u64,
    request: Option<PathBuf>,
    output: Option<Output>,
    stopped: bool,
}

struct Shared {
    state: Mutex<State>,
    changed: Condvar,
}

pub struct Player(Arc<Shared>);

impl Player {
    pub fn new(ctx: egui::Context) -> Self {
        let shared = Arc::new(Shared {
            state: Mutex::new(State::default()),
            changed: Condvar::new(),
        });
        let worker = shared.clone();
        std::thread::spawn(move || {
            loop {
                let (generation, path) = {
                    let mut state = worker.state.lock().expect("video state");
                    while state.request.is_none() && !state.stopped {
                        state = worker.changed.wait(state).expect("video wait");
                    }
                    if state.stopped {
                        break;
                    }
                    (
                        state.generation,
                        state.request.take().expect("video request"),
                    )
                };
                if !worker.wait_until(generation, Instant::now() + Duration::from_millis(500)) {
                    continue;
                }
                if let Err(error) = play(&worker, &ctx, generation, &path) {
                    worker.publish(
                        &ctx,
                        Output {
                            generation,
                            result: Err(error),
                        },
                    );
                }
            }
        });
        Self(shared)
    }

    pub fn set(&self, generation: u64, path: Option<PathBuf>) {
        let mut state = self.0.state.lock().expect("video state");
        state.generation = generation;
        state.request = path;
        state.output = None;
        self.0.changed.notify_one();
    }

    pub fn poll(&self) -> Option<Output> {
        self.0.state.lock().expect("video state").output.take()
    }
}

impl Drop for Player {
    fn drop(&mut self) {
        self.0.state.lock().expect("video state").stopped = true;
        self.0.changed.notify_one();
        // A system decoder may be inside ReadSample. It owns its COM objects and releases them
        // on return; never join that call on the UI thread. Process exit also closes its handles.
    }
}

impl Shared {
    #[cfg(windows)]
    fn active(&self, generation: u64) -> bool {
        let state = self.state.lock().expect("video state");
        !state.stopped && state.generation == generation
    }

    fn wait_until(&self, generation: u64, deadline: Instant) -> bool {
        let mut state = self.state.lock().expect("video state");
        while !state.stopped && state.generation == generation {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return true;
            }
            state = self
                .changed
                .wait_timeout(state, remaining)
                .expect("video wait")
                .0;
        }
        false
    }

    fn publish(&self, ctx: &egui::Context, mut output: Output) {
        let mut state = self.state.lock().expect("video state");
        if !state.stopped && state.generation == output.generation {
            // Keep the first-frame cache until the UI consumes it, even when frames are dropped.
            if let (Some(previous), Ok(frame)) = (state.output.as_mut(), output.result.as_mut())
                && let Ok(previous) = &mut previous.result
                && frame.jpeg.is_none()
            {
                frame.jpeg = previous.jpeg.take();
            }
            state.output = Some(output);
            ctx.request_repaint();
        }
    }
}

#[cfg(windows)]
fn play(
    shared: &Shared,
    ctx: &egui::Context,
    generation: u64,
    path: &std::path::Path,
) -> Result<(), String> {
    let _runtime = native::Runtime::new()?;
    let mut decoder = native::Decoder::open(path)?;
    let mut origin = Instant::now();
    let mut first_timestamp = None;
    let mut first_frame = true;
    let mut frames_in_loop = 0;
    let mut last_due = Duration::ZERO;
    while shared.active(generation) {
        let Some((timestamp, image)) = decoder.next()? else {
            if frames_in_loop == 0 {
                return Err("视频没有可解码的画面".into());
            }
            // Include the final frame's duration so very short videos do not spin at EOF.
            if !shared.wait_until(generation, origin + last_due + decoder.frame_duration()) {
                break;
            }
            decoder.rewind()?;
            origin = Instant::now();
            first_timestamp = None;
            frames_in_loop = 0;
            continue;
        };
        if first_timestamp.is_none() {
            origin = Instant::now();
        }
        let first = *first_timestamp.get_or_insert(timestamp);
        let ticks = timestamp.saturating_sub(first).max(0) as u64;
        let due = Duration::from_nanos(ticks.saturating_mul(100));
        if !shared.wait_until(generation, origin + due) {
            break;
        }
        let jpeg = if first_frame {
            let mut bytes = Vec::new();
            image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 90)
                .encode_image(&image)
                .map_err(|e| e.to_string())?;
            first_frame = false;
            Some(bytes)
        } else {
            None
        };
        let size = [image.width() as usize, image.height() as usize];
        shared.publish(
            ctx,
            Output {
                generation,
                result: Ok(Frame {
                    image: egui::ColorImage::from_rgb(size, &image),
                    jpeg,
                }),
            },
        );
        frames_in_loop += 1;
        last_due = due;
    }
    Ok(())
}

#[cfg(not(windows))]
fn play(
    _shared: &Shared,
    _ctx: &egui::Context,
    _generation: u64,
    _path: &std::path::Path,
) -> Result<(), String> {
    Err("视频壁纸目前仅支持 Windows，请选择图片".into())
}

#[cfg(windows)]
#[path = "windows/video.rs"]
mod native;

#[cfg(test)]
#[path = "../tests/video.rs"]
mod tests;
