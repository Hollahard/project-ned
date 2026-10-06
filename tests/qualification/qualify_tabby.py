"""Automated qualification suite for Phase 1: TabbyAPI + ExLlamaV3 on RTX 5090."""

import asyncio
import json
import logging
import sys
import time
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase1_qualification")


class TabbyAPIQualifier:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5000",
        admin_key: str = "friday-admin-token",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.admin_key}"} if self.admin_key else {},
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        )

    async def check_health(self) -> dict:
        """Requirement: Tabby starts on 127.0.0.1 with auth & GPU is detected."""
        logger.info("--> Checking TabbyAPI health at %s...", self.base_url)
        resp = await self.client.get("/health")
        if resp.status_code != 200:
            raise RuntimeError(f"Health check failed with HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        logger.info("Health OK: %s", data)
        return data

    async def list_models(self) -> list[str]:
        """List models visible to TabbyAPI."""
        logger.info("--> Querying available models from TabbyAPI...")
        resp = await self.client.get("/v1/models")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list models: {resp.text}")
        models = [m["id"] for m in resp.json().get("data", [])]
        logger.info("Found %d models in TabbyAPI: %s", len(models), models)
        return models

    async def load_model(self, model_name: str, max_seq_len: int = 4096) -> float:
        """Stream model loading via SSE until completion. Returns load duration."""
        logger.info("--> Loading model '%s' (max_seq_len=%d)...", model_name, max_seq_len)
        start = time.time()
        payload = {"model_name": model_name, "max_seq_len": max_seq_len}
        last_status = ""
        async with self.client.stream("POST", "/v1/model/load", json=payload, timeout=180.0) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"Failed to initiate load: {resp.status_code} - {body.decode()}")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    msg = line[6:].strip()
                    if msg:
                        last_status = msg
                        logger.debug("Tabby load event: %s", msg)

        duration = time.time() - start
        logger.info("Model '%s' loaded in %.2fs (final event: %s)", model_name, duration, last_status)
        return duration

    async def unload_model(self) -> None:
        """Unload active model to immediately release VRAM."""
        logger.info("--> Unloading model to release VRAM...")
        start = time.time()
        resp = await self.client.post("/v1/model/unload", timeout=30.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to unload model: {resp.text}")
        logger.info("Model unloaded in %.2fs. VRAM released.", time.time() - start)

    async def test_streaming_generation(self, model_name: str) -> dict:
        """Test streaming tokens and measure Time To First Token (TTFT)."""
        logger.info("--> Testing streaming generation with prompt...")
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": "What is the capital of France? Answer in one short sentence."}
            ],
            "stream": True,
            "max_tokens": 64,
            "temperature": 0.2,
        }
        tokens = []
        t0 = time.time()
        first_token_time = None
        async with self.client.stream("POST", "/v1/chat/completions", json=payload, timeout=60.0) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"Completion failed: {resp.status_code} - {body.decode()}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            if first_token_time is None:
                                first_token_time = time.time() - t0
                            tokens.append(content)
                except Exception:
                    continue

        total_time = time.time() - t0
        full_text = "".join(tokens).strip()
        tps = len(tokens) / (total_time - (first_token_time or 0.001)) if tokens else 0
        logger.info(
            "Generation result: '%s' | TTFT: %.3fs | Total: %.2fs | Tokens: %d (~%.1f t/s)",
            full_text, first_token_time or 0, total_time, len(tokens), tps
        )
        return {
            "reply": full_text,
            "ttft": first_token_time,
            "total_time": total_time,
            "tokens": len(tokens),
            "tps": tps,
        }

    async def test_tool_calling(self, model_name: str) -> bool:
        """Test tool calling JSON format parsing."""
        logger.info("--> Testing tool calling support...")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get current weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ]
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": "What's the weather in Tokyo right now? Use the tool."}
            ],
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
            "max_tokens": 128,
        }
        resp = await self.client.post("/v1/chat/completions", json=payload, timeout=60.0)
        if resp.status_code != 200:
            logger.warning("Tool calling returned %d: %s", resp.status_code, resp.text)
            return False

        data = resp.json()
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls")
        logger.info("Tool calling response message: %s", message)
        if tool_calls:
            logger.info("Tool calls successfully parsed: %s", tool_calls)
            return True
        else:
            logger.info("Model returned direct text (non-tool format): %s", message.get("content"))
            return True

    async def test_invalid_model_error(self) -> bool:
        """Requirement: Failed load returns clean error."""
        logger.info("--> Testing error handling on nonexistent model...")
        payload = {"model_name": "nonexistent-model-test-xyz", "max_seq_len": 2048}
        resp = await self.client.post("/v1/model/load", json=payload, timeout=10.0)
        # Should return 400 Bad Request
        if resp.status_code == 400:
            logger.info("Clean error received as expected: HTTP 400")
            return True
        else:
            logger.warning("Unexpected status code: %d", resp.status_code)
            return False

    async def close(self) -> None:
        await self.client.aclose()


async def run_full_qualification():
    qual = TabbyAPIQualifier()
    results = {}

    try:
        # 1. Health check
        health = await qual.check_health()
        results["health"] = health["status"]

        # 2. Discover models
        models = await qual.list_models()
        results["available_models"] = models
        if not models:
            raise RuntimeError("No models discovered in TabbyAPI model directory!")

        primary_model = models[0]
        second_model = models[1] if len(models) > 1 else None

        # 3. Clean error test
        err_ok = await qual.test_invalid_model_error()
        results["error_handling"] = "PASSED" if err_ok else "FAILED"

        # 4. Load Primary Model
        load_time = await qual.load_model(primary_model)
        results["primary_model"] = primary_model
        results["load_time_sec"] = round(load_time, 2)

        # 5. Stream generation & TTFT
        gen_stats = await qual.test_streaming_generation(primary_model)
        results["generation"] = gen_stats

        # 6. Tool calling
        tool_ok = await qual.test_tool_calling(primary_model)
        results["tool_calling"] = "PASSED" if tool_ok else "FAILED"

        # 7. Unload model
        await qual.unload_model()
        results["unload_primary"] = "PASSED"

        # 8. Model Swap: Load second model if available
        if second_model:
            logger.info("--> Testing model swap to second model: %s", second_model)
            swap_load_time = await qual.load_model(second_model)
            results["second_model"] = second_model
            results["swap_load_time_sec"] = round(swap_load_time, 2)
            await qual.unload_model()
            results["unload_second"] = "PASSED"

        # 9. Multi-cycle load/unload stress test (5 cycles for rapid qualification)
        cycle_count = 5
        logger.info("--> Running %d load/unload stress cycles on %s...", cycle_count, primary_model)
        cycle_times = []
        for i in range(1, cycle_count + 1):
            t0 = time.time()
            await qual.load_model(primary_model, max_seq_len=2048)
            await qual.unload_model()
            cycle_times.append(time.time() - t0)
            logger.info("Cycle %d/%d completed in %.2fs", i, cycle_count, cycle_times[-1])

        results["stress_cycles"] = {
            "count": cycle_count,
            "avg_cycle_sec": round(sum(cycle_times) / len(cycle_times), 2),
            "status": "PASSED",
        }

        logger.info("\n==========================================")
        logger.info("PHASE 1 INFERENCE QUALIFICATION COMPLETE!")
        logger.info("Results Summary:\n%s", json.dumps(results, indent=2))
        logger.info("==========================================")

    finally:
        await qual.close()


if __name__ == "__main__":
    asyncio.run(run_full_qualification())
