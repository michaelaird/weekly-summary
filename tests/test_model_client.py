"""Unit tests for model_client.ModelClient"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from model_client import ModelClient, ModelResponse


class TestModelClient(unittest.TestCase):
    """Test suite for the ModelClient deep module."""

    def setUp(self):
        """Create a mock Anthropic client for testing."""
        self.mock_client = MagicMock()

    def _make_model_response(self, text, input_tokens=100, output_tokens=50):
        """Create a mock Anthropic API response."""
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = text

        response = MagicMock()
        response.content = [content_block]
        response.stop_reason = "end_turn"
        response.usage.input_tokens = input_tokens
        response.usage.output_tokens = output_tokens

        return response

    def test_call_model_success(self):
        """Test successful model call."""
        self.mock_client.messages.create.return_value = self._make_model_response(
            "Test response"
        )

        client = ModelClient(self.mock_client, write_debug_responses=False)
        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=100,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Test response")
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 50)
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertFalse(result.was_streaming_fallback)

    def test_call_model_rate_limit_retry(self):
        """Test that rate limit errors trigger retries."""
        # First call raises rate limit error, second succeeds
        self.mock_client.messages.create.side_effect = [
            Exception("Rate limited (429)"),
            self._make_model_response("Success after retry"),
        ]

        client = ModelClient(
            self.mock_client,
            max_attempts=3,
            initial_backoff_seconds=0.01,  # Short backoff for testing
            write_debug_responses=False,
        )

        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=100,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Success after retry")
        self.assertEqual(self.mock_client.messages.create.call_count, 2)

    def test_call_model_streaming_required_fallback(self):
        """Test that 'Streaming is required' error triggers max_tokens reduction."""
        # First call raises streaming required, second succeeds with reduced tokens
        self.mock_client.messages.create.side_effect = [
            ValueError("Streaming is required for operations that may take longer than 10 minutes"),
            self._make_model_response("Success with reduced tokens"),
        ]

        client = ModelClient(
            self.mock_client,
            max_attempts=3,
            write_debug_responses=False,
        )

        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=5000,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Success with reduced tokens")
        self.assertTrue(result.was_streaming_fallback)
        # Verify that the second call used half the tokens
        second_call_kwargs = self.mock_client.messages.create.call_args_list[1][1]
        self.assertEqual(second_call_kwargs["max_tokens"], 2500)

    def test_call_model_all_attempts_fail(self):
        """Test that None is returned when all rate-limit retry attempts fail."""
        # Rate-limit errors trigger retries; other errors don't
        self.mock_client.messages.create.side_effect = [
            Exception("Rate limited (429)"),
            Exception("Rate limited (429)"),
        ]

        client = ModelClient(
            self.mock_client,
            max_attempts=2,
            initial_backoff_seconds=0.01,
            write_debug_responses=False,
        )

        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=100,
        )

        self.assertIsNone(result)
        # Both attempts should be tried since they're rate-limit errors
        self.assertEqual(self.mock_client.messages.create.call_count, 2)

    def test_call_model_extracts_usage_correctly(self):
        """Test that usage info is correctly extracted from response."""
        self.mock_client.messages.create.return_value = self._make_model_response(
            "Response", input_tokens=250, output_tokens=75
        )

        client = ModelClient(self.mock_client, write_debug_responses=False)
        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=100,
        )

        self.assertEqual(result.input_tokens, 250)
        self.assertEqual(result.output_tokens, 75)

    def test_call_model_handles_missing_usage(self):
        """Test that missing usage info doesn't crash."""
        response = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = "Test response"
        response.content = [content_block]
        response.stop_reason = "end_turn"
        response.usage = None

        self.mock_client.messages.create.return_value = response

        client = ModelClient(self.mock_client, write_debug_responses=False)
        result = client.call_model(
            system="Test system",
            user_message="Test user",
            model="test-model",
            max_tokens=100,
        )

        self.assertIsNotNone(result)
        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)

    def test_call_model_with_label(self):
        """Test that label is used in log messages."""
        self.mock_client.messages.create.return_value = self._make_model_response(
            "Test response"
        )

        client = ModelClient(self.mock_client, write_debug_responses=False)
        with patch("builtins.print") as mock_print:
            result = client.call_model(
                system="Test system",
                user_message="Test user",
                model="test-model",
                max_tokens=100,
                label="my_test_label",
            )

        self.assertIsNotNone(result)

    def test_model_response_dataclass(self):
        """Test ModelResponse dataclass creation and fields."""
        response = ModelResponse(
            text="Test text",
            input_tokens=100,
            output_tokens=50,
            stop_reason="end_turn",
            was_streaming_fallback=True,
        )

        self.assertEqual(response.text, "Test text")
        self.assertEqual(response.input_tokens, 100)
        self.assertEqual(response.output_tokens, 50)
        self.assertEqual(response.stop_reason, "end_turn")
        self.assertTrue(response.was_streaming_fallback)


if __name__ == "__main__":
    unittest.main()
