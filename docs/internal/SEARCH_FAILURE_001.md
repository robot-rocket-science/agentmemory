# Search Failure 001: ID Namespace Bridge (2026-04-11)

## Query that failed
"belief ID scanner node ID mapping namespace bridge content hash"
"onboard ingestion store belief ID alongside scanner node observation link"

## What we were looking for
How to automatically bridge the gap between scanner node IDs (like `file:src/main.py`, `doc:README.md:s:5`) and belief IDs (UUIDs like `a7b23...`). This was discussed in the current session and a solution exists in the codebase.

## What search returned
Generic results about project IDs, node IDs, FTS5 filtering, BFS requirements. Nothing about the specific content-hash dedup mechanism that IS the bridge.

## The actual answer
`store.insert_belief()` does content-hash dedup: when the same text is inserted, it returns the existing belief. During onboard, scanner node content IS the belief content. The content hash is the bridge:
- Scanner node: `doc:README.md:s:5` with content "The system uses SQLite for storage"
- Belief: ID `a7b23...` with content_hash `sha256("The system uses SQLite for storage")[:12]`
- They share the same content, so content_hash links them

The automated mapping is: during onboard, after `ingest_turn` processes a scanner node, look up the belief by content_hash to get the belief ID. Store `(scanner_node_id, belief_id)` in graph_edges.

## Why search failed
1. The solution involves an implicit mechanism (content-hash dedup) not an explicit "mapping" or "bridge"
2. The vocabulary of the solution ("content hash", "dedup", "returns existing") doesn't overlap with the vocabulary of the problem ("namespace bridge", "ID mapping", "scanner node")
3. This is exactly the semantic gap problem identified in SEARCH_PROVENANCE_TEST.md -- same answer, different vocabulary

## Fix applied
Second search with "content hash dedup insert_belief same content returns existing" found the mechanism immediately. The problem was query formulation, not retrieval capability.

## Implication for product
Memory search works when the query uses the same terms as the stored beliefs. When the user's mental model uses different vocabulary than the codebase, search fails. This is the #1 case for embedding-based semantic search.
