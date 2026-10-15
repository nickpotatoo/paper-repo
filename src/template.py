"""Templates for the paper repo's three data files."""

_papers_template = []
_taxonomy_template = {"category_index": {}, "tag_index": {}, "document_type_index": {}}
_repo_state_template = {"paper_id_counter": 0}
_paper_template = {
    "paper_id": "",
    "metadata": {
        "title": "", "original_filename": "", "filename": "", "sha256": "",
        "document_type": "", "authors": None, "year": None,
    },
    "classification": {"primary_category": "", "tags": []},
    "summary": "",
    "added_at": "",
}
