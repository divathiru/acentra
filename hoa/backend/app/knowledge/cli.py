"""CLI for testing knowledge retrieval."""

import asyncio
import argparse
import json
from rich import print

from app.core.database import SessionLocal
from app.knowledge.api import retrieve, RetrieveFlags
from app.knowledge.verify import verify_evidence
from app.core.models import DomainConfig

def _get_domain_config(session) -> dict:
    from sqlalchemy import select
    res = session.execute(select(DomainConfig)).scalars().all()
    config = {}
    for c in res:
        config[c.key] = c.value
    return config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--role", default="ALL")
    parser.add_argument("--no-graph", action="store_true")
    parser.add_argument("--no-fts", action="store_true")
    args = parser.parse_args()
    
    flags = RetrieveFlags(use_fts=not args.no_fts, use_graph=not args.no_graph)
    
    with SessionLocal() as session:
        bundle = asyncio.run(retrieve(session, args.query, args.role, flags))
        
        config = _get_domain_config(session)
        verif = verify_evidence(bundle, expected_entities=1, resolved_entities=1, config=config)
        
        print("[bold green]Evidence Bundle:[/bold green]")
        print(f"Nodes retrieved: {len(bundle.nodes)}")
        print(f"Edges retrieved: {len(bundle.edges)}")
        print(f"Top 1 Cosine: {bundle.top1_cosine:.4f}")
        print(f"Conflict Flag: {bundle.conflict_flag}")
        if bundle.conflict_flag:
            print(f"Conflict Owners: {bundle.conflict_owners}")
            
        if bundle.superseded_notes:
            print("[bold yellow]Superseded Notes:[/bold yellow]")
            for k, v in bundle.superseded_notes.items():
                print(f"  {k}: {v}")
                
        print("\n[bold cyan]Verification Results:[/bold cyan]")
        print(f"Score: {verif['score']:.4f}")
        print(f"Band: {verif['band']}")
        print(f"Conflict: {verif['conflict']}")
        print("Coverage:")
        for k, v in verif['coverage'].items():
            print(f"  {k}: {v}")
        print("Reasons:")
        for r in verif['reasons']:
            print(f"  - {r}")

if __name__ == "__main__":
    main()
