use super::*;
#[test]
fn rejects_wrong_ids_versions_and_ambiguous_envelopes() {
    for response in [
        json!({"jsonrpc": "2.0", "id": 2, "result": {}}),
        json!({"jsonrpc": true, "id": 1, "result": {}}),
        json!({"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}}),
        json!({"jsonrpc": "2.0", "id": 1}),
    ] {
        assert_eq!(
            decode_response(&response.to_string(), 1).unwrap_err().code,
            "transport_failed"
        );
    }
}

#[test]
fn decodes_standard_and_application_errors() {
    for (error, code, refresh) in [
        (
            json!({"code": -32602, "message": "Invalid params", "data": "missing argument"}),
            "invalid_params",
            false,
        ),
        (
            json!({"code": -32002, "message": "保存失败", "data": {"refresh_required": true}}),
            "operation_failed",
            true,
        ),
        (
            json!({"code": -32003, "message": "忙碌", "data": {"refresh_required": false}}),
            "operation_busy",
            false,
        ),
        (
            json!({"code": -32603, "message": "Internal error"}),
            "internal_error",
            true,
        ),
        (
            json!({"code": 100, "message": "unknown"}),
            "rpc_error",
            true,
        ),
    ] {
        let response = json!({"jsonrpc": "2.0", "id": 1, "error": error});
        let failure = decode_response(&response.to_string(), 1).unwrap_err();
        assert_eq!(failure.code, code);
        assert_eq!(failure.refresh_required, refresh);
        assert_eq!(
            failure.message,
            response["error"]["message"].as_str().unwrap()
        );
    }
    assert!(
        decode_response(r#"{"jsonrpc":"2.0","id":1,"result":null}"#, 1)
            .unwrap()
            .is_null()
    );
}

#[test]
fn rejects_malformed_error_codes_and_application_details() {
    for error in [
        json!({"code": "operation_failed", "message": "failed"}),
        json!({"code": -32002, "message": "failed"}),
        json!({"code": -32002, "message": "failed", "data": {"refresh_required": "yes"}}),
    ] {
        let response = json!({"jsonrpc": "2.0", "id": 1, "error": error});
        let failure = decode_response(&response.to_string(), 1).unwrap_err();
        assert_eq!(failure.code, "transport_failed");
        assert!(failure.refresh_required);
    }
}
