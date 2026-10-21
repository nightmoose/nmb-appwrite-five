"""Demo data for the storefront. A few records are deliberately bad so
the gates have something to stop."""

PRODUCTS = [
    {"sku": "SKU-0001", "title": "Trail Rain Shell", "description": "Packable waterproof jacket for wet trail days.",
     "price_cents": 12900, "category": "outdoor", "tags": ["rain", "jacket"]},
    {"sku": "SKU-0002", "title": "Camp Mug", "description": "Enamel steel mug that survives the campfire.",
     "price_cents": 1800, "category": "outdoor", "tags": ["camp"]},
    {"sku": "SKU-0003", "title": "Linen Throw", "description": "Soft washed linen blanket for the couch.",
     "price_cents": 6400, "category": "home"},
    {"sku": "SKU-0004", "title": "Chef Knife", "description": "Eight inch carbon steel kitchen knife.",
     "price_cents": 8900, "category": "kitchen", "tags": ["knife", "steel"]},
    {"sku": "SKU-0005", "title": "Field Guide to Birds", "description": "Pocket guide to common North American birds.",
     "price_cents": 2200, "category": "books"},
    {"sku": "SKU-0006", "title": "Merino Tee", "description": "Lightweight wool shirt that does not hold odor.",
     "price_cents": 5500, "category": "apparel"},
    # bad: price is a string, category not in enum
    {"sku": "SKU-0099", "title": "Mystery Box", "description": "Who knows what is inside this box.",
     "price_cents": "free", "category": "misc"},
]

USERS = [
    {"user_id": "u_ana", "email": "ana@example.com", "full_name": "Ana Ruiz", "tier": "member"},
    {"user_id": "u_ben", "email": "ben@example.com", "full_name": "Ben Ortiz", "tier": "vip"},
    {"user_id": "u_cam", "email": "cam@example.com", "full_name": "Cam Lee", "tier": "guest"},
    # bad: email has no domain
    {"user_id": "u_dex", "email": "dex-at-example", "full_name": "Dex Kim", "tier": "member"},
]

CARTS = [
    {"cart_id": "c_001", "user_id": "u_ana", "sku": "SKU-0001", "quantity": 1, "status": "open"},
    {"cart_id": "c_002", "user_id": "u_ana", "sku": "SKU-0002", "quantity": 2, "status": "open"},
    {"cart_id": "c_003", "user_id": "u_ben", "sku": "SKU-0004", "quantity": 1, "status": "open"},
    {"cart_id": "c_004", "user_id": "u_cam", "sku": "SKU-0005", "quantity": 3, "status": "open"},
    # bad: quantity 0
    {"cart_id": "c_005", "user_id": "u_cam", "sku": "SKU-0003", "quantity": 0, "status": "open"},
]

SETTINGS = [
    {"key": "currency", "value": "USD"},
    {"key": "store_name", "value": "Five Stores Outfitters"},
]

# What the legacy CRM app writes on its own, outside our pipeline.
CRM_DRIFT = [
    {"cust_id": "u_ben", "cust_email": "BEN@EXAMPLE", "customer_name": "Ben Ortiz", "lifetime_cents": 8900,
     "segment": "Gold"},
    {"cust_id": "u_eve", "cust_email": "eve@example.org", "customer_name": "Eve Park", "lifetime_cents": 0,
     "segment": "NEW"},
]

# A brand new feed nobody wrote a contract for yet.
NEW_FEED_SAMPLE = [
    {"refund_id": "r_100", "order_id": "o_c_001", "amount_cents": 12900, "currency": "USD", "reason": "damaged"},
    {"refund_id": "r_101", "order_id": "o_c_003", "amount_cents": 8900, "currency": "USD", "reason": "late"},
    {"refund_id": "r_102", "order_id": "o_c_004", "amount_cents": 2200, "currency": "EUR", "reason": "damaged"},
]
