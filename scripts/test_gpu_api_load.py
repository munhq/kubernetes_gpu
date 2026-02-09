#!/usr/bin/env python3
"""
Load test for GPU API batch inference endpoint.
Sends 100 concurrent batch jobs to demonstrate:
- Concurrent request handling (all jobs fire to vLLM immediately)
- Ray Serve load balancing across vLLM replicas
- End-to-end latency through the full stack (API → Ray Serve → vLLM → results)
- Throughput under sustained load

Usage:
    # Port-forward the GPU API service first:
    kubectl port-forward svc/gpu-api -n gpu-workloads 8000:8000
    # Then run:
    python3 scripts/test_gpu_api_load.py
"""

import asyncio
import aiohttp
import time
import random
from datetime import datetime

API_URL = "http://localhost:8000"
API_KEY = None  # Set below from env or arg

# 100 diverse prompts — each becomes a separate batch job
PROMPTS = [
    "Explain quantum computing",
    "What is 2+2?",
    "Write a haiku about mountains",
    "Describe machine learning in detail",
    "List 5 programming languages",
    "Tell me a short story about a robot",
    "What is Python?",
    "Explain neural networks briefly",
    "What's the capital of France?",
    "Describe the water cycle",
    "What is recursion?",
    "Write a poem about the ocean",
    "Explain Docker containers",
    "What is AI?",
    "Describe photosynthesis",
    "What are microservices?",
    "Explain REST APIs",
    "What is Kubernetes?",
    "Tell me about black holes",
    "What is Git?",
    "Explain TCP/IP in simple terms",
    "What is a database index?",
    "Describe the OSI model briefly",
    "What are GPUs used for?",
    "Explain MapReduce",
    "What is a hash table?",
    "Describe the CAP theorem",
    "What is CUDA?",
    "Explain gradient descent",
    "What is a transformer model?",
    "Describe the actor model in programming",
    "What is a load balancer?",
    "Explain eventual consistency",
    "What is WebAssembly?",
    "Describe how DNS works",
    "What is a bloom filter?",
    "Explain the PageRank algorithm",
    "What is edge computing?",
    "Describe consensus algorithms",
    "What is RLHF?",
    "Explain batch normalization",
    "What is a service mesh?",
    "Describe the Raft protocol",
    "What is tensor parallelism?",
    "Explain attention mechanism",
    "What is a priority queue?",
    "Describe the pub/sub pattern",
    "What is speculative decoding?",
    "Explain KV cache in LLMs",
    "What is continuous batching?",
    "Describe Ray framework",
    "What is model sharding?",
    "Explain pipeline parallelism",
    "What is quantization in ML?",
    "Describe the NCCL library",
    "What is flash attention?",
    "Explain prefix caching",
    "What is chunked prefill?",
    "Describe vLLM architecture",
    "What is PagedAttention?",
    "Explain beam search decoding",
    "What is top-k sampling?",
    "Describe nucleus sampling",
    "What is temperature in LLMs?",
    "Explain the softmax function",
    "What is cross-entropy loss?",
    "Describe backpropagation briefly",
    "What is a learning rate?",
    "Explain dropout regularization",
    "What is batch inference?",
    "Describe model serving patterns",
    "What is A/B testing for models?",
    "Explain canary deployments",
    "What is blue-green deployment?",
    "Describe feature flags",
    "What is observability?",
    "Explain the RED method",
    "What is distributed tracing?",
    "Describe SLOs vs SLAs",
    "What is chaos engineering?",
    "Explain the circuit breaker pattern",
    "What is rate limiting?",
    "Describe token bucket algorithm",
    "What is backpressure?",
    "Explain the bulkhead pattern",
    "What is an event loop?",
    "Describe coroutines vs threads",
    "What is zero-copy networking?",
    "Explain io_uring",
    "What is eBPF?",
    "Describe DPDK briefly",
    "What is RDMA?",
    "Explain NVLink",
    "What is InfiniBand?",
    "Describe PCIe gen5",
    "What is CXL memory?",
    "Explain HBM memory",
    "What is memory bandwidth?",
    "Describe the roofline model",
]

PRIORITIES = ["high", "medium", "low"]
PRIORITY_WEIGHTS = [0.2, 0.5, 0.3]  # 20% high, 50% medium, 30% low


async def submit_job(session: aiohttp.ClientSession, prompt: str, priority: str, max_tokens: int, job_num: int):
    """Submit a single batch job to the GPU API."""
    payload = {
        "model": "qwen2.5-0.5b-instruct",
        "input": [{"prompt": prompt}],
        "max_tokens": max_tokens,
        "priority": priority,
    }
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }

    start = time.time()
    try:
        async with session.post(f"{API_URL}/v1/batches", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            result = await resp.json()
            submit_latency = time.time() - start
            if resp.status == 202:
                return {
                    "num": job_num,
                    "job_id": result["job_id"],
                    "priority": priority,
                    "prompt": prompt[:40],
                    "max_tokens": max_tokens,
                    "submit_latency": submit_latency,
                    "status": "submitted",
                }
            else:
                return {
                    "num": job_num,
                    "status": "submit_failed",
                    "error": str(result),
                    "submit_latency": submit_latency,
                }
    except Exception as e:
        return {
            "num": job_num,
            "status": "submit_error",
            "error": str(e),
            "submit_latency": time.time() - start,
        }


async def poll_job(session: aiohttp.ClientSession, job_id: str, timeout: float = 300):
    """Poll a job until it reaches a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            async with session.get(f"{API_URL}/v1/batches/{job_id}", headers={"X-API-Key": API_KEY}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data["status"] in ("SUCCEEDED", "FAILED"):
                        return data
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return {"status": "TIMEOUT", "job_id": job_id}


async def run_load_test():
    print(f"\n{'='*80}")
    print(f"GPU API Load Test — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")
    print(f"Endpoint:   {API_URL}")
    print(f"Jobs:       {len(PROMPTS)}")
    print(f"Priorities: 20% high, 50% medium, 30% low")
    print(f"{'='*80}\n")

    # Assign random priorities and token counts
    jobs_spec = []
    for i, prompt in enumerate(PROMPTS):
        priority = random.choices(PRIORITIES, weights=PRIORITY_WEIGHTS, k=1)[0]
        max_tokens = random.choice([32, 64, 128])
        jobs_spec.append((prompt, priority, max_tokens, i + 1))

    priority_counts = {p: sum(1 for _, pr, _, _ in jobs_spec if pr == p) for p in PRIORITIES}
    print(f"Priority distribution: high={priority_counts['high']} medium={priority_counts['medium']} low={priority_counts['low']}")

    # Phase 1: Submit all jobs concurrently
    print(f"\n[Phase 1] Submitting {len(jobs_spec)} jobs concurrently...")
    submit_start = time.time()

    async with aiohttp.ClientSession() as session:
        submit_tasks = [
            submit_job(session, prompt, priority, max_tokens, num)
            for prompt, priority, max_tokens, num in jobs_spec
        ]
        submit_results = await asyncio.gather(*submit_tasks)

    submit_time = time.time() - submit_start
    submitted = [r for r in submit_results if r["status"] == "submitted"]
    submit_failed = [r for r in submit_results if r["status"] != "submitted"]

    print(f"    Submitted: {len(submitted)} in {submit_time:.2f}s ({len(submitted)/submit_time:.0f} jobs/sec)")
    if submit_failed:
        print(f"    Failed to submit: {len(submit_failed)}")
        for f in submit_failed[:3]:
            print(f"      [{f['num']}] {f.get('error', 'unknown')}")

    # Phase 2: Poll all jobs to completion
    print(f"\n[Phase 2] Waiting for {len(submitted)} jobs to complete...")
    poll_start = time.time()

    async with aiohttp.ClientSession() as session:
        poll_tasks = [poll_job(session, r["job_id"]) for r in submitted]
        poll_results = await asyncio.gather(*poll_tasks)

    poll_time = time.time() - poll_start
    total_time = time.time() - submit_start

    # Merge submit info with poll results
    job_id_to_submit = {r["job_id"]: r for r in submitted}
    final_results = []
    for poll_res in poll_results:
        job_id = poll_res.get("job_id", "")
        submit_info = job_id_to_submit.get(job_id, {})
        final_results.append({**submit_info, **poll_res})

    succeeded = [r for r in final_results if r.get("status") == "SUCCEEDED"]
    failed = [r for r in final_results if r.get("status") == "FAILED"]
    timed_out = [r for r in final_results if r.get("status") == "TIMEOUT"]

    # Results summary
    print(f"\n{'='*80}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"Total jobs:        {len(PROMPTS)}")
    print(f"Submitted:         {len(submitted)}")
    print(f"Succeeded:         {len(succeeded)}")
    print(f"Failed:            {len(failed)}")
    print(f"Timed out:         {len(timed_out)}")
    print(f"Submit phase:      {submit_time:.2f}s")
    print(f"Processing phase:  {poll_time:.2f}s")
    print(f"Total wall time:   {total_time:.2f}s")
    print(f"Throughput:        {len(succeeded)/total_time:.2f} jobs/sec")

    # Priority breakdown
    print(f"\nBY PRIORITY:")
    for p in PRIORITIES:
        p_jobs = [r for r in final_results if r.get("priority") == p]
        p_ok = [r for r in p_jobs if r.get("status") == "SUCCEEDED"]
        print(f"  {p:6s}: {len(p_ok)}/{len(p_jobs)} succeeded")

    if failed:
        print(f"\nFAILED JOBS ({len(failed)}):")
        for r in failed[:5]:
            print(f"  [{r.get('num', '?')}] {r.get('message', 'no message')[:80]}")

    print(f"\n{'='*80}")
    print(f"Done. Check Grafana for dashboard updates.")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    import sys
    import os

    API_KEY = os.environ.get("GPU_API_KEY")
    if not API_KEY:
        if len(sys.argv) > 1:
            API_KEY = sys.argv[1]
        else:
            print("Usage: GPU_API_KEY=<key> python3 test_gpu_api_load.py")
            print("   or: python3 test_gpu_api_load.py <api-key>")
            sys.exit(1)

    if len(sys.argv) > 2:
        API_URL = sys.argv[2]

    asyncio.run(run_load_test())
