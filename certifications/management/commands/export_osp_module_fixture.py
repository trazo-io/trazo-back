"""
Export the guided-OSP module registry + evaluator golden cases for the frontend.

The backend evaluator (`osp_modules/conditions.py`) and its TS twin
(`trazo-app/src/config/osp/conditionEval.ts`) must agree exactly — a drift means the
wizard shows a page the server won't validate, or hides one it requires. This command
freezes the contract: it serializes the registry AND computes, with the PYTHON
evaluator, the visible-question sets and missing-required lists for a battery of
answer fixtures. The frontend test replays the same fixtures through the TS evaluator
and asserts identical output. Change semantics on either side and the other side's
test fails — that is the point.

Run after ANY change to osp_modules content or evaluator semantics:

    poetry run python manage.py export_osp_module_fixture

The fixture is committed alongside the frontend test (same repo pattern as the
padding-detector sync noted in OSPView.tsx).
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from certifications.osp_modules import CONTENT_VERSION, MODULE_REGISTRY, serialize_registry
from certifications.osp_modules.conditions import missing_required, visible_questions

DEFAULT_OUT = (
    Path(__file__).resolve().parents[4] / "trazo-app/src/config/osp/__tests__/fixtures/module-definitions.json"
)

# Answer batteries per module — chosen to exercise every op in CONDITION_OPS and the
# N/A path. Keys are case labels; values are bare answer dicts (the evaluator accepts
# both bare and enveloped shapes).
GOLDEN_ANSWER_CASES = {
    "g3_0_seeds": {
        "unanswered": {},
        "all_none": {
            "seeds_used": ["none"],
            "seedlings_used": ["none"],
            "planting_stock_used": ["none"],
        },
        "non_organic_untreated": {"seeds_used": ["non_organic_untreated"]},
        "organic_treated": {"seeds_used": ["organic_treated"]},
        "non_organic_treated_with_stock": {
            "seeds_used": ["non_organic_treated"],
            "planting_stock_used": ["organic"],
        },
        "stale_hidden_branch": {
            "seeds_used": ["none"],
            "ca_search_before_use": "documented_search",
        },
    },
    "g4_0_rotation_soil": {
        "unanswered": {},
        "annual_only": {"system_type": ["annual"]},
        "perennial_with_other": {
            "system_type": ["perennial"],
            "in_lieu_practices": ["cover_crops", "other"],
        },
        "monitoring_no_testing": {"fertility_monitoring": ["no_testing"]},
        "monitoring_soil_tests": {"fertility_monitoring": ["soil_tests"]},
    },
    "g8_0_record_keeping": {
        "unanswered": {},
        "own_lot_system": {"lot_numbering": "own_system"},
        "trazo_lots": {"lot_numbering": "trazo_lots"},
    },
}


class Command(BaseCommand):
    help = "Export module registry + evaluator golden cases to the frontend fixture."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(DEFAULT_OUT), help="Fixture output path")

    def handle(self, *args, **options):
        modules_by_key = {m.key: m for m in MODULE_REGISTRY}
        cases = []
        for module_key, batteries in GOLDEN_ANSWER_CASES.items():
            module = modules_by_key.get(module_key)
            if module is None:
                self.stderr.write(f"skipping unknown module '{module_key}'")
                continue
            for label, answers in batteries.items():
                visible = [q.key for _p, q in visible_questions(module, answers)]
                cases.append(
                    {
                        "module": module_key,
                        "label": label,
                        "answers": answers,
                        "visible_questions": visible,
                        "missing_required": missing_required(module, answers),
                        "missing_required_na": missing_required(module, answers, not_applicable=True),
                    }
                )

        payload = {
            "content_version": CONTENT_VERSION,
            "registry": serialize_registry(),
            "golden_cases": cases,
        }
        out = Path(options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(cases)} golden cases -> {out}"))
