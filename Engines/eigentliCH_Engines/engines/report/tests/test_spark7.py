"""The spark7 client against the stand-in on a real socket: streaming, headers, the host rule, the error
kinds, the timeouts, the model check and the warm-up tick. And that the token appears nowhere."""

from __future__ import annotations

from dataclasses import replace

import pytest

from report.settings import ConfigError, load
from report.spark7 import ModelConfigError, ModelError, ModelUnavailable, Spark7Client, Warmer, check_host

from .conftest import FAKE_ENV, settings_for
from .standin import MODEL, Reply

MESSAGES = [{"role": "user", "content": "Hallo"}]


def client_for(url: str, env=FAKE_ENV, **over) -> Spark7Client:
    s = settings_for(url)
    return Spark7Client(replace(s.model, **over), env)


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "https://eu.api.anthropic.com",
                                 "https://generativelanguage.googleapis.com", "https://openrouter.ai/api/v1",
                                 "https://bedrock-runtime.eu-central-1.amazonaws.com"])
def test_external_providers_are_refused_by_name(url):
    with pytest.raises(ModelConfigError, match="external generative AI"):
        check_host(url)


@pytest.mark.parametrize("url", ["https://example.com", "https://minimind.ch.evil.io", "https://notminimind.ch"])
def test_a_host_outside_the_house_is_refused(url):
    with pytest.raises(ModelConfigError, match="neither loopback nor"):
        check_host(url)


def test_plain_http_to_a_remote_house_host_is_refused():
    with pytest.raises(ModelConfigError, match="plain http"):
        check_host("http://spark7.minimind.ch")


@pytest.mark.parametrize("url", ["https://spark7.minimind.ch", "https://litellm.minimind.ch/v1",
                                 "http://127.0.0.1:8000", "http://localhost:11434", "http://[::1]:8000"])
def test_the_house_and_loopback_are_accepted(url):
    check_host(url)


def test_the_settings_refuse_an_external_provider_at_start(monkeypatch):
    monkeypatch.setenv("REPORT_MODEL_URL", "https://api.openai.com/v1")
    with pytest.raises(ConfigError, match="external generative AI"):
        load()


def test_a_stream_is_assembled_and_the_headers_are_sent(spark):
    spark.queue(Reply(content="Grüezi, das ist eine gestreamte Antwort."))
    c = client_for(spark.url)
    done = c.complete(MESSAGES, max_tokens=50, temperature=0.0, seed=7)
    assert done.text == "Grüezi, das ist eine gestreamte Antwort."
    assert done.model == MODEL and done.finish_reason == "stop" and done.first_byte_ms is not None
    assert done.completion_tokens is not None
    sent = spark.chat_requests()[0]
    assert sent["body"]["stream"] is True and sent["body"]["seed"] == 7 and sent["body"]["model"] == MODEL
    h = sent["headers"]
    assert h["cf-access-client-id"] == FAKE_ENV["SPARK7_CLIENT_ID"]
    assert h["cf-access-client-secret"] == FAKE_ENV["SPARK7_CLIENT_SECRET"]
    assert h["cache-control"] == "no-cache, no-store, must-revalidate"


def test_the_non_streaming_form_works_too(spark):
    spark.queue(Reply(content="einmal"))
    done = client_for(spark.url, stream=False).complete(MESSAGES, max_tokens=5, temperature=0.0)
    assert done.text == "einmal" and spark.chat_requests()[0]["body"]["stream"] is False


def test_the_token_appears_in_no_description(spark):
    c = client_for(spark.url)
    for text in (repr(c), str(c.settings.describe(FAKE_ENV)), repr(settings_for(spark.url))):
        assert FAKE_ENV["SPARK7_CLIENT_SECRET"] not in text and FAKE_ENV["SPARK7_CLIENT_ID"] not in text


def test_refused_access_names_the_missing_variables(spark):
    spark.queue(Reply(status=403, body="Forbidden"))
    with pytest.raises(ModelUnavailable, match="SPARK7_CLIENT_ID"):
        client_for(spark.url, env={}).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_refused_access_with_a_token_says_so_without_the_token(spark):
    spark.queue(Reply(status=403, body="Forbidden"))
    with pytest.raises(ModelUnavailable) as info:
        client_for(spark.url).complete(MESSAGES, max_tokens=5, temperature=0.0)
    assert "service token was refused" in str(info.value)
    assert FAKE_ENV["SPARK7_CLIENT_SECRET"] not in str(info.value)


@pytest.mark.parametrize("status,kind", [(524, ModelUnavailable), (503, ModelUnavailable), (429, ModelUnavailable),
                                         (400, ModelError), (404, ModelError), (422, ModelError)])
def test_status_codes_map_to_the_two_error_kinds(spark, status, kind):
    spark.queue(Reply(status=status, body="nope"))
    with pytest.raises(kind):
        client_for(spark.url).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_a_silent_server_is_abandoned_at_the_first_byte_limit(spark):
    spark.queue(Reply(content="late", delay_s=1.5))
    with pytest.raises(ModelUnavailable, match="did not answer in time"):
        client_for(spark.url, first_byte_timeout_s=0.4).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_a_slow_but_steady_stream_beats_the_first_byte_limit(spark):
    """The point of streaming: the whole answer takes longer than the per-chunk limit, and still arrives."""
    spark.queue(Reply(content="x" * 70, chunk_delay_s=0.1))
    done = client_for(spark.url, first_byte_timeout_s=0.6).complete(MESSAGES, max_tokens=5, temperature=0.0)
    assert done.text == "x" * 70 and done.latency_ms > 600


def test_the_total_limit_ends_an_endless_stream(spark):
    spark.queue(Reply(content="y" * 140, chunk_delay_s=0.1))
    with pytest.raises(ModelUnavailable, match="longer than"):
        client_for(spark.url, total_timeout_s=0.5).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_a_broken_stream_is_an_error(spark):
    spark.queue(Reply(content="abgebrochen mitten im Satz", drop=True))
    with pytest.raises(ModelError, match="ended before"):
        client_for(spark.url).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_an_answer_from_another_model_is_refused(spark):
    spark.queue(Reply(content="hi", model="someone/else"))
    with pytest.raises(ModelError, match="wrong name"):
        client_for(spark.url).complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_an_unreachable_server_is_unavailable():
    c = client_for("http://127.0.0.1:9", connect_timeout_s=1.0)
    with pytest.raises(ModelUnavailable, match="unreachable"):
        c.complete(MESSAGES, max_tokens=5, temperature=0.0)


def test_models_lists_what_is_served(spark):
    assert client_for(spark.url).models() == [MODEL]


def test_the_warm_up_tick_records_its_outcome(spark):
    spark.queue(Reply(content="."), Reply(status=524))
    w = Warmer(client_for(spark.url), interval_s=30)
    assert w.tick()["last_ok"] is True
    after = w.tick()
    assert after["last_ok"] is False and "524" in after["last_error"] and after["ticks"] == 2
    body = spark.chat_requests()[0]["body"]
    assert body["max_tokens"] == 1
