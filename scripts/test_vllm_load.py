#!/usr/bin/env python3
"""
Load test script for Ray Serve vLLM endpoint
Sends 20 concurrent requests with varying token counts to test:
- Continuous batching
- Autoscaling behavior
- GPU utilization
- Response latency
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime

# Different prompts with varying complexity
PROMPTS = [
    ("Explain quantum computing", 50),
    ("What is 2+2?", 10),
    ("Write a haiku about mountains", 30),
    ("Describe machine learning in detail", 100),
    ("List 5 programming languages", 20),
    ("Tell me a short story", 80),
    ("What is Python?", 15),
    ("Explain neural networks", 60),
    ("What's the capital of France?", 10),
    ("Describe the water cycle", 40),
    ("What is recursion?", 25),
    ("Write a poem about the ocean", 50),
    ("Explain Docker containers", 70),
    ("What is AI?", 15),
    ("Describe photosynthesis", 45),
    ("What are microservices?", 35),
    ("Explain REST APIs", 40),
    ("What is Kubernetes?", 30),
    ("Tell me about black holes", 60),
    ("What is Git?", 20),
]

ENDPOINT = "http://localhost:8000/v1/completions"
# If running from outside cluster with port-forward, use: http://localhost:8000/v1/completions
# If running from a different pod, use: http://raycluster-batch-inference-serve-svc.gpu-workloads.svc.cluster.local:8000/v1/completions

async def send_request(session, prompt, max_tokens, request_id):
    """Send a single inference request"""
    payload = {
        "model": "qwen2.5-0.5b-instruct",
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    start_time = time.time()
    try:
        async with session.post(ENDPOINT, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            result = await resp.json()
            latency = time.time() - start_time

            if resp.status == 200:
                output_text = result['choices'][0]['text']
                tokens = result['usage']
                return {
                    'id': request_id,
                    'status': 'success',
                    'prompt': prompt[:50] + '...' if len(prompt) > 50 else prompt,
                    'max_tokens': max_tokens,
                    'latency': latency,
                    'tokens': tokens,
                    'output': output_text[:100] + '...' if len(output_text) > 100 else output_text
                }
            else:
                return {
                    'id': request_id,
                    'status': 'error',
                    'error': await resp.text(),
                    'latency': latency
                }
    except asyncio.TimeoutError:
        return {
            'id': request_id,
            'status': 'timeout',
            'latency': time.time() - start_time
        }
    except Exception as e:
        return {
            'id': request_id,
            'status': 'exception',
            'error': str(e),
            'latency': time.time() - start_time
        }

async def run_load_test():
    """Run the load test with 20 concurrent requests"""
    print(f"\n{'='*80}")
    print(f"Ray Serve vLLM Load Test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Requests: {len(PROMPTS)} concurrent")
    print(f"{'='*80}\n")

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            send_request(session, prompt, max_tokens, i+1)
            for i, (prompt, max_tokens) in enumerate(PROMPTS)
        ]

        # Send all requests concurrently
        results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time

    # Analyze results
    successful = [r for r in results if r['status'] == 'success']
    failed = [r for r in results if r['status'] != 'success']

    print(f"\n{'='*80}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"Total requests:     {len(results)}")
    print(f"Successful:         {len(successful)}")
    print(f"Failed:             {len(failed)}")
    print(f"Total time:         {total_time:.2f}s")
    print(f"Requests/sec:       {len(results)/total_time:.2f}")

    if successful:
        latencies = [r['latency'] for r in successful]
        total_tokens = sum(r['tokens']['total_tokens'] for r in successful)

        print(f"\nLATENCY STATS:")
        print(f"  Min:              {min(latencies):.2f}s")
        print(f"  Max:              {max(latencies):.2f}s")
        print(f"  Mean:             {sum(latencies)/len(latencies):.2f}s")
        print(f"  Median:           {sorted(latencies)[len(latencies)//2]:.2f}s")

        print(f"\nTOKEN STATS:")
        print(f"  Total tokens:     {total_tokens}")
        print(f"  Tokens/sec:       {total_tokens/total_time:.2f}")

        print(f"\n{'='*80}")
        print(f"DETAILED RESULTS (sorted by latency)")
        print(f"{'='*80}")
        successful_sorted = sorted(successful, key=lambda x: x['latency'])

        for r in successful_sorted:
            print(f"\n[{r['id']:2d}] {r['prompt']}")
            print(f"     Max tokens: {r['max_tokens']}, Latency: {r['latency']:.2f}s")
            print(f"     Usage: {r['tokens']['prompt_tokens']} prompt + {r['tokens']['completion_tokens']} completion = {r['tokens']['total_tokens']} total")
            print(f"     Output: {r['output']}")

    if failed:
        print(f"\n{'='*80}")
        print(f"FAILED REQUESTS")
        print(f"{'='*80}")
        for r in failed:
            print(f"[{r['id']:2d}] Status: {r['status']}, Error: {r.get('error', 'N/A')}")

    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    asyncio.run(run_load_test())
