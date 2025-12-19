from typing import List, Dict, Any, Optional
import json
from datetime import datetime
from sqlalchemy.orm import Session
from src.core.database import SessionLocal
from src.models.archive import ArchiveRecord
from src.models.vector_node import VectorNode
from src.models.proposal import Proposal
from src.services.ai_service import AIService
from src.services.notification import send_webhook_notification
from src.core.prompt_manager import prompt_manager # [New]
from src.utils.text_tools import RecursiveCharacterTextSplitter
import logging

logger = logging.getLogger(__name__)

class RefinerAgent:
    """
    Gardener Agent: Refines archives into atomic VectorNodes.
    """
    
    def __init__(self, db: Session = None):
        self.db = db or SessionLocal()
        # Initialize AIService (assuming it's available as singleton or utility)
        # In this codebase, AIService might need instantiation
        self.ai_service = AIService() 

    def semantic_split(self, text: str) -> List[str]:
        """
        Hybrid Splitting Strategy:
        1. Use RecursiveCharacterTextSplitter to safely break huge text into ~3000 char blocks (preserving structure).
        2. For each block, use LLM to further refine/split into atomic semantic chunks.
        """
        # 1. Safety Split (Mechanical)
        # Using 3000 to leave room for prompt overhead and response
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=100)
        safe_blocks = text_splitter.split_text(text)
        
        final_chunks = []
        
        prompt_template = prompt_manager.get("gardener.semantic_split", default="Split the following text into self-contained semantic chunks. Return a JSON list of strings. Do not add any other text.\n\n{{ text }}")
        
        for block in safe_blocks:
            # 2. Semantic Split (LLM)
            prompt = prompt_template.replace("{{ text }}", block)
            
            try:
                response = self.ai_service.generate_text(prompt=prompt) 
                 
                # Simple heuristic cleanup
                clean_response = response.strip()
                if clean_response.startswith("```json"):
                    clean_response = clean_response[7:-3]
                elif clean_response.startswith("```"):
                    clean_response = clean_response[3:-3]
                    
                chunks = json.loads(clean_response)
                if isinstance(chunks, list):
                    final_chunks.extend(chunks)
                else:
                    logger.warning(f"LLM returned invalid format: {type(chunks)}")
                    final_chunks.append(block) # Fallback to the safe block
            except Exception as e:
                logger.error(f"Semantic split failed for block: {e}")
                final_chunks.append(block) # Fallback to safe block

        return final_chunks

    def context_enrich(self, chunk_text: str, metadata: Dict) -> str:
        """
        Use LLM to enrich chunk content (resolve pronouns, add dates).
        """
        prompt_template = prompt_manager.get("gardener.context_enrich", default="You are a context enrichment assistant... Metadata: {{ metadata }} Text Chunk: \"{{ chunk_text }}\" Return the rewritten text...")
        prompt = prompt_template.replace("{{ metadata }}", json.dumps(metadata, ensure_ascii=False)).replace("{{ chunk_text }}", chunk_text)
        try:
            # Reusing the generate_text method
            enriched_text = self.ai_service.generate_text(prompt=prompt)
            return enriched_text.strip()
        except Exception as e:
            logger.warning(f"Context enrichment failed: {e}")
            return chunk_text

    def scan_and_propose(self):
        """
        Identify Archives with NO VectorNodes and propose refinement.
        """
        # Find archives with no associated vector_nodes
        # Outer join to VectorNode where vector_node.id is null
        
        candidates = (
            self.db.query(ArchiveRecord)
            .outerjoin(VectorNode, ArchiveRecord.id == VectorNode.parent_archive_id)
            .filter(VectorNode.id == None)
            .limit(10) # Process in batches
            .all()
        )
        
        logger.info(f"Found {len(candidates)} archives to refine.")
        
        for archive in candidates:
            # Skip if file content is empty
            content = archive.full_text or archive.summary
            if not content:
                continue
                
            # Semantic split
            chunks = self.semantic_split(content)
            
            # Prepare proposal
            suggested_nodes = []
            for i, chunk in enumerate(chunks):
                enriched_chunk = self.context_enrich(chunk, archive.meta_data)
                suggested_nodes.append({
                    "chunk_index": i,
                    "content": enriched_chunk,
                    "meta": archive.meta_data
                })
            
            # Create Proposal record
            proposal_payload = {
                "archive_id": archive.id,
                "suggested_nodes": suggested_nodes
            }
            
            # Check if proposal already exists
            # Optimized simple check to avoid JSON operator issues (Postgres JSON vs JSONB)
            existing_proposals = self.db.query(Proposal).filter_by(
                type="refine_archive",
                status="pending"
            ).all()
            
            already_proposed = False
            for p in existing_proposals:
                if p.content and isinstance(p.content, dict) and p.content.get("archive_id") == archive.id:
                    already_proposed = True
                    break
            
            if already_proposed:
                continue

            new_proposal = Proposal(
                type="refine_archive",
                content=proposal_payload,
                status="pending",
                reasoning=f"Auto-generated refinement for Archive {archive.id}"
            )
            self.db.add(new_proposal)
            self.db.commit()
            logger.info(f"Created proposal for Archive {archive.id}")
            
            # Send Notification
            send_webhook_notification("proposals_ready", {
                "archive_id": archive.id,
                "proposal_id": new_proposal.id,
                "type": new_proposal.type
            })

if __name__ == "__main__":
    # Simple test run
    agent = RefinerAgent()
    agent.scan_and_propose()
