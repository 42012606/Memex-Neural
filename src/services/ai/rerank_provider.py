
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

class RerankService:
    """
    Local Rerank Service using BAAI/bge-reranker-v2-m3.
    Singleton to avoid reloading the model.
    """
    _instance = None
    _model = None
    _tokenizer = None
    _use_onnx = False
    _onnx_session = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RerankService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Lazy load will happen on first call
        pass

    def _ensure_model(self):
        if self._model or self._onnx_session:
            return
        
        try:
            # 1. Try Loading ONNX First
            import os
            import onnxruntime as ort
            from transformers import AutoTokenizer
            
            onnx_path = os.path.join("resources", "models", "bge-reranker-v2-m3-onnx", "model.onnx")
            
            if os.path.exists(onnx_path):
                logger.info(f"📥 Found ONNX model at {onnx_path}. Loading ONNX Runtime...")
                # Load Tokenizer
                model_name = "BAAI/bge-reranker-v2-m3"
                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                
                # Load ONNX Session
                # Using CPUExecutionProvider for now, can add CUDAExecutionProvider if needed
                providers = ['CPUExecutionProvider']
                if 'CUDAExecutionProvider' in ort.get_available_providers():
                    providers.insert(0, 'CUDAExecutionProvider')
                
                self._onnx_session = ort.InferenceSession(onnx_path, providers=providers)
                self._use_onnx = True
                logger.info(f"✅ Rerank service loaded in ONNX mode (Providers: {self._onnx_session.get_providers()})")
                return

            # 2. Fallback to PyTorch
            from sentence_transformers import CrossEncoder
            import torch
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_name = "BAAI/bge-reranker-v2-m3"
            
            logger.info(f"📥 ONNX model not found. Loading PyTorch model [{model_name}] on {device}...")
            self._model = CrossEncoder(model_name, max_length=1024, device=device)
            self._use_onnx = False
            logger.info(f"✅ Rerank model loaded successfully (PyTorch).")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Rerank/ONNX model: {e}", exc_info=True)
            self._model = None
            self._onnx_session = None

    def rerank(self, query: str, candidates: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """
        Rerank using ONNX or PyTorch.
        """
        if not candidates:
            return []
            
        self._ensure_model()
        
        # Determine mode
        if self._use_onnx and self._onnx_session:
            return self._rerank_onnx(query, candidates, top_k)
        elif self._model:
            return self._rerank_pytorch(query, candidates, top_k)
        else:
            raise RuntimeError("Rerank model is not available.")

    def _rerank_pytorch(self, query: str, candidates: List[str], top_k: int) -> List[Tuple[int, float]]:
        pairs = [[query, doc[:2000]] for doc in candidates]
        try:
            scores = self._model.predict(pairs)
            results = list(enumerate(scores))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]
        except Exception as e:
            logger.error(f"PyTorch Reranking failed: {e}")
            return [(i, 0.0) for i in range(len(candidates))][:top_k]

    def _rerank_onnx(self, query: str, candidates: List[str], top_k: int) -> List[Tuple[int, float]]:
        import numpy as np
        
        pairs = [[query, doc[:2000]] for doc in candidates]
        try:
            # Tokenize
            encoded_input = self._tokenizer(
                pairs, 
                padding=True, 
                truncation=True, 
                max_length=1024, 
                return_tensors="numpy"
            )
            
            inputs = {
                "input_ids": encoded_input["input_ids"].astype(np.int64),
                "attention_mask": encoded_input["attention_mask"].astype(np.int64)
            }
            
            # Inference
            # Output[0] is logits. Shape: [batch_size] (if 1D) or [batch_size, 1]
            # BGE-reranker usually outputs a single score per pair
            logits = self._onnx_session.run(None, inputs)[0]
            
            # Normalize scores (Sigmoid) if logical, but BGE-Reranker output is usually raw logits.
            # We just need to sort them. 
            # Flatten if necessary
            flat_scores = logits.flatten().tolist()
            
            results = list(enumerate(flat_scores))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"ONNX Reranking failed: {e}", exc_info=True)
            return [(i, 0.0) for i in range(len(candidates))][:top_k]
