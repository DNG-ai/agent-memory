"""LLM provider for memory summarization (compaction) and pattern extraction."""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_memory.config import Config


EXTRACT_PATTERNS_PROMPT = """Analyze the following session content and extract any error-fix patterns.

For each pattern found, return a JSON array of objects with these fields:
- "error": The error message or symptom
- "cause": The root cause
- "fix": How it was fixed
- "context": Where it occurred (file, module, component)

Return ONLY a JSON array. If no patterns found, return: []

Session content:
{content}"""


COMPACTION_PROMPT = """Summarize the following {count} related memories into a single, comprehensive memory.

Rules:
- Preserve all key facts, decisions, and important context
- Be concise but complete
- Use clear, direct language
- If memories contradict each other, keep the most recent information
- Output only the summary, no preamble or explanation

Memories (oldest to newest):
{memories}

Summary:"""


class LLMProvider:
    """LLM provider for summarization, reuses embedding provider credentials."""

    def __init__(self, config: Config):
        """Initialize the LLM provider.

        Args:
            config: Configuration object (reuses semantic provider settings)
        """
        self.config = config
        self.provider = config.semantic.provider
        self._client = None

    def _get_vertex_client(self):
        """Get or create Vertex AI client."""
        if self._client is None:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(
                project=self.config.semantic.vertex_project_id,
                location=self.config.semantic.vertex_location,
            )
            self._client = GenerativeModel(self.config.llm.vertex_model)
        return self._client

    def _get_claude_client(self):
        """Get or create Anthropic client."""
        if self._client is None:
            import os

            import anthropic

            api_key = os.environ.get(self.config.semantic.claude_api_key_env)
            if not api_key:
                raise ValueError(
                    f"Anthropic API key not found in env var: {self.config.semantic.claude_api_key_env}"
                )
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def summarize(self, memories: list[str]) -> str:
        """Generate a summary of the given memories.

        Args:
            memories: List of memory content strings (ordered oldest to newest)

        Returns:
            A single summary string

        Raises:
            Exception: If LLM call fails (caller should abort)
        """
        if not memories:
            raise ValueError("No memories to summarize")

        # Format memories with numbers
        formatted_memories = "\n".join(f"{i + 1}. {m}" for i, m in enumerate(memories))

        prompt = COMPACTION_PROMPT.format(
            count=len(memories),
            memories=formatted_memories,
        )

        if self.provider == "vertex":
            return self._summarize_vertex(prompt)
        elif self.provider == "claude":
            return self._summarize_claude(prompt)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _summarize_vertex(self, prompt: str) -> str:
        """Generate summary using Vertex AI."""
        client = self._get_vertex_client()
        response = client.generate_content(prompt)
        return response.text.strip()

    def _summarize_claude(self, prompt: str) -> str:
        """Generate summary using Anthropic Claude."""
        client = self._get_claude_client()
        response = client.messages.create(
            model=self.config.llm.claude_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def extract_patterns(self, content: str) -> list[dict]:
        """Extract error-fix patterns from session content.

        Args:
            content: Session content to analyze

        Returns:
            List of pattern dicts with error/cause/fix/context fields.
            Returns empty list if no patterns found or on parse error.
        """
        if not content:
            return []

        prompt = EXTRACT_PATTERNS_PROMPT.format(content=content)

        try:
            if self.provider == "vertex":
                raw = self._summarize_vertex(prompt)
            elif self.provider == "claude":
                raw = self._summarize_claude(prompt)
            else:
                return []
        except Exception:
            return []

        # Parse JSON from LLM response
        try:
            # Strip markdown code fences if present
            text = raw.strip()
            if text.startswith("```"):
                # Remove opening fence (possibly ```json)
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            parsed = _json.loads(text)
            if isinstance(parsed, list):
                return parsed
            return []
        except (_json.JSONDecodeError, ValueError):
            return []


def get_llm_provider(config: Config) -> LLMProvider | None:
    """Get an LLM provider if semantic search is enabled.

    Args:
        config: Configuration object

    Returns:
        LLMProvider instance or None if semantic search is disabled
    """
    if not config.semantic.enabled:
        return None

    try:
        return LLMProvider(config)
    except Exception:
        return None
