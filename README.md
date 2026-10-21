# nmb-appwrite-five

> Draft README. This is the first working version.

A small demo storefront that keeps real app data in **all five Appwrite
database types**. [DataContractGate](https://github.com/nightmoose/contractgate)
enforces a data contract at every edge where data moves between stores.

| Store | What lives there | Contract(s) |
| --- | --- | --- |
| **DocumentsDB** | product catalog (schemaless docs) | `product` |
| **TablesDB** | users, carts, settings | `user`, `cart` |
| **VectorsDB** | product embeddings + the *contract relationship map* | `product_embedding`, `contract_map_entry` |
| **Managed PostgreSQL** | orders, payments | `order`, `payment` |
| **Managed MySQL** | a legacy CRM that drifts | `crm_customer` |

## The flow

```
seed ──gate──▶ DocumentsDB.products ──gate──▶ VectorsDB.product_vectors   (semantic search)
seed ──gate──▶ TablesDB.users / carts
TablesDB.carts + DocumentsDB prices ──gate──▶ PostgreSQL.orders ──gate──▶ PostgreSQL.payments
TablesDB.users + PostgreSQL totals ──gate──▶ MySQL.crm_customers
   (legacy CRM app writes bad rows directly into MySQL: drift)
MySQL.crm_customers ──gate(read)──gate──▶ TablesDB.users
every failure ──▶ quarantine ──embed──▶ VectorsDB.contract_map
```

Passing records are written to the target store. Failing records never
land there. They go to quarantine, and both the failures and the
contracts are embedded into VectorsDB. That **contract relationship map**
can:

- find contracts similar to a given one (`order` → `payment`, `cart`),
- flag **conflicts**: the same concept with different rules (e.g. `cart.status` vs `order.status` enums),
- explain a quarantined record by its nearest contracts, and
- **suggest a contract for a new feed** from a few sample records. It borrows rules from the nearest contracts, e.g. a `refund` feed inherits the `order_id` pattern from `order`.

## Run it locally (no Appwrite account needed)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m nmb_five demo     # end-to-end demo with local stand-ins
pytest -q
```

Local mode uses in-memory stand-ins for TablesDB, DocumentsDB, and
VectorsDB, sqlite for the two SQL engines, and a deterministic hashed
embedder.

## Run it on Appwrite Cloud

0. `pip install -e ".[appwrite]"`
1. Create one project with a TablesDB, a DocumentsDB, a VectorsDB, a PostgreSQL and a MySQL database (see `docs/appwrite-notes.md` for plan requirements).
2. Copy `.env.example` to `.env` and fill it in. Native PostgreSQL and MySQL are reached through Appwrite's SQL API over HTTPS by default (`APPWRITE_SQL_TRANSPORT=api`). Set `driver` to use the DSN / host instead.
3. `python -m nmb_five.provision` creates the TablesDB tables `users`, `carts`, `settings`, the DocumentsDB collection `products`, and the VectorsDB collections `product_vectors` and `contract_map` (768 dimensions, `hnsw_cosine` index on `embeddings`). It is idempotent.
4. `python -m nmb_five demo --mode appwrite`
5. `NMB_LIVE=1 pytest -q` also runs the live smoke test against all five stores.

The Appwrite connectors (`nmb_five/connectors/appwrite.py`) have run end to
end against a live Appwrite Cloud project (nyc). See the "Verified live"
section of `docs/appwrite-notes.md`.

## Layout

```
contracts/                DataContractGate YAML contracts
nmb_five/gate.py          DataContractGate wrapper (pass / quarantine)
nmb_five/connectors/      Connector interface, local stand-ins, Appwrite connectors
nmb_five/sync.py          sync jobs between the five stores
nmb_five/contract_map.py  VectorsDB contract relationship map
nmb_five/seed.py          demo data (with deliberate bad rows)
tests/                    pytest suite
docs/appwrite-notes.md    verified Appwrite facts with sources
```

## Tech stack

Python 3.10+, [`contractgate`](https://github.com/nightmoose/contractgate)
(DataContractGate Python SDK, MIT), `appwrite` Python SDK, `psycopg`,
`PyMySQL`, `PyYAML`, `pytest`.

## License

MIT
