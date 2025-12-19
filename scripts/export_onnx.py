
import os
import torch
from sentence_transformers import CrossEncoder

def export_onnx():
    print("🚀 Starting ONNX export for BAAI/bge-reranker-v2-m3...")
    
    # 1. Load PyTorch Model
    model_name = "BAAI/bge-reranker-v2-m3"
    print(f"📥 Loading model {model_name}...")
    
    # Use CPU for export
    device = "cpu"
    cross_encoder = CrossEncoder(model_name, device=device, max_length=1024)
    model = cross_encoder.model
    tokenizer = cross_encoder.tokenizer
    model.eval()
    
    # 2. Prepare Dummy Input
    # [CLS] query [SEP] doc [SEP]
    text_pairs = [("What is ONNX?", "ONNX is an open format for ML models.")]
    encoded_input = tokenizer(
        text_pairs, 
        padding=True, 
        truncation=True, 
        return_tensors="pt"
    )
    
    input_ids = encoded_input["input_ids"]
    attention_mask = encoded_input["attention_mask"]
    
    # 3. Define Output Path
    output_dir = os.path.join("resources", "models", "bge-reranker-v2-m3-onnx")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "model.onnx")
    
    print(f"💾 Exporting to {output_path}...")
    
    # 4. Export
    # Dynamic axes: critical for batching and variable sequence length
    torch.onnx.export(
        model,
        (input_ids, attention_mask),
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "logits": {0: "batch_size"}
        }
    )
    
    print(f"✅ Export completed: {output_path}")
    print("You can now simplify/quantize this model using onnxruntime tools if needed.")

if __name__ == "__main__":
    if not os.path.exists("resources"):
        os.makedirs("resources")
        
    try:
        export_onnx()
    except Exception as e:
        print(f"❌ Export failed: {e}")
