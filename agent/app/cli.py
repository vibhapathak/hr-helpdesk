"""Interactive terminal chat: docker compose run --rm agent python -m app.cli"""
import asyncio
import logging
import uuid

from .graph import HelpdeskAgent


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    agent = await HelpdeskAgent.create()
    session = uuid.uuid4().hex
    print("Acme HR & IT Helpdesk — type 'exit' to quit.\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"exit", "quit"}:
            break
        if not q:
            continue
        r = await agent.ask(q, session_id=session)
        print(f"\nagent> {r['answer']}\n  [status={r['status']} tools={r['tools_used']} "
              f"redactions={r['redactions']} {r['latency_ms']}ms]\n")


if __name__ == "__main__":
    asyncio.run(main())
