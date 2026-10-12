"""Generate vectors for all indexed papers through SSBridge."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from utils.semantic_search.bridge import SSBridge
    from utils.semantic_search.config import VECTORS_PATH

    data = json.loads((ROOT / "paper_index.json").read_text(encoding="utf-8"))
    for paper in data["papers"]:
        if not (ROOT / paper["method_document"]).is_file():
            raise RuntimeError(f"Missing method document: {paper['paper_id']}")
    bridge = SSBridge(
        paper_index_path=ROOT / "paper_index.json",
        paper_method_dir=ROOT / "methods",
        vectors_path=VECTORS_PATH,
    )
    print(f"Papers: {len(data['papers'])}; output: {Path(VECTORS_PATH).resolve()}", flush=True)
    saved = skipped = 0
    failed = []
    try:
        for paper in data["papers"]:
            paper_id = paper["paper_id"]
            try:
                result = bridge.create_vector(index=paper_id)
                if len(result) != 1 or result[0]["paper_id"] != paper_id:
                    raise RuntimeError("No vector result")
                if result[0]["saved"]:
                    saved += 1
                    print(paper_id, "SAVED", flush=True)
                else:
                    skipped += 1
                    print(paper_id, "EXISTS", flush=True)
            except Exception as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                print(paper_id, "FAILED:", type(error).__name__, f"HTTP {status}" if status else "", flush=True)
                failed.append(paper_id)
        counts = Counter()
        dimensions = set()
        path = Path(VECTORS_PATH)
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    counts[record["metadata"]["paper_id"]] += 1
                    dimensions.add(len(record["vector"]))
        missing = [p["paper_id"] for p in data["papers"] if not counts[p["paper_id"]]]
        print(json.dumps({"saved": saved, "skipped": skipped, "failed": failed, "missing": missing,
                          "vector_count": sum(counts.values()), "dimensions": sorted(dimensions),
                          "papers_with_vectors": len(counts)}), flush=True)
        return 1 if failed or missing else 0
    finally:
        bridge._store.transformer.client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImportError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
