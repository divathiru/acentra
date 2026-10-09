"""Public interface for knowledge retrieval."""

import uuid
import networkx as nx
from datetime import date
from typing import List, Optional, Dict, Any

from pydantic import BaseModel
from sqlalchemy import select, and_, or_, exists, desc, func
from sqlalchemy.orm import Session

from app.core.models import GraphVersion, Node, NodeVisibility, Edge, NodeChunk
from app.knowledge.embedders import MistralEmbedder, FakeEmbedder
from app.core.config import get_settings

class RetrieveFlags(BaseModel):
    use_fts: bool = True
    use_graph: bool = True

class EvidenceBundle(BaseModel):
    nodes: Dict[str, dict]
    edges: List[dict]
    entry_nodes: List[str]
    rrf_scores: Dict[str, float]
    top1_cosine: float
    conflict_flag: bool
    conflict_owners: List[str]
    superseded_notes: Dict[str, str]

# Global cache for NetworkX graph
_GRAPH_CACHE: Dict[uuid.UUID, nx.DiGraph] = {}

def get_active_version_id(session: Session) -> Optional[uuid.UUID]:
    res = session.execute(
        select(GraphVersion.id).where(GraphVersion.status == "active")
    )
    return res.scalar_one_or_none()

def _get_or_build_graph(session: Session, version_id: uuid.UUID) -> nx.DiGraph:
    if version_id in _GRAPH_CACHE:
        return _GRAPH_CACHE[version_id]
        
    G = nx.DiGraph()
    # allow-list of edge types (structural and approved origins only)
    edges = session.execute(
        select(Edge).where(
            Edge.version_id == version_id,
            Edge.origin.in_(["structural", "approved"])
        )
    ).scalars().all()
    
    for e in edges:
        G.add_edge(str(e.from_id), str(e.to_id), type=e.type)
        
    _GRAPH_CACHE[version_id] = G
    return G

def _visibility_clause(roles: List[str], version_id: uuid.UUID):
    allowed_roles = roles + ["ALL"]
    return exists().where(
        and_(
            NodeVisibility.node_id == Node.id,
            NodeVisibility.version_id == version_id,
            NodeVisibility.role_id.in_(allowed_roles)
        )
    )

async def retrieve(session: Session, query: str, dept_role: str, flags: RetrieveFlags) -> EvidenceBundle:
    version_id = get_active_version_id(session)
    if not version_id:
        return EvidenceBundle(
            nodes={}, edges=[], entry_nodes=[], rrf_scores={},
            top1_cosine=0.0, conflict_flag=False, conflict_owners=[], superseded_notes={}
        )

    settings = get_settings()
    embedder = MistralEmbedder() if settings.MISTRAL_API_KEY else FakeEmbedder()
    
    q_emb_list = await embedder.embed([query])
    q_emb = q_emb_list[0]
    
    roles = [dept_role]
    today = date.today()
    
    base_node_cond = and_(
        Node.version_id == version_id,
        Node.status == 'approved',
        or_(Node.effective_date == None, Node.effective_date <= today),
        _visibility_clause(roles, version_id)
    )
    
    # 1. Vector top-20
    vector_res = session.execute(
        select(Node.id, NodeChunk.embedding.cosine_distance(q_emb).label('dist'))
        .join(NodeChunk, NodeChunk.node_id == Node.id)
        .where(
            NodeChunk.version_id == version_id,
            base_node_cond
        )
        .order_by('dist')
        .limit(20)
    ).all()
    
    vector_ranks = {}
    top1_cosine = 0.0
    for i, row in enumerate(vector_res):
        nid = str(row.id)
        if nid not in vector_ranks:
            vector_ranks[nid] = i + 1
        if i == 0:
            top1_cosine = 1.0 - row.dist

    # 2. FTS top-20
    fts_ranks = {}
    if flags.use_fts:
        fts_res = session.execute(
            select(Node.id, func.ts_rank(NodeChunk.tsv, func.websearch_to_tsquery('english', query)).label('rank'))
            .join(NodeChunk, NodeChunk.node_id == Node.id)
            .where(
                NodeChunk.version_id == version_id,
                base_node_cond,
                NodeChunk.tsv.op('@@')(func.websearch_to_tsquery('english', query))
            )
            .order_by(desc('rank'))
            .limit(20)
        ).all()
        for i, row in enumerate(fts_res):
            nid = str(row.id)
            if nid not in fts_ranks:
                fts_ranks[nid] = i + 1

    # RRF Fusion (k=60)
    rrf_scores = {}
    all_nids = set(vector_ranks.keys()).union(set(fts_ranks.keys()))
    k = 60
    for nid in all_nids:
        score = 0.0
        if nid in vector_ranks:
            score += 1.0 / (k + vector_ranks[nid])
        if nid in fts_ranks:
            score += 1.0 / (k + fts_ranks[nid])
        rrf_scores[nid] = score
        
    sorted_nids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    top5_nids = [x[0] for x in sorted_nids[:5]]
    
    # 4. Superseded handling
    superseded_notes = {}
    entry_nodes = []
    
    for nid in top5_nids:
        sup_edge = session.execute(
            select(Edge.to_id).where(
                Edge.from_id == uuid.UUID(nid),
                Edge.type == 'supersedes',
                Edge.version_id == version_id
            )
        ).scalars().first()
        
        if sup_edge:
            new_id = str(sup_edge)
            superseded_notes[new_id] = f"Supersedes old node {nid}"
            if new_id not in entry_nodes:
                entry_nodes.append(new_id)
        else:
            if nid not in entry_nodes:
                entry_nodes.append(nid)
            
    # 3. Graph expansion
    expanded_nodes = set(entry_nodes)
    
    if flags.use_graph and entry_nodes:
        G = _get_or_build_graph(session, version_id)
        
        def check_node(n_id_str: str) -> bool:
            res = session.execute(
                select(Node.id).where(
                    Node.id == uuid.UUID(n_id_str),
                    base_node_cond
                )
            ).scalars().first()
            return res is not None

        queue = [(n, 0) for n in entry_nodes]
        visited = set(entry_nodes)
        
        while queue and len(expanded_nodes) < 15:
            curr, depth = queue.pop(0)
            if depth >= 2:
                continue
                
            if curr not in G:
                continue
                
            neighbors = list(G.successors(curr)) + list(G.predecessors(curr))
            neighbors = sorted(neighbors, key=lambda x: G.degree(x) if x in G else 0)
            
            for nbr in neighbors:
                if len(expanded_nodes) >= 15:
                    break
                if nbr not in visited:
                    visited.add(nbr)
                    if check_node(nbr):
                        expanded_nodes.add(nbr)
                        queue.append((nbr, depth + 1))
                        
    # Fetch all edges between expanded nodes
    edges_out = []
    if expanded_nodes:
        node_ids = [uuid.UUID(n) for n in expanded_nodes]
        all_edges = session.execute(
            select(Edge).where(
                Edge.from_id.in_(node_ids),
                Edge.to_id.in_(node_ids),
                Edge.version_id == version_id
            )
        ).scalars().all()
        for e in all_edges:
            edges_out.append({"from_id": str(e.from_id), "to_id": str(e.to_id), "type": e.type})
            
    # 5. Conflict handling and node hydration
    nodes_out = {}
    conflict_flag = False
    conflict_owners = set()
    
    if expanded_nodes:
        node_ids = [uuid.UUID(n) for n in expanded_nodes]
        node_objs = session.execute(
            select(Node).where(Node.id.in_(node_ids), Node.version_id == version_id)
        ).scalars().all()
        
        for n in node_objs:
            nid = str(n.id)
            nodes_out[nid] = {
                "id": nid,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "owner": n.owner,
            }
            
            c_edges = session.execute(
                select(Edge.to_id).where(
                    Edge.from_id == n.id,
                    Edge.version_id == version_id,
                    Edge.type == 'conflicts_with'
                )
            ).scalars().all()
            
            if c_edges:
                conflict_flag = True
                if n.owner:
                    conflict_owners.add(n.owner)
                for ce in c_edges:
                    co_node = session.execute(select(Node.owner).where(Node.id == ce, Node.version_id == version_id)).scalars().first()
                    if co_node:
                        conflict_owners.add(co_node)
                        
    return EvidenceBundle(
        nodes=nodes_out,
        edges=edges_out,
        entry_nodes=entry_nodes,
        rrf_scores={k: v for k, v in rrf_scores.items() if k in entry_nodes},
        top1_cosine=top1_cosine,
        conflict_flag=conflict_flag,
        conflict_owners=list(conflict_owners),
        superseded_notes=superseded_notes
    )
