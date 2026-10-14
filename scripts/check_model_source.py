"""Check published QPack metadata without downloading the model weights."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "Leonickson/Qwen3.6-35B-A3B-qpack"


def fetch(url):
    request = Request(url, headers={"User-Agent": "PrivAI-build-verification"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    model = fetch(f"https://huggingface.co/api/models/{REPO}")
    revision = model["sha"]
    base = f"https://huggingface.co/{REPO}/resolve/{revision}"
    manifest = fetch(f"{base}/manifest.json")
    layout = fetch(f"{base}/packed_experts/layout.json")
    config = fetch(f"{base}/config.json")
    text = config.get("text_config", config)
    assert manifest["magic"] == "QPACK" and manifest["version"] == 1
    assert manifest["quantBits"] == 4 and manifest["quantGroupSize"] == 64
    assert text["model_type"] == "qwen3_5_moe_text"
    assert text["num_hidden_layers"] == layout["layerCount"] == 40
    assert text["num_experts"] == layout["expertCount"] == 256
    assert text["num_experts_per_tok"] == 8
    per_layer = layout["expertStride"] * layout["expertCount"]
    for layer in range(layout["layerCount"]):
        assert manifest["files"][f"packed_experts/layer_{layer:02}.bin"] == per_layer
    # This endpoint's size metadata checks the published files, not just the manifest.
    remote_files = {}
    url = f"https://huggingface.co/api/models/{REPO}/tree/{revision}?recursive=true&limit=1000"
    for item in fetch(url):
        if item["type"] == "file":
            remote_files[item["path"]] = item["size"]
    for name, size in manifest["files"].items():
        assert remote_files.get(name) == size, f"Missing or wrong-size remote file: {name}"
    for section in layout["sections"]:
        assert section["offset"] >= 0 and section["offset"] + section["size"] <= layout["expertStride"]
    result = {
        "repository": REPO, "revision": revision,
        "container_bytes": sum(manifest["files"].values()),
        "dense_file_bytes": manifest["files"]["model.safetensors"],
        "layers": layout["layerCount"], "experts_per_layer": layout["expertCount"],
        "expert_stride_bytes": layout["expertStride"],
        "checks": "manifest, architecture, quantization, all remote file sizes, expert layout",
        "device_inference": "UNVERIFIED",
    }
    print(json.dumps(result, indent=2))
    output = Path("build/model-source-verification.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
