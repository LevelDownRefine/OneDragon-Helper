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
