"""
Property-based tests for AWS startup configuration validation.

Feature: cloud-migration, Property 17: AWS startup configuration validation

Validates: Requirements 8.5

Tests that:
- Missing AWS vars raise errors when use_local_providers=False
- Local mode works without AWS vars
- Whitespace-only values are treated as empty
- All vars present and non-empty allows startup in cloud mode
"""

import os
from contextlib import contextmanager

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# The four required AWS environment variable names
AWS_ENV_VARS = [
    "SENTIFY_AWS_REGION",
    "SENTIFY_COGNITO_USER_POOL_ID",
    "SENTIFY_COGNITO_APP_CLIENT_ID",
    "SENTIFY_DYNAMODB_TABLE_NAME",
]

# All SENTIFY_ env vars that might interfere with Settings construction
ALL_SENTIFY_VARS = AWS_ENV_VARS + ["SENTIFY_USE_LOCAL_PROVIDERS"]

# Non-empty strings that represent valid AWS config values
valid_aws_value = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Whitespace-only strings (treated as empty by the validator)
whitespace_only = st.lists(
    st.sampled_from([" ", "\t", "\n", "\r"]),
    min_size=0,
    max_size=10,
).map("".join)

# Strategy that generates either empty string or whitespace-only string
empty_or_whitespace = st.one_of(st.just(""), whitespace_only)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _env_context(env_vars: dict[str, str]):
    """Context manager that sets env vars and restores original state on exit."""
    original = {}
    removed = []

    # Save original state and clear all SENTIFY vars
    for var in ALL_SENTIFY_VARS:
        if var in os.environ:
            original[var] = os.environ[var]
        else:
            removed.append(var)
        os.environ.pop(var, None)

    # Set the desired env vars
    for key, value in env_vars.items():
        os.environ[key] = value

    try:
        yield
    finally:
        # Restore original state
        for var in ALL_SENTIFY_VARS:
            os.environ.pop(var, None)
        for key, value in original.items():
            os.environ[key] = value


def _create_settings():
    """Create a fresh Settings instance (re-reads env vars)."""
    from app.config import Settings

    return Settings()


# ---------------------------------------------------------------------------
# Property 17: AWS startup configuration validation
# ---------------------------------------------------------------------------


class TestProperty17AWSConfigValidation:
    """Feature: cloud-migration, Property 17: AWS startup configuration validation.

    For any combination where use_local_providers is False and at least one of
    the required AWS environment variables is missing or empty, the application
    SHALL raise a configuration error at startup indicating which variable is
    missing.

    **Validates: Requirements 8.5**
    """

    @given(
        region=empty_or_whitespace,
        pool_id=empty_or_whitespace,
        client_id=empty_or_whitespace,
        table_name=empty_or_whitespace,
    )
    @settings(max_examples=100)
    def test_all_vars_missing_or_empty_raises_error(
        self, region, pool_id, client_id, table_name
    ):
        """When use_local_providers=False and ALL required AWS vars are
        missing/empty, a ValueError is raised listing all missing variables.

        **Validates: Requirements 8.5**
        """
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": region,
            "SENTIFY_COGNITO_USER_POOL_ID": pool_id,
            "SENTIFY_COGNITO_APP_CLIENT_ID": client_id,
            "SENTIFY_DYNAMODB_TABLE_NAME": table_name,
        }
        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            # All four vars should be mentioned as missing
            for var in AWS_ENV_VARS:
                assert var in error_text

    @given(
        values=st.lists(
            valid_aws_value, min_size=4, max_size=4
        ),
        missing_indices=st.lists(
            st.integers(min_value=0, max_value=3),
            min_size=1,
            max_size=3,
            unique=True,
        ),
        replacement=empty_or_whitespace,
    )
    @settings(max_examples=100)
    def test_subset_of_vars_missing_raises_error_with_correct_names(
        self, values, missing_indices, replacement
    ):
        """When use_local_providers=False and a subset of required AWS vars
        are missing/empty, a ValueError is raised listing only the missing ones.

        **Validates: Requirements 8.5**
        """
        env = {"SENTIFY_USE_LOCAL_PROVIDERS": "false"}
        for i, var in enumerate(AWS_ENV_VARS):
            if i in missing_indices:
                env[var] = replacement
            else:
                env[var] = values[i]

        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            # Missing vars should appear in error message
            for i in missing_indices:
                assert AWS_ENV_VARS[i] in error_text

            # Present vars should NOT appear in error message as missing
            for i, var in enumerate(AWS_ENV_VARS):
                if i not in missing_indices:
                    assert var not in error_text

    @given(
        region=valid_aws_value,
        pool_id=valid_aws_value,
        client_id=valid_aws_value,
        table_name=valid_aws_value,
    )
    @settings(max_examples=100)
    def test_all_vars_present_does_not_raise(
        self, region, pool_id, client_id, table_name
    ):
        """When use_local_providers=False and ALL required AWS vars are
        present and non-empty, no error is raised.

        **Validates: Requirements 8.5**
        """
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": region,
            "SENTIFY_COGNITO_USER_POOL_ID": pool_id,
            "SENTIFY_COGNITO_APP_CLIENT_ID": client_id,
            "SENTIFY_DYNAMODB_TABLE_NAME": table_name,
        }
        with _env_context(env):
            # Should not raise
            s = _create_settings()
            assert s.use_local_providers is False
            assert s.aws_region == region
            assert s.cognito_user_pool_id == pool_id
            assert s.cognito_app_client_id == client_id
            assert s.dynamodb_table_name == table_name

    @given(
        set_vars=st.lists(st.booleans(), min_size=4, max_size=4),
        var_values=st.lists(empty_or_whitespace, min_size=4, max_size=4),
    )
    @settings(max_examples=100)
    def test_local_mode_skips_aws_validation(self, set_vars, var_values):
        """When use_local_providers=True, no AWS validation is performed,
        regardless of whether AWS vars are set or not.

        **Validates: Requirements 8.5**
        """
        env = {"SENTIFY_USE_LOCAL_PROVIDERS": "true"}
        for i, var in enumerate(AWS_ENV_VARS):
            if set_vars[i]:
                env[var] = var_values[i]

        with _env_context(env):
            # Should not raise regardless of AWS var state
            s = _create_settings()
            assert s.use_local_providers is True


class TestConfigValidationEdgeCases:
    """Edge case tests for configuration validation.

    Feature: cloud-migration, Property 17: AWS startup configuration validation.
    **Validates: Requirements 8.5**
    """

    def test_whitespace_only_region_treated_as_missing(self):
        """Whitespace-only values are treated as empty/missing."""
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": "   ",
            "SENTIFY_COGNITO_USER_POOL_ID": "pool-123",
            "SENTIFY_COGNITO_APP_CLIENT_ID": "client-456",
            "SENTIFY_DYNAMODB_TABLE_NAME": "my-table",
        }
        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            assert "SENTIFY_AWS_REGION" in error_text
            # Only the whitespace var should be flagged
            assert "SENTIFY_COGNITO_USER_POOL_ID" not in error_text

    def test_tab_and_newline_values_treated_as_empty(self):
        """Tabs and newlines are also treated as empty."""
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": "\t\n",
            "SENTIFY_COGNITO_USER_POOL_ID": "\t",
            "SENTIFY_COGNITO_APP_CLIENT_ID": "client-456",
            "SENTIFY_DYNAMODB_TABLE_NAME": "my-table",
        }
        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            assert "SENTIFY_AWS_REGION" in error_text
            assert "SENTIFY_COGNITO_USER_POOL_ID" in error_text
            assert "SENTIFY_COGNITO_APP_CLIENT_ID" not in error_text
            assert "SENTIFY_DYNAMODB_TABLE_NAME" not in error_text

    def test_single_missing_var_error_mentions_only_that_var(self):
        """Error message mentions only the missing variable."""
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": "us-east-1",
            "SENTIFY_COGNITO_USER_POOL_ID": "",
            "SENTIFY_COGNITO_APP_CLIENT_ID": "client-456",
            "SENTIFY_DYNAMODB_TABLE_NAME": "my-table",
        }
        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            assert "SENTIFY_COGNITO_USER_POOL_ID" in error_text
            assert "SENTIFY_AWS_REGION" not in error_text

    def test_local_mode_default_no_aws_vars_required(self):
        """Default mode (use_local_providers=True) does not require AWS vars."""
        with _env_context({}):
            # Don't set USE_LOCAL_PROVIDERS — it defaults to True
            s = _create_settings()
            assert s.use_local_providers is True

    def test_error_message_suggests_switching_to_local(self):
        """Error message includes hint to switch to local providers."""
        env = {
            "SENTIFY_USE_LOCAL_PROVIDERS": "false",
            "SENTIFY_AWS_REGION": "",
            "SENTIFY_COGNITO_USER_POOL_ID": "",
            "SENTIFY_COGNITO_APP_CLIENT_ID": "",
            "SENTIFY_DYNAMODB_TABLE_NAME": "",
        }
        with _env_context(env):
            with pytest.raises(ValidationError) as exc_info:
                _create_settings()

            error_text = str(exc_info.value)
            assert "SENTIFY_USE_LOCAL_PROVIDERS=true" in error_text
