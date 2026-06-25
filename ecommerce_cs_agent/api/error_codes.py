from __future__ import annotations


ECS_OE_001 = "ECS-OE-001"
ECS_OE_002 = "ECS-OE-002"
ECS_OE_003 = "ECS-OE-003"
ECS_LAUNCH_001 = "ECS-LAUNCH-001"
ECS_LAUNCH_002 = "ECS-LAUNCH-002"
ECS_LAUNCH_003 = "ECS-LAUNCH-003"
ECS_LAUNCH_004 = "ECS-LAUNCH-004"


ERROR_CODE_REGISTRY = [
    {
        "id": ECS_OE_001,
        "user_message": "open_erp integration token is missing or invalid",
        "endpoint": "/v1/integrations/open-erp/*",
    },
    {
        "id": ECS_OE_002,
        "user_message": "open_erp connector is not bound or active",
        "endpoint": "/v1/integrations/open-erp/admin-launch-tickets",
    },
    {
        "id": ECS_OE_003,
        "user_message": "open_erp integration request validation failed",
        "endpoint": "/v1/integrations/open-erp/*",
    },
    {
        "id": ECS_LAUNCH_001,
        "user_message": "launch token has already been used",
        "endpoint": "/v1/admin/auth/launch/exchange",
    },
    {
        "id": ECS_LAUNCH_002,
        "user_message": "launch token has expired",
        "endpoint": "/v1/admin/auth/launch/exchange",
    },
    {
        "id": ECS_LAUNCH_003,
        "user_message": "launch token was not found",
        "endpoint": "/v1/admin/auth/launch/exchange",
    },
    {
        "id": ECS_LAUNCH_004,
        "user_message": "launch_token is required",
        "endpoint": "/v1/admin/auth/launch/exchange",
    },
]
