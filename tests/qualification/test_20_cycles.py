import asyncio
import time
import httpx

async def main():
    admin_key = "friday-admin-token"
    headers = {"Authorization": f"Bearer {admin_key}"}
    model_name = "Mistral-Small-3.1-24B-Instruct-2503-exl3"
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5000", headers=headers, timeout=120.0) as client:
        print("Starting 20 load/unload stress cycles...")
        for i in range(1, 21):
            t0 = time.time()
            # Load
            resp = await client.post("/v1/model/load", json={"model_name": model_name, "max_seq_len": 2048})
            assert resp.status_code == 200, f"Cycle {i} load failed: {resp.text}"
            # Unload
            resp = await client.post("/v1/model/unload")
            assert resp.status_code == 200, f"Cycle {i} unload failed: {resp.text}"
            print(f"Cycle {i}/20 PASSED in {round(time.time() - t0, 2)}s")
        print("ALL 20 LOAD/UNLOAD STRESS CYCLES COMPLETED SUCCESSFULLY!")

asyncio.run(main())
