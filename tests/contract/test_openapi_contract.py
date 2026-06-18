import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "docs" / "openapi.yaml"

REQUIRED_PATHS = {
    "/v1/reply-decisions",
    "/v1/reply-decisions/{decision_id}/contexts/products",
    "/v1/reply-decisions/{decision_id}/contexts/orders",
    "/v1/reply-decisions/{decision_id}/contexts/logistics",
    "/v1/reply-decisions/{decision_id}/contexts/rules",
    "/v1/reply-decisions/{decision_id}/actions/results",
    "/v1/message-traces/{decision_id}",
    "/v1/feedback/human-replies",
    "/v1/admin/auth/login",
    "/v1/admin/auth/logout",
    "/v1/admin/auth/me",
    "/v1/admin/audit-logs",
    "/v1/product-content/products",
    "/v1/product-content/assets",
    "/v1/product-content/price-snapshots",
    "/v1/system-admin/auth/login",
    "/v1/system-admin/auth/logout",
    "/v1/system-admin/auth/me",
    "/v1/system-admin/message-traces",
    "/v1/system-admin/audit-logs",
    "/v1/system-admin/health",
}


def load_openapi():
    result = subprocess.run(
        [
            "ruby",
            "-rjson",
            "-ryaml",
            "-e",
            "puts JSON.generate(YAML.load_file(ARGV.fetch(0)))",
            str(OPENAPI_PATH),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def resolve_pointer(document, ref):
    if not ref.startswith("#/"):
        raise AssertionError(f"non-local $ref is not allowed: {ref}")

    current = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise AssertionError(f"missing $ref target: {ref}")
    return current


class OpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_openapi()

    def test_openapi_yaml_is_parseable(self):
        self.assertEqual(self.document["openapi"], "3.1.0")
        self.assertIsInstance(self.document["paths"], dict)
        self.assertIsInstance(self.document["components"], dict)

    def test_local_refs_are_all_resolvable(self):
        refs = [node["$ref"] for node in walk(self.document) if "$ref" in node]
        self.assertGreater(refs, [])
        missing = []
        for ref in refs:
            try:
                resolve_pointer(self.document, ref)
            except AssertionError as exc:
                missing.append(str(exc))

        self.assertEqual(missing, [], "\n".join(missing))

    def test_operation_ids_are_unique(self):
        operation_ids = []
        for path_item in self.document["paths"].values():
            for method, operation in path_item.items():
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    operation_ids.append(operation.get("operationId"))

        missing = [operation for operation in operation_ids if not operation]
        duplicates = sorted(
            operation_id
            for operation_id in set(operation_ids)
            if operation_ids.count(operation_id) > 1
        )
        self.assertEqual(missing, [])
        self.assertEqual(duplicates, [])

    def test_first_version_required_paths_exist(self):
        paths = self.document["paths"]
        failures = []
        for path in sorted(REQUIRED_PATHS):
            if path not in paths:
                failures.append(f"missing path {path}")
                continue
            operations = [
                (method, operation)
                for method, operation in paths[path].items()
                if method.lower() in {"get", "post", "put", "patch", "delete"}
            ]
            if not operations:
                failures.append(f"missing operation {path}")
                continue
            for method, operation in operations:
                if not operation.get("operationId"):
                    failures.append(f"missing operationId {method.upper()} {path}")
                if "security" not in operation:
                    failures.append(f"missing security {method.upper()} {path}")
                if "responses" not in operation or not operation["responses"]:
                    failures.append(f"missing responses {method.upper()} {path}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_product_asset_declares_object_storage_unavailable_response(self):
        responses = self.document["paths"]["/v1/product-content/assets"]["post"]["responses"]

        self.assertEqual(
            responses["503"]["$ref"],
            "#/components/responses/ObjectStorageUnavailable",
        )


if __name__ == "__main__":
    unittest.main()
