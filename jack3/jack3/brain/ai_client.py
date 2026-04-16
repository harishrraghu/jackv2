"""
Unified AI interface for Jack v3.

Supports three backends:
  A) Anthropic API (direct) -- for deep reasoning tasks
  B) OpenAI-compatible proxy (Gemini via cliproxy) -- for fast intraday decisions
  C) Claude Code headless subprocess -- for nightly journal reviews

The rest of the system uses AIClient without knowing which provider is active.
"""
import json
import os
import subprocess
from typing import Optional


class AIClient:
    """
    Unified AI interface.

    provider options: "anthropic", "openai_proxy", "claude_code"
    """

    def __init__(self, provider: str, config: dict):
        self.provider = provider
        self.config = config

    def ask(
        self,
        prompt: str,
        system: str = "",
        response_format: str = "json",
    ) -> dict:
        """
        Send a prompt to the AI and return the response.

        Args:
            prompt: The user message.
            system: Optional system prompt.
            response_format: "json" or "text".

        Returns:
            {"content": str_or_dict, "usage": {"input_tokens": int, "output_tokens": int}}
        """
        if self.provider == "anthropic":
            return self._ask_anthropic(prompt, system, response_format)
        elif self.provider == "openai_proxy":
            return self._ask_openai_proxy(prompt, system, response_format)
        elif self.provider == "claude_code":
            return self._ask_claude_code(prompt, system)
        else:
            raise ValueError(f"Unknown AI provider: {self.provider}")

    # ─────────────────────────────────────────────────
    #  Backend A: Anthropic API
    # ─────────────────────────────────────────────────

    def _ask_anthropic(self, prompt: str, system: str, response_format: str) -> dict:
        """Call the Anthropic API directly."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

        api_key = os.environ.get("ANTHROPIC_API_KEY", self.config.get("api_key", ""))
        model = self.config.get("model", "claude-sonnet-4-20250514")
        max_tokens = int(self.config.get("max_tokens", 2000))

        client = anthropic.Anthropic(api_key=api_key)

        messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        content = response.content[0].text

        # Parse JSON if requested
        if response_format == "json":
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting JSON from markdown code blocks
                content = _extract_json_from_text(content)

        return {
            "content": content,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    # ─────────────────────────────────────────────────
    #  Backend B: OpenAI-compatible proxy (Gemini via cliproxy)
    # ─────────────────────────────────────────────────

    def _ask_openai_proxy(self, prompt: str, system: str, response_format: str) -> dict:
        """Call via OpenAI-compatible REST endpoint with exponential backoff on 429."""
        try:
            import requests
        except ImportError:
            raise ImportError("requests package not installed. Run: pip install requests")
        import time

        base_url = self.config.get("base_url", "http://localhost:8080/v1")
        api_key = self.config.get("api_key", "dummy")
        model = self.config.get("model", "gemini-pro")
        max_tokens = int(self.config.get("max_tokens", 2000))

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        max_retries = 6
        wait = 15  # seconds, doubles each retry
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=60,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", wait))
                    actual_wait = max(retry_after, wait)
                    print(f"[AIClient] 429 rate limit -- waiting {actual_wait}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(actual_wait)
                    wait = min(wait * 2, 120)
                    continue
                response.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if attempt == max_retries - 1:
                    raise
                print(f"[AIClient] HTTP error {e} -- retrying in {wait}s")
                time.sleep(wait)
                wait = min(wait * 2, 120)

        data = response.json()
        if "error" in data and "choices" not in data:
            raise RuntimeError(f"Proxy error: {data['error']}")
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        if response_format == "json":
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = _extract_json_from_text(content)

        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }

    # ─────────────────────────────────────────────────
    #  Backend C: Claude Code headless subprocess
    # ─────────────────────────────────────────────────

    def _ask_claude_code(self, prompt: str, system: str) -> dict:
        """Run Claude Code as a headless subprocess."""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        allowed_tools = self.config.get("allowed_tools", "Read,Bash")
        max_turns = str(self.config.get("max_turns", 5))

        result = subprocess.run(
            [
                "claude",
                "-p", full_prompt,
                "--output-format", "json",
                "--bare",
                "--allowedTools", allowed_tools,
                "--max-turns", max_turns,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Claude Code subprocess failed: {result.stderr}")

        try:
            parsed = json.loads(result.stdout)
            content = parsed.get("result", result.stdout)
        except json.JSONDecodeError:
            content = result.stdout

        # Try to parse the content as JSON
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = _extract_json_from_text(content)

        return {
            "content": content,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


# ─────────────────────────────────────────────────
#  Factory function
# ─────────────────────────────────────────────────

def create_ai_client(settings: dict, mode: str = "intraday") -> AIClient:
    """
    Create an AIClient configured for the given mode.

    Args:
        settings: Full settings.yaml config dict.
        mode: "intraday" (fast, cheap) or "nightly" (deep reasoning).

    Returns:
        Configured AIClient instance.
    """
    ai_config = settings.get("ai", {})

    if mode == "intraday":
        provider = ai_config.get("intraday_provider", "openai_proxy")
    else:
        provider = ai_config.get("nightly_provider", "claude_code")

    provider_config = ai_config.get(provider, {})
    return AIClient(provider=provider, config=provider_config)


def _extract_json_from_text(text: str) -> dict:
    """
    Try to extract a JSON object from text that may contain markdown code blocks
    or extra prose around the JSON.
    """
    if not isinstance(text, str):
        return {}

    # Try extracting from ```json ... ``` blocks
    import re
    patterns = [
        r"```json\s*([\s\S]+?)\s*```",
        r"```\s*([\s\S]+?)\s*```",
        r"(\{[\s\S]+\})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    return {"raw_response": text}
