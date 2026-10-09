"""Knowledge graph validation."""
import re
from typing import Dict, Any, List
import structlog

logger = structlog.get_logger(__name__)

class GraphValidator:
    def __init__(self, domain_config: Dict[str, Any]) -> None:
        self.domain = domain_config
        self.injection_patterns = [
            re.compile(p, re.IGNORECASE) 
            for p in self.domain.get("prompt_injection_patterns", [])
        ]
        
    def validate(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[str]:
        errors = []
        node_ids = {n["id"] for n in nodes}
        
        # Broken references
        for edge in edges:
            if edge["from_id"] not in node_ids:
                errors.append(f"Broken edge {edge['type']}: from_id {edge['from_id']} missing")
            if edge["to_id"] not in node_ids:
                errors.append(f"Broken edge {edge['type']}: to_id {edge['to_id']} missing")
                
        # Cycles (simple self-edge check for now)
        for edge in edges:
            if edge["from_id"] == edge["to_id"]:
                errors.append(f"Self-referencing edge found on node {edge['from_id']}")
                
        # Orphan steps
        step_ids = {n["id"] for n in nodes if n["type"] == "step"}
        linked_steps = {e["to_id"] for e in edges if e["type"] == "has_step"}
        orphan_steps = step_ids - linked_steps
        if orphan_steps:
            for step in orphan_steps:
                errors.append(f"Orphan step detected: {step}")
                
        # Workflows with no governing article
        workflow_ids = {n["id"] for n in nodes if n["type"] == "workflow"}
        linked_workflows = {e["from_id"] for e in edges if e["type"] == "defined_in"}
        missing_articles = workflow_ids - linked_workflows
        if missing_articles:
            for wf in missing_articles:
                errors.append(f"Workflow missing governing article: {wf}")
                
        # Quarantine prompt injection in article bodies
        for node in nodes:
            if node["type"] == "article":
                body = node.get("body", "")
                for p in self.injection_patterns:
                    if p.search(body):
                        errors.append(f"PROMPT INJECTION DETECTED in article {node['id']}")
                        break
                        
        return errors
