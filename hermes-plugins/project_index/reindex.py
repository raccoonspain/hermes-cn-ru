"""Manual maintenance script: recompute the embeddings index for every
project under a user's workspace.

Not registered as an agent tool (see the project-index design doc) —
this is a rare backfill/index-loss-recovery operation, not something
the model should be able to trigger from chat.

Run with the same interpreter Hermes uses, as a module, from the
directory that CONTAINS project_index/ (so `-m` can resolve the
package and its relative imports):

    cd ~/.hermes/plugins
    ~/.hermes/hermes-agent/venv/bin/python3 -m project_index.reindex --user dem
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="Логин пользователя, например 'dem' или 'rost'")
    args = parser.parse_args()

    try:
        result = core.reindex_all(user=args.user)
    except core.ProjectIndexError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
