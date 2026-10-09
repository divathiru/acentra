"""
Load testing script for Healthcare Operations Assistant.
Simulates ~50 concurrent users under template mode and a small run under Mistral mode.
Measures and reports p50 and p95 latencies.

Usage:
    python scripts/load_test.py [target_url] [concurrent_users]
"""

import asyncio
import math
import time
import sys
import httpx


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    sorted_v = sorted(vals)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_v[int(k)]
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return d0 + d1



DEFAULT_URL = "http://localhost:8001/chat"

SAMPLE_QUERIES = [
    "What is the policy for patient admission?",
    "I need prior authorization for an MRI scan for patient MRN-998877.",
    "Should I increase the patient's digoxin dosage from 125mcg to 250mcg daily?",
    "How long do we have to submit a claim after discharge?",
    "What is the visiting hours policy?",
]


async def send_request(client: httpx.AsyncClient, url: str, query: str, user_idx: int) -> float:
    payload = {
        "query": query,
        "user_id": f"load-test-user-{user_idx}",
        "dept_role": "ALL",
    }
    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=15.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if resp.status_code == 200:
            return elapsed_ms
        else:
            return -1.0
    except Exception:
        return -1.0


async def run_load_test(target_url: str, concurrent_users: int = 50, mode: str = "template") -> dict:
    print(f"\n🚀 Running Load Test: {concurrent_users} concurrent users ({mode} mode)")
    print(f"Target URL: {target_url}\n")

    limits = httpx.Limits(max_keepalive_connections=concurrent_users, max_connections=concurrent_users * 2)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for i in range(concurrent_users):
            query = SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)]
            tasks.append(send_request(client, target_url, query, i))

        t0 = time.perf_counter()
        latencies_ms = await asyncio.gather(*tasks)
        total_time_s = time.perf_counter() - t0

    valid_latencies = [l for l in latencies_ms if l > 0]
    failed_count = len(latencies_ms) - len(valid_latencies)

    if not valid_latencies:
        print("❌ All requests failed. Is the API server running?")
        return {"p50": 0.0, "p95": 0.0, "rps": 0.0, "success_rate": 0.0}

    p50 = float(_percentile(valid_latencies, 50))
    p95 = float(_percentile(valid_latencies, 95))
    rps = len(valid_latencies) / total_time_s if total_time_s > 0 else 0.0
    success_rate = (len(valid_latencies) / len(latencies_ms)) * 100.0

    print(f"📊 Results ({mode} mode):")
    print(f"   - Total Requests: {len(latencies_ms)}")
    print(f"   - Successful: {len(valid_latencies)} ({success_rate:.1f}%)")
    print(f"   - Failed: {failed_count}")
    print(f"   - Throughput: {rps:.2f} req/sec")
    print(f"   - p50 Latency: {p50:.2f} ms")
    print(f"   - p95 Latency: {p95:.2f} ms")

    return {
        "mode": mode,
        "concurrent_users": concurrent_users,
        "total_requests": len(latencies_ms),
        "success_rate": round(success_rate, 1),
        "rps": round(rps, 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
    }


async def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL

    # Run 1: 50 Concurrent users in template mode
    res_template = await run_load_test(target_url, concurrent_users=50, mode="template")

    # Run 2: Small run in Mistral mode (5 concurrent users)
    res_mistral = await run_load_test(target_url, concurrent_users=5, mode="mistral")

    print("\n=======================================================")
    print(" SUMMARY LOAD TEST REPORT")
    print("=======================================================")
    print(f" Mode: TEMPLATE | Concurrent: 50 | p50: {res_template['p50_ms']}ms | p95: {res_template['p95_ms']}ms")
    print(f" Mode: MISTRAL  | Concurrent:  5 | p50: {res_mistral['p50_ms']}ms | p95: {res_mistral['p95_ms']}ms")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
