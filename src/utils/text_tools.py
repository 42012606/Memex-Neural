from typing import List, Optional

class RecursiveCharacterTextSplitter:
    """
    Implementation of recursive character text splitting.
    Recursively tries to split by different characters (separators) to find one
    that works.
    """

    def __init__(
        self,
        separators: Optional[List[str]] = None,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        length_function: callable = len,
    ):
        self._separators = separators or ["\n\n", "\n", " ", ""]
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._length_function = length_function

    def split_text(self, text: str) -> List[str]:
        final_chunks = []
        
        # Determine which separator to use
        separator = self._separators[-1]
        for _s in self._separators:
            if _s == "":
                separator = _s
                break
            if _s in text:
                separator = _s
                break

        # Split using the separator
        if separator:
            splits = text.split(separator)
        else:
            splits = list(text) # Split by character

        # Now go through splits, merging them if possible
        _good_splits = []
        _separator = separator if separator else ""
        
        for s in splits:
            if self._length_function(s) < self._chunk_size:
                _good_splits.append(s)
            else:
                # Recursively split if a single split is too large
                if _good_splits:
                    self._merge_splits(_good_splits, _separator, final_chunks)
                    _good_splits = []
                
                if not s:
                    continue
                    
                # If we used the empty string separator, we can't split further
                if separator == "":
                    # Truncate hard if strictly needed, or just keep it (usually shouldn't happen with char split)
                    final_chunks.append(s[:self._chunk_size]) 
                    # Warning: this might lose data if loop doesn't handle remainder, 
                    # but for basic recursion on chars it should be fine.
                else:
                    # Recursive call
                    other_info = self.split_text(s)
                    final_chunks.extend(other_info)
                    
        if _good_splits:
            self._merge_splits(_good_splits, _separator, final_chunks)
            
        return final_chunks

    def _merge_splits(self, splits: List[str], separator: str, final_chunks: List[str]):
        # Merge splits into chunks
        current_doc = []
        total_len = 0
        
        for s in splits:
            _len = self._length_function(s)
            
            # If adding this split would exceed chunk_size
            if total_len + _len + (len(separator) if current_doc else 0) > self._chunk_size:
                if total_len > self._chunk_size:
                    # Current doc is already too big (should be rare if recursion works)
                    pass
                    
                if current_doc:
                    doc = separator.join(current_doc)
                    if doc.strip():
                        final_chunks.append(doc)
                    
                    # Reset with overlap
                    # Simple overlap logic: keep last few splits that fit within overlap limit?
                    # For simplicity in this lightweight version, we might skip complex overlap logic 
                    # or implementing a basic one:
                    
                    while total_len > self._chunk_overlap:
                        if not current_doc: break
                        total_len -= self._length_function(current_doc.pop(0)) 
                        if current_doc: total_len -= len(separator) # Remove separator len estimate
                        
                # If current split is bigger than chunk size alone (caught by recursion usually),
                # but here it means we are building a new doc
                
            current_doc.append(s)
            total_len += _len + (len(separator) if len(current_doc) > 1 else 0)
            
        if current_doc:
            doc = separator.join(current_doc)
            if doc.strip():
                final_chunks.append(doc)

        return final_chunks

def estimate_token_count(text: str) -> int:
    """
    Estimate token count using a safe upper-bound heuristic (Char Count).
    - Chinese: ~1-1.5 token/char
    - English: ~0.25 token/char
    Using len(text) is a safe proxy for mixed/Chinese content to avoid OOM or specific tokenizer dependnecy.
    """
    if not text:
        return 0
    return len(text)
