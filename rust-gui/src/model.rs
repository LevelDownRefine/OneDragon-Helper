use serde::Deserialize;
use serde_json::Value;

#[derive(Clone, Debug, Deserialize)]
pub struct Script {
    pub script_name: String,
    pub display_name: String,
    pub script_path: String,
    pub adapted: bool,
}

#[derive(Debug, Deserialize)]
pub struct Snapshot {
    pub scripts: Vec<Script>,
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
pub struct Selection {
    pub task_name: Option<String>,
    pub sequence: Value,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Daily {
    pub daily_name: String,
    pub options: Options,
    pub selected: Selection,
    pub enabled: Option<bool>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Weekly {
    pub weekly_name: String,
    pub options: Option<Options>,
    pub selected: Option<String>,
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
        let Some(task) = &self.selected.task_name else {
            return "未选择".into();
        };
        self.choices()
            .iter()
            .find(|choice| &choice.task_name == task && choice.sequence == self.selected.sequence)
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
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn preserves_boolean_integer_and_string_sequences() {
        let daily: Daily = serde_json::from_value(json!({
            "daily_name": "测试", "enabled": null,
            "selected": {"task_name": "培养目标", "sequence": true},
            "options": {"values": [{"display_name": "培养目标", "physical_name": "target",
                "options": {"values": [
                    {"display_name": "开启", "physical_name": true},
                    {"display_name": "整数", "physical_name": 1},
                    {"display_name": "字符串", "physical_name": "1"}
                ]}}]}
        }))
        .unwrap();
        let choices = daily.choices();
        assert_eq!(choices[0].sequence, json!(true));
        assert_eq!(choices[1].sequence, json!(1));
        assert_eq!(choices[2].sequence, json!("1"));
        assert_eq!(daily.label(), "培养目标 · 开启");
        assert_eq!(daily.enabled, None);
        assert_ne!(start_label(None), start_label(Some(0)));
    }
}
