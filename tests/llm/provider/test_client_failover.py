"""Tests for profile-scoped AIClient failover and routing."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider.client import AIClient
from tinysoul.llm.provider.config import (
    ChatConfig,
    ChatModelOverride,
    ChatProfile,
    LLMProfileName,
    ModelCapability,
    ModelConfig,
    ModelType,
)
from tinysoul.llm.provider.request import AIRequest
from tinysoul.llm.provider.response import AIResponse
from tinysoul.trap import SystemExhaustedError


DEFAULT_TEST_PROFILES = {
    LLMProfileName.STEP1: ChatProfile(provider_chain=["A", "B"]),
    LLMProfileName.STEP2: ChatProfile(provider_chain=["A", "B"]),
    LLMProfileName.STEP3: ChatProfile(provider_chain=["A", "B"]),
    LLMProfileName.ACTION_LLM: ChatProfile(provider_chain=["A", "B"]),
}


class FailingAdapter:
    def __init__(self, name: str):
        self.name = name

    def chat(self, request, config):
        raise RuntimeError(f"{self.name} failed")


class WorkingAdapter:
    def __init__(self, name: str, response_text: str = "ok"):
        self.name = name
        self.response_text = response_text
        self.calls = 0
        self.configs = []

    def chat(self, request, config):
        self.calls += 1
        self.configs.append(config)
        return AIResponse(content=self.response_text)


class CountdownAdapter:
    def __init__(self, name: str, response_text: str = "ok", fail_count: int = 0):
        self.name = name
        self.response_text = response_text
        self.fail_count = fail_count
        self.calls = 0

    def chat(self, request, config):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise RuntimeError(f"{self.name} failed (call {self.calls})")
        return AIResponse(content=self.response_text)


class RecordingAdapter:
    def __init__(self):
        self.last_request: AIRequest | None = None
        self.last_config: ModelConfig | None = None

    def chat(self, request, config):
        self.last_request = request
        self.last_config = config
        return AIResponse(content="ok")


class OrderedAdapter:
    def __init__(self, name: str, attempts: list[str], *, response_text: str = "ok", fail: bool = False):
        self.name = name
        self.attempts = attempts
        self.response_text = response_text
        self.fail = fail

    def chat(self, request, config):
        self.attempts.append(self.name)
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return AIResponse(content=self.response_text)


def _configs(*providers: str) -> list[ModelConfig]:
    return [
        ModelConfig(
            provider=provider,
            model=f"{provider}-model",
            model_type=ModelType.CHAT,
            api_key="fake",
            max_retries=1,
            base_retry_delay=0,
        )
        for provider in providers
    ]


def _make_client(monkeypatch, adapters, profiles=None, providers=("A", "B")):
    client = AIClient(
        _configs(*providers),
        chat_profiles=profiles or DEFAULT_TEST_PROFILES,
    )

    def fake_create_adapter(config):
        return adapters[config.provider]

    monkeypatch.setattr("tinysoul.llm.provider.client.create_adapter", fake_create_adapter)
    return client


class TestProfileFailover:
    def test_first_provider_fails_second_succeeds(self, monkeypatch):
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters)

        assert client.current_chat_model_name(LLMProfileName.STEP1) == "A-model"

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_B"
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"

    def test_subsequent_call_uses_profile_current_provider(self, monkeypatch):
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters)

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_B"
        assert adapters["B"].calls == 2

    def test_failover_index_is_independent_per_profile(self, monkeypatch):
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters)

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"
        assert client.current_chat_model_name(LLMProfileName.STEP3) == "A-model"

    def test_current_provider_failure_retries_from_head(self, monkeypatch):
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters)
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"

        adapters["A"] = WorkingAdapter("A", "from_A_recovered")
        adapters["B"] = FailingAdapter("B")
        client._adapters.clear()

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_A_recovered"
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "A-model"

    def test_current_provider_failure_scans_from_chain_head_with_three_providers(self, monkeypatch):
        attempts: list[str] = []
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(provider_chain=["A", "B", "C"]),
        }
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
            "C": WorkingAdapter("C", "from_C"),
        }
        client = _make_client(
            monkeypatch,
            adapters,
            profiles=profiles,
            providers=("A", "B", "C"),
        )
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"

        adapters["A"] = OrderedAdapter("A", attempts, fail=True)
        adapters["B"] = OrderedAdapter("B", attempts, fail=True)
        adapters["C"] = OrderedAdapter("C", attempts, response_text="from_C")
        client._adapters.clear()

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_C"
        assert attempts == ["B", "A", "C"]
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "C-model"

    def test_all_exhausted_raises(self, monkeypatch):
        adapters = {
            "A": FailingAdapter("A"),
            "B": FailingAdapter("B"),
        }
        client = _make_client(monkeypatch, adapters)

        with pytest.raises(SystemExhaustedError, match="All models exhausted"):
            client.chat(
                messages=[{"role": "user", "content": "hello"}],
                profile=LLMProfileName.STEP1,
            )

    def test_retry_current_model_before_failover(self, monkeypatch):
        adapters = {
            "A": CountdownAdapter("A", "from_A", fail_count=1),
            "B": WorkingAdapter("B", "from_B"),
        }
        configs = _configs("A", "B")
        configs[0].max_retries = 2
        client = AIClient(configs, chat_profiles=DEFAULT_TEST_PROFILES)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapters[c.provider],
        )

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_A"
        assert adapters["A"].calls == 2
        assert adapters["B"].calls == 0


class TestProfileRouting:
    def test_profile_can_choose_different_provider_order(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(provider_chain=["B", "A"]),
        }
        adapters = {
            "A": WorkingAdapter("A", "from_A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters, profiles=profiles)

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_B"
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-model"

    def test_chat_model_overrides_support_multiple_providers(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A", "B"],
                chat_model_overrides={
                    "A": ChatModelOverride(
                        model="A-override",
                        capabilities=[ModelCapability.TEXT],
                    ),
                    "B": ChatModelOverride(
                        model="B-override",
                        capabilities=[ModelCapability.TEXT],
                    ),
                },
            ),
        }
        adapters = {
            "A": FailingAdapter("A"),
            "B": WorkingAdapter("B", "from_B"),
        }
        client = _make_client(monkeypatch, adapters, profiles=profiles)

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_B"
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-override"
        assert adapters["B"].configs[0].model == "B-override"

    def test_chat_model_override_can_inherit_known_model_capabilities(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A"],
                required_capabilities=[ModelCapability.TEXT],
                chat_model_overrides={
                    "A": ChatModelOverride(model="A-vision"),
                },
            ),
        }
        configs = [
            ModelConfig(
                provider="A",
                model="A-text",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
            ModelConfig(
                provider="A",
                model="A-vision",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
        ]
        adapter = RecordingAdapter()
        client = AIClient(configs, chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapter,
        )

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert adapter.last_config is not None
        assert adapter.last_config.model == "A-vision"
        assert adapter.last_config.capabilities == [
            ModelCapability.TEXT,
            ModelCapability.VISION,
        ]

    def test_chat_model_override_requires_capabilities_for_unknown_model(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A"],
                chat_model_overrides={
                    "A": ChatModelOverride(model="A-unknown"),
                },
            ),
        }
        client = AIClient(_configs("A"), chat_profiles=profiles)

        with pytest.raises(Exception, match="without explicit capabilities"):
            client.chat(
                messages=[{"role": "user", "content": "hello"}],
                profile=LLMProfileName.STEP1,
            )

    def test_chat_model_override_uses_explicit_capabilities_for_unknown_model(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A"],
                chat_model_overrides={
                    "A": ChatModelOverride(
                        model="A-unknown",
                        capabilities=[ModelCapability.TEXT],
                    ),
                },
            ),
        }
        adapter = RecordingAdapter()
        client = AIClient(_configs("A"), chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapter,
        )

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert adapter.last_config is not None
        assert adapter.last_config.model == "A-unknown"
        assert adapter.last_config.capabilities == [ModelCapability.TEXT]

    def test_profile_selects_chat_model_by_required_capabilities(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A"],
                required_capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
            ),
        }
        configs = [
            ModelConfig(
                provider="A",
                model="A-text",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
            ModelConfig(
                provider="A",
                model="A-vision",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
        ]
        adapter = RecordingAdapter()
        client = AIClient(configs, chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapter,
        )

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert adapter.last_config is not None
        assert adapter.last_config.model == "A-vision"

    def test_profile_prefers_capabilities_without_requiring_them(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.ACTION_LLM: ChatProfile(
                provider_chain=["A"],
                required_capabilities=[ModelCapability.TEXT],
                preferred_capabilities=[ModelCapability.VISION],
            ),
        }
        configs = [
            ModelConfig(
                provider="A",
                model="A-text",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
            ModelConfig(
                provider="A",
                model="A-vision",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
        ]
        adapter = RecordingAdapter()
        client = AIClient(configs, chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapter,
        )

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.ACTION_LLM,
        )

        assert adapter.last_config is not None
        assert adapter.last_config.model == "A-vision"

    def test_profile_falls_back_when_preferred_capabilities_are_unavailable(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.ACTION_LLM: ChatProfile(
                provider_chain=["A"],
                required_capabilities=[ModelCapability.TEXT],
                preferred_capabilities=[ModelCapability.VISION],
            ),
        }
        adapter = RecordingAdapter()
        client = AIClient(_configs("A"), chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapter,
        )

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.ACTION_LLM,
        )

        assert adapter.last_config is not None
        assert adapter.last_config.model == "A-model"

    def test_profile_skips_provider_without_required_capabilities(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A", "B"],
                required_capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
            ),
        }
        configs = [
            ModelConfig(
                provider="A",
                model="A-text",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
            ModelConfig(
                provider="B",
                model="B-vision",
                model_type=ModelType.CHAT,
                capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
                api_key="fake",
                max_retries=1,
                base_retry_delay=0,
            ),
        ]
        adapters = {"B": WorkingAdapter("B", "from_B")}
        client = AIClient(configs, chat_profiles=profiles)
        monkeypatch.setattr(
            "tinysoul.llm.provider.client.create_adapter",
            lambda c: adapters[c.provider],
        )

        response = client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
        )

        assert response.content == "from_B"
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "B-vision"

    def test_unknown_profile_raises(self, monkeypatch):
        adapters = {"A": WorkingAdapter("A")}
        client = _make_client(monkeypatch, adapters, providers=("A",))

        with pytest.raises(Exception, match="Unknown chat profile"):
            client.chat(
                messages=[{"role": "user", "content": "hello"}],
                profile="unknown",
            )


class TestChatConfigOverride:
    def test_per_request_timeout_in_request_config(self, monkeypatch):
        adapter = RecordingAdapter()
        client = _make_client(monkeypatch, {"A": adapter}, providers=("A",))

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
            config=ChatConfig(timeout=25.0),
        )

        assert adapter.last_request is not None
        assert adapter.last_request.config is not None
        assert adapter.last_request.config.timeout == 25.0
        assert adapter.last_config is not None
        assert adapter.last_config.timeout == 25.0

    def test_profile_config_and_request_config_merge(self, monkeypatch):
        profiles = {
            **DEFAULT_TEST_PROFILES,
            LLMProfileName.STEP1: ChatProfile(
                provider_chain=["A"],
                config=ChatConfig(temperature=0.2, max_tokens=100),
            ),
        }
        adapter = RecordingAdapter()
        client = _make_client(monkeypatch, {"A": adapter}, profiles=profiles, providers=("A",))

        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            profile=LLMProfileName.STEP1,
            config=ChatConfig(timeout=25.0),
        )

        assert adapter.last_config is not None
        assert adapter.last_config.temperature == 0.2
        assert adapter.last_config.max_tokens == 100
        assert adapter.last_config.timeout == 25.0
