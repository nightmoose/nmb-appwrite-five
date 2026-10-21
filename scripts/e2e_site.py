"""Headless end-to-end check of the public site (pip install playwright; uses system Chrome).

Runs 8 live checks at the end, so it trips the rate limit on purpose."""
import json, sys
from playwright.sync_api import sync_playwright
SITE = "https://nmb-five-6ad8c48c.appwrite.network"
API = "https://nmb-five-api-6ad8c48c.appwrite.network"
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1600, "height": 1000})
    errs = []
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(SITE, timeout=120000)
    pg.wait_for_function("document.querySelectorAll('#stores .store').length==5", timeout=120000)
    out["mode"] = pg.inner_text("#mode")
    out["store_counts"] = pg.eval_on_selector_all("#stores .ent", "e=>e.map(x=>x.innerText.replace('\\n',' '))")
    out["edges_rows"] = pg.eval_on_selector_all("#edges tr", "e=>e.length-1")
    out["quarantine_before"] = pg.eval_on_selector_all("#quar .q", "e=>e.length")
    out["conflict"] = pg.inner_text("#conf")[:90]
    out["similar_rows"] = pg.eval_on_selector_all("#sim tr", "e=>e.length-1")
    out["suggest_has_order_id"] = "order_id" in pg.inner_text("#yaml")
    pg.click("#stores .ent >> nth=5"); out["peek"] = pg.inner_text("#peekt")
    pg.wait_for_function("document.querySelectorAll('#sres tr').length>0", timeout=60000)
    pg.fill("#sq", "kitchen knife"); pg.click("button[onclick=\"search()\"]")
    pg.wait_for_function("document.querySelector('#sres').innerText.includes('Knife')", timeout=60000)
    out["search_top"] = pg.inner_text("#sres tr >> nth=0")
    pg.click("text=drifted CRM row"); pg.click("text=Check with DataContractGate")
    pg.wait_for_function("document.querySelector('#verdict').innerText.length>0", timeout=60000)
    out["verdict"] = pg.inner_text("#verdict").split("\n")[0]
    pg.wait_for_timeout(4000)
    out["quarantine_after"] = pg.eval_on_selector_all("#quar .q", "e=>e.length")
    out["top_quarantine"] = pg.inner_text("#quar .q >> nth=0").split("\n")[0]
    pg.evaluate("window.scrollTo(0,0)")
    pg.screenshot(path="nmb-five-site.png", full_page=True)
    codes = pg.evaluate("""async (api)=>{const c=[];for(let i=0;i<8;i++){const r=await fetch(api+'/api/check',{method:'POST',
      body:JSON.stringify({contract:'order',record:{order_id:'o_c_rl'+i,user_id:'u_ana',sku:'SKU-0001',quantity:1,total_cents:12900,status:'paid'}})});c.push(r.status)}return c}""", API)
    out["rate_limit_codes"] = codes
    out["console_errors"] = errs
    b.close()
print(json.dumps(out, indent=1))
