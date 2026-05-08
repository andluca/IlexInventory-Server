"""Auth request/response serializers for apps.core.

These are the only serializers in this module; they drive both DRF validation
and the OpenAPI schema (drf-spectacular reads the class structure).

Constraints:
- SignupRequest: password min_length=8 (new accounts must have an 8-char password)
- LoginRequest: no min_length on password (existing users may pre-date the policy)
- UserResponse: exposes date_joined as created_at per SPEC X2 §step-5 shape
"""

from __future__ import annotations

from rest_framework import serializers


class SignupRequest(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        min_length=8,
        write_only=True,
        style={"input_type": "password"},
    )


class LoginRequest(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )


class UserResponse(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    created_at = serializers.DateTimeField(source="date_joined", read_only=True)
