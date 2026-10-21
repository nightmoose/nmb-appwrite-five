# Demo video script (2:45 target)

Setup before recording:

- `python -m nmb_five.provision` (idempotent), then call any SQL endpoint once
  so PostgreSQL and MySQL are awake (they hibernate after 15 idle minutes and
  the first call is slow).
- `python -m nmb_five serve --mode appwrite`, open http://127.0.0.1:8000 in a
  1600px-wide window at 100% zoom. Click **Re-run pipeline** once so the page is fresh.
- Second tab: the Appwrite Console on the project's **Databases** page, showing
  `app`, `catalog`, `vectors`, `orders`, `crm`.

| Time | Shot | Narration |
| --- | --- | --- |
| 0:00–0:15 | Title card, then the storefront header (pill reads **LIVE · Appwrite Cloud**). | "Most apps end up with data in several databases, and each store quietly grows its own idea of what a 'customer' or an 'order' is. This is one data contract, enforced across all five Appwrite database types." |
| 0:15–0:35 | Appwrite Console Databases page; pan across the five databases. Cut back to the **five stores** row. | "One Appwrite project: TablesDB for users and carts, DocumentsDB for the schemaless catalog, VectorsDB for embeddings, Managed PostgreSQL for orders and payments, and Managed MySQL for a legacy CRM." |
| 0:35–0:55 | Click `products` under DocumentsDB, then `orders` under PostgreSQL, so the row preview opens. | "These are real rows read back from each store. Products are documents, orders are PostgreSQL rows sent through Appwrite's SQL API." |
| 0:55–1:15 | Zoom on **Every edge is gated**. Hover the red quarantine counts. | "Every time data moves between stores, DataContractGate checks it against a YAML contract. Nine edges. Records that pass get written. Records that fail never reach the target store." |
| 1:15–1:35 | Scroll to **Quarantine**. Point at the MySQL entry (`BEN@EXAMPLE`, segment `Gold`). | "Here's drift. The legacy CRM writes straight to MySQL and skips the app, so an uppercase email and a segment called 'Gold' show up. When we read it back into TablesDB, the contract catches it." |
| 1:35–2:00 | **Live contract check**: click *valid order* → Check → green PASS. Click *drifted CRM row* → Check → red QUARANTINED; a new card flashes at the top of Quarantine. | "It's live. A valid order passes. A drifted CRM row fails on three rules, goes to quarantine, and gets embedded into the contract map with the contracts nearest to it." |
| 2:00–2:25 | **VectorsDB contract map**: the yellow conflict card, then the nearest-contracts table. | "Contracts and failures both live in VectorsDB as embeddings. That turns up conflicts: cart.status and order.status mean similar things but allow different values. It also shows which contracts are related." |
| 2:25–2:40 | Scroll to **Suggested contract for a new feed: refund**. Highlight `order_id` pattern in the YAML. | "A new refund feed arrives. From a few samples, the map finds its nearest contracts and drafts one. It borrows the order_id pattern from the order contract, so the new feed lines up with the old ones from the start." |
| 2:40–2:45 | Semantic search box: type "waterproof jacket for rain" → Trail Rain Shell first. End card with repo URL. | "One contract, five databases, drift caught at every edge. Code is MIT on GitHub." |

Fallback: if the live project is slow, record with `python -m nmb_five serve`
(local stand-ins). The UI and flow are identical; the header pill reads
"local stand-ins" instead.
