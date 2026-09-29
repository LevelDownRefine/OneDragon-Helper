use super::*;
use serde_json::json;

#[test]
fn preserves_boolean_integer_and_string_sequences() {
    let daily: Daily = serde_json::from_value(json!({
        "name": "测试", "enabled": null,
        "task": "培养目标", "sequence": true,
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

#[test]
fn single_group_label_omits_repeated_daily_name() {
    let mut daily: Daily = serde_json::from_value(json!({
        "name": "每日任务", "enabled": null,
        "task": "每日任务", "sequence": false,
        "options": {"values": [{"display_name": "每日任务", "physical_name": "每日任务",
            "options": {"values": [
                {"display_name": "培养目标", "physical_name": true},
                {"display_name": "不启用培养目标", "physical_name": false}
            ]}}]}
    }))
    .unwrap();
    assert_eq!(daily.label(), "不启用培养目标");
    assert_eq!(daily.choices()[1].task_name, "每日任务");
    assert_eq!(daily.choices()[1].sequence, json!(false));
    daily.enabled = Some(false);
    assert_eq!(daily.label(), "不启用");
}
