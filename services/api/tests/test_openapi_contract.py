from promotion_control_plane.api.app import create_app


def test_sse_openapi_declares_event_stream_media_type() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/events/stream"]["get"]
    content = operation["responses"]["200"]["content"]

    assert set(content) == {"text/event-stream"}
    assert content["text/event-stream"]["schema"] == {"type": "string"}


def test_openapi_declares_rfc_7807_media_type_for_every_error_response() -> None:
    document = create_app().openapi()
    checked = 0

    for path_item in document["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            for status, response in operation["responses"].items():
                if int(status) < 400:
                    continue
                assert set(response["content"]) == {"application/problem+json"}
                schema = response["content"]["application/problem+json"]["schema"]
                assert schema["properties"]["code"]["type"] == "string"
                assert schema["properties"]["correlation_id"]["format"] == "uuid"
                checked += 1

    assert checked > 0
