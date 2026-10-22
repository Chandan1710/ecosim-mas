"""
Check which LLM providers work with the keys in your environment / .env.

  python -m town.check_llm            # one test call per configured key
  python -m town.check_llm --models   # also list the model IDs each key can use
"""

import argparse
import asyncio

from town.llm_pool import LLMPool, PROVIDERS, load_env


async def main(show_models: bool) -> None:
    pool = LLMPool()
    if not pool.providers:
        print("No providers configured. Add at least one key to backend/.env, e.g.")
        for name, (_, key_env, model, *_rest) in PROVIDERS.items():
            if key_env:
                print(f"  {key_env}=...        (model {model})")
        print("  ECOSIM_OLLAMA=1          (local Ollama, no key)")
        return
    print(f"Testing {len(pool.providers)} provider key(s)...\n")
    results = await pool.check()
    for r in results:
        mark = "OK  " if r["ok"] else "FAIL"
        lat = f"{r.get('latency_s', '')}s" if r.get("latency_s") is not None else ""
        print(f"  [{mark}] {r['provider']:<14} {r['model']:<42} {lat:>6}  {r.get('note', '')}")
    if show_models or any("model" in r.get("note", "").lower() for r in results if not r["ok"]):
        for p in pool.providers:
            models = await pool.list_models(p)
            if models:
                print(f"\n  Models available to {p.label}: " + ", ".join(models[:40]))
    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok} of {len(results)} working.", "Agents will spread calls across all working keys." if ok else "")
    await pool.close()


if __name__ == "__main__":
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", action="store_true")
    asyncio.run(main(ap.parse_args().models))
