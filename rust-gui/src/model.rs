use serde::Deserialize;
use serde_json::Value;

#[derive(Clone, Debug, Deserialize)]
pub struct Script {
    pub script_name: String,
    pub display_name: String,
    pub script_path: String,
    pub adapted: bool,
    pub icon_path: Option<std::path::PathBuf>,
}

#[derive(Debug, Deserialize)]
pub struct Snapshot {
    pub scripts: Vec<Script>,
    pub default_icon_path: Option<std::path::PathBuf>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Options {
    pub values: Vec<Choice>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Choice {
    pub display_name: String,
    pub physical_name: Value,
    pub options: Option<Options>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Daily {
    pub name: String,
    pub options: Options,
    pub task: Option<String>,
    pub sequence: Value,
    pub enabled: Option<bool>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Weekly {
    pub name: String,
    pub options: Option<Options>,
    pub task: Option<String>,
    pub start_day: Option<u8>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ScriptView {
    pub script: Script,
    pub dailies: Vec<Daily>,
    pub weeklies: Vec<Weekly>,
}

#[derive(Debug, PartialEq)]
pub struct DailyChoice {
    pub label: String,
    pub task_name: String,
    pub sequence: Value,
}

impl Daily {
    pub fn choices(&self) -> Vec<DailyChoice> {
        let mut result = Vec::new();
        for choice in &self.options.values {
            if let Some(children) = &choice.options {
                for child in &children.values {
                    result.push(DailyChoice {
                        label: format!("{} · {}", choice.display_name, child.display_name),
                        task_name: choice.display_name.clone(),
                        sequence: child.physical_name.clone(),
                    });
                }
            } else {
                result.push(DailyChoice {
                    label: choice.display_name.clone(),
                    task_name: choice.display_name.clone(),
                    sequence: Value::Null,
                });
            }
        }
        result
    }

    pub fn label(&self) -> String {
        if self.enabled == Some(false) {
            return "不启用".into();
        }
        let Some(task) = &self.task else {
            return "未选择".into();
        };
        self.choices()
            .iter()
            .find(|choice| &choice.task_name == task && choice.sequence == self.sequence)
            .map_or_else(|| task.clone(), |choice| choice.label.clone())
    }
}

pub fn start_label(day: Option<u8>) -> &'static str {
    match day {
        None => "未设置",
        Some(0) => "不启用",
        Some(1) => "周一起",
        Some(2) => "周二起",
        Some(3) => "周三起",
        Some(4) => "周四起",
        Some(5) => "周五起",
        Some(6) => "周六起",
        Some(7) => "周日起",
        Some(_) => "无效起始日",
    }
}

#[cfg(test)]
#[path = "../tests/model.rs"]
mod tests;
