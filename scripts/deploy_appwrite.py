"""Deploy the public storefront fully on Appwrite.

    python scripts/deploy_appwrite.py

1. Appwrite Function ``nmb-storefront-api`` (Python): bundles nmb_five,
   contracts/ and the DataContractGate SDK; sets its environment variables
   through the API (credentials never live in the repo); execute = any.
2. A function domain (proxy rule) so the browser can call it directly.
3. Appwrite Site ``nmb-storefront``: nmb_five/static plus a generated
   config.js that points at the function domain.
4. ALLOWED_ORIGINS on the function is set to the site's domain (CORS).

Needs an API key with: functions.read/write, sites.read/write,
rules.read/write (proxy) plus the database / embeddings scopes the demo
already uses. Reads configuration from the environment or .env.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from appwrite.enums.build_runtime import BuildRuntime  # noqa: E402
from appwrite.enums.framework import Framework  # noqa: E402
from appwrite.enums.runtime import Runtime  # noqa: E402
from appwrite.exception import AppwriteException  # noqa: E402
from appwrite.input_file import InputFile  # noqa: E402
from appwrite.services.functions import Functions  # noqa: E402
from appwrite.services.proxy import Proxy  # noqa: E402
from appwrite.services.sites import Sites  # noqa: E402

from nmb_five.connectors.appwrite import appwrite_client, load_dotenv  # noqa: E402

FUNCTION_ID = "nmb-storefront-api"
SITE_ID = "nmb-storefront"
RUNTIME = os.environ.get("NMB_FUNCTION_RUNTIME", "python-3.12")
FUNCTION_VARS = ["APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_API_KEY", "APPWRITE_TABLESDB_ID",
                 "APPWRITE_DOCUMENTSDB_ID", "APPWRITE_VECTORSDB_ID", "APPWRITE_POSTGRES_ID", "APPWRITE_MYSQL_ID",
                 "APPWRITE_SQL_TRANSPORT"]
SECRET_VARS = {"APPWRITE_API_KEY"}


def _d(o):
    return o.model_dump() if hasattr(o, "model_dump") else o


def _tar(src_dir: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(src_dir.rglob("*")):
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            tf.add(p, arcname=str(p.relative_to(src_dir)), recursive=False)
    return buf.getvalue()


def build_function_bundle(out: Path) -> Path:
    import contractgate

    shutil.copytree(ROOT / "functions" / "storefront", out, dirs_exist_ok=True)
    shutil.copytree(ROOT / "nmb_five", out / "nmb_five", ignore=shutil.ignore_patterns("__pycache__", "static"))
    shutil.copytree(ROOT / "contracts", out / "contracts")
    shutil.copytree(Path(contractgate.__file__).parent, out / "contractgate",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return out


def _wait_deployment(get, label, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        d = _d(get())
        st = getattr(d.get("status"), "value", d.get("status"))
        if st == "ready":
            return d
        if st in ("failed", "canceled"):
            raise RuntimeError(f"{label} deployment {st}: {(d.get('buildlogs') or '')[-1500:]}")
        time.sleep(5)
    raise TimeoutError(f"{label} deployment not ready after {timeout}s")


def _set_var(svc, fid, key, value, secret):
    vars_ = _d(svc.list_variables(function_id=fid)).get("variables", [])
    existing = next((v for v in vars_ if v.get("key") == key), None)
    if existing:
        svc.update_variable(function_id=fid, variable_id=existing.get("id") or existing.get("$id"), key=key,
                            value=value, secret=secret)
    else:
        svc.create_variable(function_id=fid, variable_id=key.lower().replace("_", "-")[:36], key=key, value=value, secret=secret)


def deploy() -> None:
    load_dotenv(str(ROOT / ".env"))
    c = appwrite_client()
    fn, sites, proxy = Functions(c), Sites(c), Proxy(c)

    # 1. function
    try:
        fn.get(function_id=FUNCTION_ID)
    except AppwriteException:
        fn.create(function_id=FUNCTION_ID, name="nmb-five storefront API", runtime=Runtime(RUNTIME),
                  execute=["any"], entrypoint="src/main.py", commands="pip install -r requirements.txt",
                  timeout=60, logging=True)
    for k in FUNCTION_VARS:
        if os.environ.get(k):
            _set_var(fn, FUNCTION_ID, k, os.environ[k], k in SECRET_VARS)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = build_function_bundle(Path(tmp) / "fn")
        dep = _d(fn.create_deployment(function_id=FUNCTION_ID, code=InputFile.from_bytes(_tar(bundle), "code.tar.gz"),
                                      activate=True, entrypoint="src/main.py",
                                      commands="pip install -r requirements.txt"))
    _wait_deployment(lambda: fn.get_deployment(function_id=FUNCTION_ID, deployment_id=dep.get("id") or dep["$id"]),
                     "function")

    # 2. function domain
    fn_domain = os.environ.get("NMB_FUNCTION_DOMAIN") or f"nmb-five-api-{os.environ['APPWRITE_PROJECT_ID'][:8]}.appwrite.network"
    try:
        proxy.create_function_rule(domain=fn_domain, function_id=FUNCTION_ID)
    except AppwriteException as e:
        if getattr(e, "code", None) != 409:
            raise
    api_base = f"https://{fn_domain}"

    # 3. site
    try:
        sites.get(site_id=SITE_ID)
    except AppwriteException:
        sites.create(site_id=SITE_ID, name="nmb-five storefront", framework=Framework("other"), build_runtime=BuildRuntime("node-22"),
                     output_directory="./")
    with tempfile.TemporaryDirectory() as tmp:
        site_dir = Path(tmp) / "site"
        shutil.copytree(ROOT / "nmb_five" / "static", site_dir)
        (site_dir / "config.js").write_text(f"window.NMB_API = '{api_base}';\n")
        sdep = _d(sites.create_deployment(site_id=SITE_ID, code=InputFile.from_bytes(_tar(site_dir), "site.tar.gz"),
                                          activate=True, output_directory="./"))
    _wait_deployment(lambda: sites.get_deployment(site_id=SITE_ID, deployment_id=sdep.get("id") or sdep["$id"]),
                     "site")
    site_domain = os.environ.get("NMB_SITE_DOMAIN") or f"nmb-five-{os.environ['APPWRITE_PROJECT_ID'][:8]}.appwrite.network"
    try:
        proxy.create_site_rule(domain=site_domain, site_id=SITE_ID)
    except AppwriteException as e:
        if getattr(e, "code", None) != 409:
            raise

    # 4. CORS: only the site may call the API from a browser
    _set_var(fn, FUNCTION_ID, "ALLOWED_ORIGINS", f"https://{site_domain}", False)
    print(f"site: https://{site_domain}\napi:  {api_base}\n"
          "Note: a variable change applies to new deployments; re-run once if ALLOWED_ORIGINS was just created.")


if __name__ == "__main__":
    deploy()
