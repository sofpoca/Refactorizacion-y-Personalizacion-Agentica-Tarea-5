"""CLI para conversar con los agentes.

Ejemplos:
  python agent_cli.py --list
  python agent_cli.py -a auditor "dame un reporte de calidad" -d transactions_mixed.json
  python agent_cli.py -a analyst            # modo interactivo (escribe 'salir' para terminar)
  python agent_cli.py -a auditor --llm "por que se rechazaron registros?"   # planificador LLM (requiere TXN_LLM_*)
"""
from __future__ import annotations

import argparse
import sys

from txnexplorer.agents import create_agent, list_agents
from txnexplorer.llm import provider_from_env
from txnexplorer.skills import default_registry


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Agentes de txnexplorer")
    ap.add_argument("message", nargs="?", help="Mensaje para el agente (si se omite: modo interactivo)")
    ap.add_argument("-a", "--agent", default="auditor")
    ap.add_argument("-d", "--dataset", default=None, help="Dataset de data/ a usar")
    ap.add_argument("--list", action="store_true", help="Lista agentes y skills")
    ap.add_argument("--llm", action="store_true", help="Usar LLM como planificador (variables TXN_LLM_*)")
    args = ap.parse_args(argv)

    if args.list:
        print("Skills:")
        for s in default_registry().catalog():
            print(f"  - {s['name']}: {s['description']}")
        print("Agentes:")
        for a in list_agents().values():
            print(f"  - {a.id} ({a.name}): {', '.join(a.skills)}")
        return 0

    provider = None
    if args.llm:
        provider = provider_from_env()
        if provider is None:
            print("Aviso: faltan TXN_LLM_BASE_URL / TXN_LLM_API_KEY / TXN_LLM_MODEL; se usa el planificador de reglas.")
    try:
        agent = create_agent(args.agent, provider=provider)
    except KeyError as exc:
        print(exc.args[0])
        return 2

    if args.message:
        reply = agent.ask(args.message, dataset=args.dataset)
        print(reply.message)
        return 0 if reply.ok else 1
    print(f"{agent.profile.name}: {agent.profile.description}\n(escribe 'salir' para terminar)")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("salir", "exit", "quit"):
            break
        if text:
            print(agent.ask(text, dataset=args.dataset).message, "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
