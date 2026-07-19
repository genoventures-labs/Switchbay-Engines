# Neo4j Navigator Engine

Neo4j Navigator uses a knowledge graph as a **RAG routing layer**, not as permission to load the whole graph into model context.

Recommended flow:

1. Call `graph_overview` once to learn labels, relationship types, properties, and available indexes.
2. Use `search_nodes` or `fulltext_search` to locate a small set of starting concepts.
3. Use `explore_branches`, `node_neighborhood`, or `find_paths` to understand the relevant topology.
4. Use `route_sources` to extract concrete retrieval pointers.
5. Pass `path`, `source`, `chunk_id`, `document_id`, URL, collection, or index values to RAG Navigator, File Helper, Web Ingest, or the appropriate source engine.

All engine queries are fixed and read-only. There is no arbitrary-Cypher tool. Traversals and result counts are bounded. Configure a Neo4j account with read-only database privileges anyway; application-side controls are not a substitute for database authorization.

The engine uses Neo4j's HTTP Query API v2 with Python's standard library. It does not require the Neo4j Python driver, APOC, Graph Data Science, embeddings, or a model API.

Environment:

- `NEO4J_HTTP_URL` — HTTP(S) origin, default `http://127.0.0.1:7474`.
- `NEO4J_DATABASE` — default `neo4j`.
- `NEO4J_USERNAME` — default `neo4j`.
- `NEO4J_PASSWORD` — required for basic auth.
- `NEO4J_AUTH_MODE` — `basic` or `none`; default `basic`.
- `NEO4J_TIMEOUT` — request timeout seconds; default `15`.

Neo4j Community Edition can be self-hosted without a license fee. Neo4j Aura offers free and paid hosted plans. Product/signup: https://neo4j.com/product/auradb/ — Query API documentation: https://neo4j.com/docs/query-api/current/
