# Appwrite database notes (docs read 2026-10-21; live run 2026-10-21)

Facts below were read from Appwrite's own docs on 2026-10-21. Each line
cites its source. Anything not confirmed is marked **UNVERIFIED**.
Plan requirements are summarised neutrally below.

## Shared

| Fact | Source |
| --- | --- |
| Five types: TablesDB, DocumentsDB (Beta), VectorsDB (Beta), PostgreSQL (Beta), MySQL (Beta). | https://appwrite.io/products/databases |
| Two families. "Appwrite databases" (TablesDB, DocumentsDB, VectorsDB) are used through the Appwrite SDKs with row/document permissions. "Native databases" (PostgreSQL, MySQL) are raw engines reached with standard drivers, with no Appwrite layer in the data path. | https://appwrite.io/blog/post/native-databases-all-appwrite-cloud-regions |
| Cloud API endpoint format: `https://<REGION>.cloud.appwrite.io/v1`. Server SDKs need an API key (`setKey`). | https://appwrite.io/docs/products/databases/documentsdb/documents |
| Regions: fra, nyc, sfo, sgp, syd, tor. All of them can host native and dedicated databases (as of 2026-09-24). | blog post above |
| Native database hostnames look like `db-<...>.appwrite.center`. Credentials (host, `admin` user, password, DSN) are under **Credentials** on the database. TLS is on by default. IP allowlists are available. | blog post above |
| Python SDK: `pip install appwrite`. Version 26.0.0 was installed and checked on 2026-10-21. It ships `appwrite.services.tables_db.TablesDB`, `documents_db.DocumentsDB`, `vectors_db.VectorsDB`, `embeddings.Embeddings`, `postgresql`, and `mysql` (the last two manage the databases themselves, not the data). Node: `node-appwrite`. Web: `appwrite`. | local `pip show appwrite`; https://appwrite.io/docs/products/databases/documentsdb/documents |

## Plan requirements

| Fact | Source |
| --- | --- |
| **Free plan: 1 database per project.** Pro: unlimited databases. Five stores in one project therefore require the Pro plan. | https://appwrite.io/docs/products/databases |
| Managed PostgreSQL and Managed MySQL require the Pro plan (or higher) with a payment method on the organization. Pro can pick the four smallest compute specs; Scale can pick all of them. | https://appwrite.io/docs/products/databases/postgresql (plan requirements) |
| Native and dedicated databases require the Pro plan (or higher); the entry tier is included on Pro. | blog post above (FAQ) |
| Appwrite lists **TablesDB (default)** as *Serverless* and **DocumentsDB, VectorsDB, PostgreSQL, MySQL, or upgraded TablesDB** as *Dedicated*, so DocumentsDB and VectorsDB each run on a dedicated compute tier. | https://appwrite.io/docs/products/databases |
| **CONFLICT / UNVERIFIED:** the same blog post also says "Every project gets these [TablesDB, DocumentsDB, VectorsDB] on a shared pool with no provisioning step. Pass a `specification` … and it moves to dedicated compute." The DocumentsDB and VectorsDB quick-starts both say "Select your preferred tier". Whether DocumentsDB or VectorsDB can run serverless (no tier) on Pro, or on Free, must be checked in the Console. | blog post above; https://appwrite.io/docs/products/databases/vectorsdb/quick-start ; https://appwrite.io/docs/products/databases/documentsdb/quick-start |
| Hackathon FAQ: Managed PostgreSQL and Managed MySQL run on dedicated infrastructure and require the Pro plan. | https://hackathon.appwrite.io/ |
| Embeddings have a monthly token allowance per model on Free and Pro. | https://appwrite.io/docs/products/ai |

## TablesDB

- Relational tables, columns, rows, indexes. Python: `TablesDB(client).upsert_row(database_id, table_id, row_id, data)` and `list_rows(database_id, table_id, queries)`. Checked against SDK 26.0.0 signatures.
- Docs: https://appwrite.io/docs/products/databases/tablesdb

## DocumentsDB (Beta)

- Schemaless JSON documents. Documents in one collection can have different fields. Supports queries, transactions, bulk operations, and document-level permissions (`documentSecurity`).
- REST: `POST /v1/documentsdb/{databaseId}/collections/{collectionId}/documents`, `GET …/documents`, `GET …/documents/{documentId}`, `PATCH …/documents/{documentId}`, transactions under `/v1/documentsdb/transactions`. Scope: `documentsdb.documents.write`. Client rate limit: 120 req/min per IP (server API keys bypass it). Source: https://appwrite.io/docs/references/cloud/client-rest/documentsDB
- Python: `from appwrite.services.documents_db import DocumentsDB`, then `create_document`, `get_document`, `upsert_document`, `list_documents`. Source: https://appwrite.io/docs/products/databases/documentsdb/documents
- Console: Databases → Create database → DocumentsDB → pick a tier. Source: https://appwrite.io/docs/products/databases/documentsdb/quick-start

## VectorsDB (Beta)

- Fixed-shape collections: `dimension` is set at creation. Each document has `embeddings` (vector) plus an optional free-form `metadata` object. There are no custom columns. Source: https://appwrite.io/docs/products/databases/vectorsdb/quick-start
- Embeddings come from the separate **Embeddings** service: `createTextEmbeddings({texts, model?})`. The default model is `nomic-embed-text`, with 768 dimensions. The API key needs the `embeddings.write` scope. A "Custom dimension" option is available for your own model. Source: https://appwrite.io/docs/products/databases/vectorsdb/embeddings
- Index: `createIndex` with `VectorsDBIndexType.HnswCosine | HnswDot | HnswEuclidean` on `embeddings`. Query: `Query.vectorCosine / vectorDot / vectorEuclidean('embeddings', vector)` passed to `listDocuments`. The query must match the index type. Results come back sorted by `$distance`, closest first. Small collections work without an index. Source: https://appwrite.io/docs/products/databases/vectorsdb/vector-search
- `Query.select(["metadata"])` leaves the vector out of the response. Source: https://appwrite.io/docs/products/databases/vectorsdb/queries
- **UNVERIFIED:** filtering on `metadata.*` keys in the same `listDocuments` call as a vector query. This repo filters client-side after the vector query.

## Managed PostgreSQL (Beta)

- A real PostgreSQL engine with its own hostname and credentials. Connect with `psql`, Prisma, Drizzle, or any driver. Extensions include pgvector, PostGIS, and pg_trgm. Backups, PITR, HA replicas, branches, and a pooler are included. Source: https://appwrite.io/docs/products/databases/postgresql
- **UNVERIFIED:** port number and exact DSN query parameters. Copy them from the Console's Credentials dialog.

## Managed MySQL (Beta)

- MySQL 8.4. Connect with the `mysql` client or any driver. A ProxySQL-based pooler is included. Binlog archiving provides PITR. Sources: https://appwrite.io/docs/products/databases/mysql ; blog post above.
- **UNVERIFIED:** port and TLS CA requirements. Copy them from the Console.

## Verified live (2026-10-21, nyc region, Pro project, `appwrite` Python SDK 26.0.0)

All five stores were exercised by `python -m nmb_five demo --mode appwrite` and by `NMB_LIVE=1 pytest`.

- **Typed models nest user fields under `data`.** `list_rows` / `list_documents` return models whose `model_dump()` has system keys (`id`, `sequence`, `createdat`, `permissions`, …) and the user fields in `data`. The vector distance comes back next to them.
- **TablesDB:** `create_table`, `create_varchar_column`, `create_integer_column`, and a `key` index all worked. Columns are created asynchronously; `list_columns` reports `status` as an enum, and you have to wait for `available` before indexing. The column key `key` is accepted. `upsert_row` and `list_rows` with `Query.equal` work.
- **DocumentsDB:** `create_collection` worked with no attributes (schemaless). `upsert_document` (custom IDs like `SKU-0001`) and `list_documents` work.
- **VectorsDB:** `create_collection(dimension=768)` and `create_index(type=hnsw_cosine, attributes=["embeddings"])` worked. **A 768-float vector query sent through `list_documents` (GET) fails with `URI Too Long`.** Use `create_query` (`POST …/documents/query`), which takes the same queries in the request body. Ranking by `Query.vector_cosine` worked, closest first.
- **Embeddings:** `Embeddings.create_text_embeddings(texts=[...])` returned 768-dimension vectors (default `nomic-embed-text`).
- **Native credentials are exposed by the API.** `Postgresql.get(id)` and `Mysql.get(id)` return `hostname`, `connectionport`, `connectionuser`, `connectionpassword` and `connectionstring`. `update_credentials(id)` queues a rotation. Treat those GET responses as secrets.
- **Ports:** the API reports PostgreSQL on 5432 and MySQL on 3306 (`?sslmode=require` / `?ssl=true`). From our build box, every non-443 port to `*.appwrite.center` timed out (5432, 6432, 3306, 6033), so direct driver connections were **not** verified. That is a property of our network, not proven to be an Appwrite limit.
- **SQL API over HTTPS works for both engines:** `Postgresql.create_execution(database_id, sql, bindings)` (placeholders `$1…`) and `Mysql.create_execution` (placeholders `?`). Each call runs exactly one statement. `CREATE TABLE IF NOT EXISTS`, `INSERT … ON CONFLICT` / `ON DUPLICATE KEY UPDATE`, `SELECT`, and `information_schema` reads worked. Engines reported PostgreSQL 18.4 and MySQL 8.4.10. This is the repo's default SQL transport (`APPWRITE_SQL_TRANSPORT=api`).
- **Idle hibernation:** each native database reports `idletimeoutminutes: 15`, and wakes on access.
