"""
ModelClient: Deep module for robust Anthropic API interactions.

Encapsulates all retry, backoff, rate-limit, and streaming-failure handling.
Provides a single clean interface for scoring and analysis stages.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import anthropic


@dataclass
class ModelResponse:
    """Result of a model call, including text, usage, and metadata."""

    text: str
    """The extracted text from the model response."""
    
    input_tokens: int | None = None
    """Input tokens consumed by the model."""
    
    output_tokens: int | None = None
    """Output tokens produced by the model."""
    
    stop_reason: str | None = None
    """Why the model stopped (e.g. 'end_turn', 'max_tokens')."""
    
    was_streaming_fallback: bool = False
    """True if this response required a retry with streaming/smaller budget."""


class ModelClient:
    """
    Robust wrapper around Anthropic API that handles retries, rate limits,
    and streaming failures with exponential backoff and fallback strategies.
    
    This is a deep module: the retry/backoff/rate-limit logic is fully isolated here,
    making calling code simple and testable.
    """

    def __init__(
        self,
        anthropic_client,
        *,
        max_attempts: int = 3,
        initial_backoff_seconds: float = 1.0,
        write_debug_responses: bool = False,
        debug_dir: Path | None = None,
    ):
        """
        Initialize the ModelClient.
        
        Args:
            anthropic_client: An Anthropic() instance or adapter (e.g., DryRunAnthropic)
            max_attempts: Maximum number of retry attempts (including the first try)
            initial_backoff_seconds: Starting backoff duration before rate-limit retries
            write_debug_responses: If True, save raw model responses to debug_dir
            debug_dir: Directory for debug files (used if write_debug_responses=True)
        """
        self.client = anthropic_client
        self.max_attempts = max_attempts
        self.initial_backoff_seconds = initial_backoff_seconds
        self.write_debug_responses = write_debug_responses
        self.debug_dir = debug_dir

    def call_model(
        self,
        *,
        system: str,
        user_message: str,
        model: str,
        max_tokens: int,
        label: str | None = None,
    ) -> ModelResponse | None:
        """
        Make a robust call to the Anthropic API with automatic retry and fallback.
        
        Handles:
        - Rate limiting (429, "rate", "throttle") with exponential backoff
        - Streaming requirement errors (reduces max_tokens and retries)
        - General exceptions (logs and returns None)
        
        Args:
            system: System prompt to guide the model
            user_message: User prompt/message
            model: Model ID (e.g. "claude-haiku-4-5", "claude-sonnet-5")
            max_tokens: Maximum tokens for the response
            label: Debug label for log messages and debug files
        
        Returns:
            ModelResponse on success, None if all attempts failed.
        """
        if label is None:
            label = model
        
        backoff = self.initial_backoff_seconds
        
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                
                # Extract text from response
                text = "\n".join(
                    block.text 
                    for block in response.content 
                    if getattr(block, "type", None) == "text"
                )
                
                # Extract usage info
                usage = getattr(response, "usage", None)
                input_tokens = None
                output_tokens = None
                if usage is not None:
                    input_tokens = getattr(usage, "input_tokens", None)
                    output_tokens = getattr(usage, "output_tokens", None)
                
                stop_reason = getattr(response, "stop_reason", None)
                
                # Write debug output if requested
                if self.write_debug_responses and self.debug_dir:
                    self._write_debug_response(
                        label=label,
                        text=text,
                        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                        stop_reason=stop_reason,
                    )
                
                return ModelResponse(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    stop_reason=stop_reason,
                    was_streaming_fallback=False,
                )
            
            except ValueError as exc:
                # Handle "Streaming is required for operations that may take longer than 10 minutes"
                exc_text = str(exc)
                if "Streaming is required" in exc_text and attempt < self.max_attempts:
                    new_max = max(1000, max_tokens // 2)
                    print(
                        f"  ⚠️  {label}: Streaming required; retrying with max_tokens={new_max}"
                    )
                    try:
                        response = self.client.messages.create(
                            model=model,
                            max_tokens=new_max,
                            system=system,
                            messages=[{"role": "user", "content": user_message}],
                        )
                        
                        text = "\n".join(
                            block.text 
                            for block in response.content 
                            if getattr(block, "type", None) == "text"
                        )
                        
                        usage = getattr(response, "usage", None)
                        input_tokens = None
                        output_tokens = None
                        if usage is not None:
                            input_tokens = getattr(usage, "input_tokens", None)
                            output_tokens = getattr(usage, "output_tokens", None)
                        
                        stop_reason = getattr(response, "stop_reason", None)
                        
                        if self.write_debug_responses and self.debug_dir:
                            self._write_debug_response(
                                label=f"{label}_streaming_fallback",
                                text=text,
                                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                                stop_reason=stop_reason,
                            )
                        
                        return ModelResponse(
                            text=text,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            stop_reason=stop_reason,
                            was_streaming_fallback=True,
                        )
                    except Exception as exc2:
                        print(f"  ✗ {label}: Streaming fallback retry failed: {exc2}")
                        return None
                else:
                    print(f"  ✗ {label}: ValueError: {exc}")
                    return None
            
            except Exception as exc:
                exc_msg = str(exc).lower()
                # Detect rate-limit errors
                is_rate_limit = any(term in exc_msg for term in ["rate", "429", "throttle"])
                
                if attempt < self.max_attempts and is_rate_limit:
                    print(f"  ⚠️  {label}: Rate-limited; retrying in {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                
                print(f"  ✗ {label}: Exception: {exc}")
                return None
        
        # All attempts exhausted
        print(f"  ✗ {label}: All {self.max_attempts} attempts failed")
        return None

    def _write_debug_response(
        self,
        label: str,
        text: str,
        usage: dict | None = None,
        stop_reason: str | None = None,
    ) -> None:
        """Write a debug response file for inspection."""
        if not self.debug_dir:
            return
        
        import json
        import re
        from datetime import datetime, timezone
        
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_") or "response"
        path = self.debug_dir / f"{safe_label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt"
        
        metadata = {
            "stop_reason": stop_reason,
            "usage": usage,
            "payload": text,
        }
        path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
