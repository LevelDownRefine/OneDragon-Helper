//! One persistent JSONL session. Only this module owns the Python child.
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::VecDeque,
    io::{BufRead, BufReader, Read, Write},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

const MAX_LINE: u64 = 8 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize)]
pub struct Failure {
    pub code: String,
    pub message: String,
    pub refresh_required: bool,
}

impl Failure {
    pub fn transport(message: impl Into<String>) -> Self {
        Self {
            code: "transport_failed".into(),
            message: message.into(),
            refresh_required: true,
        }
    }
}

fn decode_response(line: &str, id: u64) -> Result<Value, Failure> {
    let envelope: Value = serde_json::from_str(line)
        .map_err(|err| Failure::transport(format!("CLI 返回了无效 JSON：{err}")))?;
    let object = envelope
        .as_object()
        .ok_or_else(|| Failure::transport("CLI 响应不是对象"))?;
    if object.len() != 3
        || object.get("protocol_version") != Some(&json!(1))
        || object.get("id") != Some(&json!(id))
        || object.contains_key("result") == object.contains_key("error")
    {
        return Err(Failure::transport("CLI 响应版本、请求编号或字段不匹配"));
    }
    if let Some(error) = object.get("error") {
        return Err(serde_json::from_value(error.clone())
            .map_err(|err| Failure::transport(format!("CLI 错误响应无效：{err}")))?);
    }
    Ok(object["result"].clone())
}

pub struct Session {
    child: Child,
    stdin: Option<ChildStdin>,
    lines: mpsc::Receiver<Result<String, String>>,
    readers: Vec<JoinHandle<()>>,
    diagnostics: Arc<Mutex<VecDeque<String>>>,
    next_id: u64,
    usable: bool,
}

impl Session {
    pub fn spawn(mut command: Command) -> Result<Self, Failure> {
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW for the CLI helper.
        }
        let mut child = command
            .spawn()
            .map_err(|err| Failure::transport(format!("无法启动 Python CLI：{err}")))?;
        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");
        let stderr = child.stderr.take().expect("piped stderr");
        let (tx, lines) = mpsc::sync_channel(8);
        let reader = thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                let result = reader.by_ref().take(MAX_LINE + 1).read_line(&mut line);
                let event = match result {
                    Ok(0) => Err("CLI 进程已退出，请刷新重连".into()),
                    Ok(size) if size as u64 > MAX_LINE => Err("CLI 响应超过 8 MiB".into()),
                    Ok(_) => Ok(line),
                    Err(err) => Err(format!("读取 CLI 响应失败：{err}")),
                };
                let failed = event.is_err();
                if tx.send(event).is_err() || failed {
                    break;
                }
            }
        });
        let diagnostics = Arc::new(Mutex::new(VecDeque::new()));
        let tail = diagnostics.clone();
        let stderr_reader = thread::spawn(move || {
            let mut reader = stderr;
            let mut bytes = [0; 2048];
            loop {
                match reader.read(&mut bytes) {
                    Ok(0) => break,
                    Ok(count) => {
                        let message = String::from_utf8_lossy(&bytes[..count]).into_owned();
                        log::debug!("CLI: {message}");
                        let mut tail = tail.lock().expect("diagnostics mutex");
                        tail.push_back(message);
                        while tail.len() > 8 {
                            tail.pop_front();
                        }
                    }
                    Err(err) => {
                        log::warn!("读取 CLI stderr 失败：{err}");
                        break;
                    }
                }
            }
        });
        Ok(Self {
            child,
            stdin: Some(stdin),
            lines,
            readers: vec![reader, stderr_reader],
            diagnostics,
            next_id: 1,
            usable: true,
        })
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    pub fn request(
        &mut self,
        method: &str,
        params: Value,
        timeout: Duration,
        stop: &AtomicBool,
    ) -> Result<Value, Failure> {
        if !self.usable {
            return Err(Failure::transport("连接已失效，请刷新重连"));
        }
        let id = self.next_id;
        self.next_id += 1;
        let mut payload = serde_json::to_vec(&json!({
            "protocol_version": 1, "id": id, "method": method, "params": params
        }))
        .expect("serializable JSON request");
        payload.push(b'\n');
        let result = self.exchange(&payload, id, timeout, stop);
        if matches!(&result, Err(failure) if failure.code == "transport_failed") {
            self.usable = false;
        }
        result
    }

    fn exchange(
        &mut self,
        payload: &[u8],
        id: u64,
        timeout: Duration,
        stop: &AtomicBool,
    ) -> Result<Value, Failure> {
        // One outstanding, small request prevents a full stdin pipe from blocking shutdown.
        if payload.len() > 4096 {
            return Err(Failure::transport("请求超过 4 KiB"));
        }
        self.stdin
            .as_mut()
            .expect("open session stdin")
            .write_all(payload)
            .map_err(|err| Failure::transport(format!("发送 CLI 请求失败：{err}")))?;
        let deadline = Instant::now() + timeout;
        loop {
            if stop.load(Ordering::Relaxed) {
                return Err(Failure::transport("界面已关闭"));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(Failure::transport("CLI 请求超时；请刷新确认实际保存状态"));
            }
            match self
                .lines
                .recv_timeout(remaining.min(Duration::from_millis(50)))
            {
                Ok(Ok(line)) => return decode_response(&line, id),
                Ok(Err(message)) => return Err(Failure::transport(message)),
                Err(mpsc::RecvTimeoutError::Timeout) => continue,
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    return Err(Failure::transport("CLI 响应管道已关闭"));
                }
            }
        }
    }

    pub fn diagnostics(&self) -> String {
        self.diagnostics
            .lock()
            .expect("diagnostics mutex")
            .iter()
            .cloned()
            .collect()
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.stdin.take();
        let deadline = Instant::now() + Duration::from_millis(300);
        loop {
            match self.child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
                result => {
                    if let Err(err) = result {
                        log::warn!("读取 CLI 退出状态失败：{err}");
                    }
                    if let Err(err) = self.child.kill() {
                        log::warn!("结束 CLI 失败：{err}");
                    }
                    if let Err(err) = self.child.wait() {
                        log::warn!("回收 CLI 失败：{err}");
                    }
                    break;
                }
            }
        }
        // Disconnect first: even an unsolicited-response flood must not block joining.
        let (_, empty) = mpsc::channel();
        drop(std::mem::replace(&mut self.lines, empty));
        for reader in self.readers.drain(..) {
            if reader.join().is_err() {
                log::error!("CLI 管道读取线程异常退出");
            }
        }
    }
}

pub struct Request {
    pub method: String,
    pub params: Value,
}
pub struct Reply {
    pub method: String,
    pub result: Result<Value, Failure>,
    pub diagnostics: String,
    pub pid: u32,
}

pub struct Backend {
    pub requests: mpsc::Sender<Request>,
    pub replies: mpsc::Receiver<Reply>,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl Backend {
    pub fn start(command: Command, repaint: impl Fn() + Send + 'static) -> Self {
        let (requests, incoming) = mpsc::channel::<Request>();
        let (outgoing, replies) = mpsc::channel();
        let stop = Arc::new(AtomicBool::new(false));
        let cancelled = stop.clone();
        let worker = thread::spawn(move || {
            let mut session = match Session::spawn(command) {
                Ok(session) => session,
                Err(error) => {
                    let _ = outgoing.send(Reply {
                        method: "app.snapshot".into(),
                        result: Err(error),
                        diagnostics: String::new(),
                        pid: 0,
                    });
                    repaint();
                    return;
                }
            };
            while !cancelled.load(Ordering::Relaxed) {
                match incoming.recv_timeout(Duration::from_millis(50)) {
                    Ok(request) => {
                        let result = session.request(
                            &request.method,
                            request.params,
                            Duration::from_secs(15),
                            &cancelled,
                        );
                        let broken =
                            matches!(&result, Err(error) if error.code == "transport_failed");
                        let sent = outgoing
                            .send(Reply {
                                method: request.method,
                                result,
                                diagnostics: session.diagnostics(),
                                pid: session.pid(),
                            })
                            .is_ok();
                        repaint();
                        if !sent || broken {
                            break;
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => match session.child.try_wait() {
                        Ok(None) => continue,
                        state => {
                            let detail = match state {
                                Ok(Some(status)) => format!("CLI 进程已退出：{status}，请刷新重连"),
                                Err(error) => format!("无法查询 CLI 进程状态：{error}"),
                                Ok(None) => unreachable!(),
                            };
                            let _ = outgoing.send(Reply {
                                method: "session".into(),
                                result: Err(Failure::transport(detail)),
                                diagnostics: session.diagnostics(),
                                pid: session.pid(),
                            });
                            repaint();
                            break;
                        }
                    },
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
        });
        Self {
            requests,
            replies,
            stop,
            worker: Some(worker),
        }
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if self.worker.take().expect("backend worker").join().is_err() {
            log::error!("CLI 后台线程异常退出");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_wrong_ids_versions_and_ambiguous_envelopes() {
        for response in [
            json!({"protocol_version": 1, "id": 2, "result": {}}),
            json!({"protocol_version": true, "id": 1, "result": {}}),
            json!({"protocol_version": 1, "id": 1, "result": {}, "error": {}}),
            json!({"protocol_version": 1, "id": 1}),
        ] {
            assert_eq!(
                decode_response(&response.to_string(), 1).unwrap_err().code,
                "transport_failed"
            );
        }
    }
}
