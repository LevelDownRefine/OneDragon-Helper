use super::*;
use serde_json::json;

#[test]
fn nullable_task_fields_must_be_present_and_have_valid_types() {
    let daily = json!({"name":"daily", "options":{"values":[]},
        "task":null, "sequence":null, "enabled":null});
    assert!(serde_json::from_value::<Daily>(daily.clone()).is_ok());
    for key in ["task", "enabled"] {
        let mut missing = daily.clone();
        missing.as_object_mut().unwrap().remove(key);
        assert!(serde_json::from_value::<Daily>(missing).is_err(), "{key}");
    }
    let weekly = json!({"name":"weekly", "options":null, "task":null, "start_day":null});
    assert!(serde_json::from_value::<Weekly>(weekly.clone()).is_ok());
    for key in ["options", "task", "start_day"] {
        let mut missing = weekly.clone();
        missing.as_object_mut().unwrap().remove(key);
        assert!(serde_json::from_value::<Weekly>(missing).is_err(), "{key}");
    }
    for (key, value) in [
        ("options", json!([])),
        ("task", json!(3)),
        ("start_day", json!(true)),
    ] {
        let mut invalid = weekly.clone();
        invalid[key] = value;
        assert!(serde_json::from_value::<Weekly>(invalid).is_err(), "{key}");
    }
}

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
