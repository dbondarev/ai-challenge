from openai import OpenAI

ALLOWED_MODELS = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
    "gpt-4o",
}


class Agent:
    """Simple LLM agent: owns the OpenAI client and request/response flow."""

    def __init__(self, api_key: str, model: str = "gpt-5.4", role: str = ""):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")
        self.model = model
        self.role = (role or "").strip()
        self._client = OpenAI(api_key=api_key)

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")

        messages = []
        if self.role:
            messages.append({"role": "system", "content": self.role})
        messages.append({"role": "user", "content": text})

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        choice = completion.choices[0]
        usage = completion.usage
        return {
            "reply": choice.message.content or "",
            "model": self.model,
            "role": self.role,
            "finish_reason": choice.finish_reason,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None)
                if usage
                else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            },
        }
