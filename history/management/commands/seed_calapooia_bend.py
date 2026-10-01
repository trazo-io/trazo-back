"""Rebuild Calapooia Bend Farm — the depth demo — from an exact fixture.

Why this exists
---------------
Calapooia Bend is the deepest dataset Trazo has: 6 parcels over 86.9 acres, 12 seasons across
two crop years, 512 events, closed seasons AND open ones. It is the farm the certifier-packet
work was validated against (dossier flags 29 -> 19), and the only one whose records were
produced by working the product the way a grower does rather than by inventing rows.

It existed in exactly one place: a developer's local database. 465 of its 512 events came from
an ad-hoc shell script that was never committed, and the remaining 47 were typed into the UI
during the rehearsal. Nothing could rebuild it, so a schema change would have quietly destroyed
the only copy — and it could not be put in front of anyone, because production had never seen it.

Why a JSON fixture and not inline Python
----------------------------------------
`ProductionEvent` has 97 columns, `ChemicalEvent` 82, `SoilManagementEvent` 80. 512 rows across
those is roughly fifteen thousand values. Written as Python literals that is a ten-thousand-line
module nobody can review, and every hand-copied value is a chance to invent data that the
rehearsal never produced. The fixture is machine-extracted from the rows themselves.

The extraction records ONLY fields whose value differs from the model's own default. That is
what keeps a 97-column model from becoming a 97-key dict of mostly-None, and it is why stale
columns stay unwritten: a field nobody filled is absent here rather than pinned to a default the
farmer never chose. `extra_data` is carried verbatim — it is heavily used on this farm (all 80
chemical applications, all 15 weather notes, 104 of 227 production events).

Why not dumpdata / loaddata
---------------------------
`loaddata` pins primary keys, which collide in a database that already has rows; it cannot remap
the foreign keys that must point at whatever CropType / Product / NationalListSubstance the
target database happens to have; and it carries no honesty constraints. This command does all
three, and fails loudly when a referenced natural key is missing rather than seeding a farm with
holes in it.

Honesty constraints
-------------------
The rehearsal data names REAL organisations: Oregon Tilth Certified Organic, a USDA-accredited
certifying agent, plus two real Oregon handlers. `seed_showcase_walnut_farm` refuses to do this
for a reason it states plainly — "no real accredited agent is named as certifying a farm that
does not exist" — and the risk is sharper here, because Oregon Tilth is on the certifier
outreach ladder and would be shown this packet.

So the names are replaced with invented ones by default, everywhere they appear including inside
descriptions and observations (Oregon Tilth alone occurs 31 times, one handler 57). `--real-names`
restores the ground truth for local work; it should not be used for anything anyone else sees.

The establishment is created with `is_demo=True`, so every packet, CSV, OSP module, workbook and
PUR export it produces is stamped a specimen (`common/specimen.py`).
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User

FIXTURE = Path(__file__).with_name("_calapooia_bend_data.json")

EVENT_MODELS = [
    "ChemicalEvent",
    "ProductionEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "GeneralEvent",
    "BusinessEvent",
    "WeatherEvent",
]

#: Real organisation -> invented stand-in. Applied to EVERY string in the fixture, longest key
#: first so "Oregon Tilth Certified Organic (OTCO)" is consumed before the bare "Oregon Tilth".
#: Bare acronyms are matched on word boundaries only, or "OGC" would corrupt any word containing
#: it. Regional plausibility is kept on purpose: a Willamette Valley grower shipping to a
#: "Marion Bend Fruit Co." still reads like Oregon, which is the point of a demo.
FICTIONAL_NAMES: dict[str, str] = {
    "Oregon Tilth Certified Organic (OTCO)": "Cascadia Organic Certifiers (COC)",
    "Oregon Tilth Certified Organic": "Cascadia Organic Certifiers",
    "Oregon Tilth": "Cascadia Organic Certifiers",
    "Real Organic Project": "Living Soil Standard",
    "Organically Grown Company (OGC) — Portland DC": "Cascade Organic Distributors — Portland DC",
    "Organically Grown Company (OGC)": "Cascade Organic Distributors",
    "Organically Grown Company": "Cascade Organic Distributors",
    "Willamette Valley Fruit Co.": "Marion Bend Fruit Co.",
    "Willamette Valley Fruit": "Marion Bend Fruit",
}
#: Acronyms replaced only as whole words.
FICTIONAL_ACRONYMS: dict[str, str] = {"OTCO": "COC", "OGC": "COD"}


def _decode(value):
    """Undo the fixture's type markers. Left as data in JSON so the file stays diffable."""
    if isinstance(value, dict):
        if "__dec__" in value:
            return Decimal(value["__dec__"])
        if "__dt__" in value:
            return parse_datetime(value["__dt__"])
        if "__d__" in value:
            return parse_date(value["__d__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _substitute(value, enabled: bool):
    """Replace real organisation names throughout the fixture, recursively.

    Runs over the WHOLE structure rather than the certifier and facility name fields, because the
    names also appear inside free text the operator wrote — descriptions, observations, the OSP
    narrative. Marking only the structured fields would leave a packet whose header says one thing
    and whose body still names the real agent.
    """
    if not enabled:
        return value
    if isinstance(value, str):
        out = value
        for real, fake in FICTIONAL_NAMES.items():
            out = out.replace(real, fake)
        for real, fake in FICTIONAL_ACRONYMS.items():
            out = re.sub(rf"\b{re.escape(real)}\b", fake, out)
        return out
    if isinstance(value, dict):
        return {k: _substitute(v, enabled) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, enabled) for v in value]
    return value


class Command(BaseCommand):
    help = "Rebuild the Calapooia Bend demo farm from its exact fixture."

    def add_arguments(self, parser):
        parser.add_argument(
            "--owner-email",
            required=True,
            help="Existing user who will own the company and be credited as operator.",
        )
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Delete an existing Calapooia Bend establishment first. Without this the "
            "command refuses rather than creating a second copy.",
        )
        parser.add_argument(
            "--real-names",
            action="store_true",
            help="Keep the real certifier and handler names from the rehearsal. Local use only "
            "— it names a real accredited agent as certifying a farm that does not exist.",
        )

    # ------------------------------------------------------------------
    @transaction.atomic
    def handle(self, *args, **options):
        from subscriptions.models import Subscription

        if not FIXTURE.exists():
            raise CommandError(f"Fixture missing: {FIXTURE}")

        raw = json.loads(FIXTURE.read_text())
        data = _substitute(raw, enabled=not options["real_names"])

        owner = User.objects.filter(email=options["owner_email"]).first()
        if owner is None:
            raise CommandError(f"No user with email {options['owner_email']!r}.")

        est_name = data["establishment"]["name"]
        existing = Establishment.objects.filter(name=est_name)

        # --rebuild DELETES a farm and everything under it, and this command runs against
        # production. Matching on name alone would let it destroy a real operation that happened
        # to share the name — an unrecoverable outcome from a demo tool. Everything this seeder
        # creates is `is_demo=True`, so refusing to touch anything else costs nothing and makes
        # "it deleted a customer's records" impossible rather than unlikely.
        real = existing.filter(is_demo=False)
        if real.exists():
            raise CommandError(
                f"Refusing to touch {est_name!r}: establishment(s) "
                f"{', '.join(str(e.pk) for e in real)} exist with is_demo=False. This command "
                "only ever creates and replaces demo farms. Rename the real operation, or seed "
                "under a different name."
            )

        existing = existing.filter(is_demo=True)
        if existing.exists():
            if not options["rebuild"]:
                raise CommandError(
                    f"{est_name!r} already exists (id "
                    f"{', '.join(str(e.pk) for e in existing)}). Pass --rebuild to replace it."
                )
            for est in existing:
                self.stdout.write(f"  removing existing demo establishment {est.pk}")
                self._teardown(est)
                est.delete()

        company, membership = self._company(data, owner)
        est = self._establishment(data, company)
        facilities = self._facilities(data, est)
        certs = self._certifications(data, est)
        osps = self._osp_graph(data, est, owner, certs)
        parcels = self._parcels(data, est)
        seasons = self._seasons(data, est, parcels, facilities, owner)
        n_events, event_map = self._events(data, seasons, owner)
        self._related_records(data, seasons, parcels, event_map, owner)
        self._record_type_confirmations(data, osps, owner)
        self._renewal(data, osps, owner)
        self._specimen_documents(data, est, owner)

        self.stdout.write(
            self.style.SUCCESS(
                f"Calapooia Bend rebuilt: establishment {est.pk}, {len(parcels)} parcels, "
                f"{len(seasons)} productions, {n_events} events, "
                f"{est.organic_system_plans.count()} OSP versions, "
                f"is_demo={est.is_demo}"
            )
        )
        # This command is run over a production console, where the next question is always
        # "will I actually see it?". Answer it here rather than making someone log in to find out.
        subscription = Subscription.objects.filter(company=company).first()
        self.stdout.write(f"  company      : {company.name} (#{company.pk})")
        self.stdout.write(f"  access       : {owner.email} as {membership.get_role_display()}")
        self.stdout.write(
            f"  plan         : {subscription.plan.slug if subscription else 'NONE — farm will be read-only'}"
        )
        if options["real_names"]:
            self.stdout.write(
                self.style.WARNING("  --real-names: this farm names a REAL accredited certifier. Do not expose it.")
            )

    # ------------------------------------------------------------------
    #: Fixture key prefixes: "_" identity, "#" a foreign key inside this farm's own graph,
    #: "@" a foreign key resolved by natural key against the target database, "~" a
    #: many-to-many set listed by natural key. Only unprefixed keys are model columns.
    #:
    #: Fixture keys that describe STRUCTURE rather than a column. `events` nests the child
    #: rows; `post_harvest_facilities` is the § 205.272 many-to-many, which Django refuses to
    #: accept in `create()` and which is wired separately once the season exists.
    STRUCTURAL_KEYS = frozenset({"events", "post_harvest_facilities"})

    @staticmethod
    def _teardown(est):
        """Remove what PROTECT would otherwise block, in dependency order.

        This is a DEMO RESET, not product behaviour: `--rebuild` throws the whole farm away,
        signed and frozen annual-update revisions included, and seeds it again. Nothing in the
        product deletes a filed revision (the viewset answers 423), and nothing here should be
        read as evidence that a filing "survives" a rebuild; the seed simply re-creates it.

        `OSPAnnualUpdate.prior_osp` is on_delete=PROTECT, so an establishment that has ever
        filed a § 205.406 annual update cannot be deleted until the update rows go first — the
        same order `create_organic_pilot_farm` already works in. Worth knowing outside this
        command: a farm with an OSP is not deletable by a plain `.delete()`, which is a
        deliberate records-retention posture rather than an oversight.
        """
        OSP = apps.get_model("certifications", "OrganicSystemPlan")
        AU = apps.get_model("certifications", "OSPAnnualUpdate")
        osp_ids = list(OSP.objects.filter(establishment=est).values_list("id", flat=True))
        if osp_ids:
            updates = AU.objects.filter(establishment=est) | AU.objects.filter(prior_osp_id__in=osp_ids)
            # Corrections first: `corrects` is PROTECT, so a revision cannot go before the one
            # that corrects it.
            for update in updates.distinct().order_by("-revision_number"):
                update.delete()
            OSP.objects.filter(id__in=osp_ids).delete()

    @classmethod
    def _scalar_fields(cls, payload):
        """Fixture keys that map straight onto model fields (skip markers and structure)."""
        return {
            k: _decode(v)
            for k, v in payload.items()
            if not k.startswith(("_", "#", "@", "~")) and k not in cls.STRUCTURAL_KEYS
        }

    #: Columns Django stamps itself. `auto_now_add` / `auto_now` IGNORE a value passed to
    #: create(), so every reseed re-dated the farm's audit trail — approved-input changes,
    #: certifications, affidavits, notifications — to the day the command ran. The plan
    #: review then listed "10 materials added 2026-08-23" on a plan whose answers were written
    #: 2026-08-21, which is a fixture artifact, not a finding. A queryset update after create
    #: bypasses the auto stamp and restores what the rehearsal actually recorded.
    AUTO_TIMESTAMPS = ("created_at", "updated_at", "changed_at")

    @classmethod
    def _stamp(cls, obj, row):
        """Restore the fixture's own timestamps on `obj` after create(); returns obj."""
        if obj is None or not isinstance(row, dict):
            return obj
        names = {f.name for f in obj._meta.fields}
        vals = {k: _decode(row[k]) for k in cls.AUTO_TIMESTAMPS if k in names and row.get(k) not in (None, "")}
        if vals:
            type(obj).objects.filter(pk=obj.pk).update(**vals)
        return obj

    def _company(self, data, owner):
        """Create the company, grant the owner access, and give it a plan.

        Both halves were missing and both are load-bearing in production:

        ACCESS. `User.companies` is a many-to-many `through="WorksIn"` with
        `related_name="company_users"` — there is no `company.users`, and Django refuses `.add()`
        on a through-relation anyway. An earlier version of this method guarded with
        `hasattr(company, "users")`, which is simply False, so it silently granted nothing: the
        farm existed and the person who seeded it could not see it. `WorksIn` with
        COMPANY_ADMIN is what `provision_pilot` and `create_demo_user` both do, and
        `RetrieveCompanySerializer` gives role "CA" every establishment in the company.

        PLAN. A company with no Subscription row resolves to no plan at all, and that cascades:
        `can_create_parcel` / `can_create_establishment` / `can_create_production` all answer
        False, photo and document uploads are refused with NO_SUBSCRIPTION, voice input switches
        off. The farm would be visible and inert — you could show it and not touch it, which is
        the opposite of a demo. `pilot` is the correct plan: comped, internal, and hidden from
        the public lineup.
        """
        from subscriptions.models import Plan, Subscription
        from users.models import WorksIn

        company, _ = Company.objects.get_or_create(name=data["company"]["name"])

        membership, created = WorksIn.objects.get_or_create(
            user=owner,
            company=company,
            defaults={"role": WorksIn.COMPANY_ADMIN},
        )
        # An existing membership is left alone rather than upgraded — a seeder must not silently
        # escalate someone's role. But a VIEWER cannot open most of what this farm exists to
        # demonstrate, and finding that out by clicking around is a bad afternoon, so say it.
        if not created and membership.role != WorksIn.COMPANY_ADMIN:
            self.stdout.write(
                self.style.WARNING(
                    f"  {owner.email} already works in {company.name} as "
                    f"{membership.get_role_display()}, not Company Admin. Left unchanged — only "
                    "a Company Admin sees every establishment in a company."
                )
            )

        if not Subscription.objects.filter(company=company).exists():
            plan = Plan.objects.filter(slug="pilot").first()
            if plan is None:
                raise CommandError(
                    "No plan with slug 'pilot' exists. Run `manage.py create_plans` first — it is "
                    "the only thing that creates plan rows; `migrate` does not."
                )
            Subscription.objects.create(
                company=company,
                plan=plan,
                status="active",
                current_period_start=timezone.now(),
                current_period_end=timezone.now() + timedelta(days=365),
            )

        return company, membership

    def _establishment(self, data, company):
        fields = self._scalar_fields(data["establishment"])
        # Never inherited from the fixture: this is the flag that makes every export from this
        # farm say what it is. Set explicitly so it cannot be lost by an extraction change.
        fields["is_demo"] = True
        est = Establishment.objects.create(company=company, **fields)
        return est

    def _facilities(self, data, est):
        PHF = apps.get_model("certifications", "PostHarvestFacility")
        out = {}
        for row in data.get("post_harvest_facilities", []):
            obj = self._stamp(PHF.objects.create(establishment=est, **self._scalar_fields(row)), row)
            out[row["_id"]] = obj
        return out

    def _certifications(self, data, est):
        Cert = apps.get_model("certifications", "Certification")
        return {
            row["_id"]: self._stamp(Cert.objects.create(establishment=est, **self._scalar_fields(row)), row)
            for row in data.get("certifications", [])
        }

    @staticmethod
    def _assert_real_catalog_id(model_name, row):
        """Refuse a fixture catalogue row whose identifier is not the publisher's own.

        OMRI publishes company-letters + number (`dow-2900`); WSDA publishes a bare integer
        Product #. Anything else is a Trazo invention, and `registry_identifiers` withholds
        it from every reader — so seeding one creates a row that can never be cited.
        """
        from certifications.services.omri_verifier import looks_like_omri_code
        from certifications.services.registry_identifiers import is_real_wsda_product_number

        if model_name == "OMRIProduct":
            value = (row.get("omri_id") or "").strip()
            if not looks_like_omri_code(value):
                raise ValueError(f"Fixture OMRIProduct has a non-OMRI identifier: {value!r}")
        elif model_name == "WSDAMaterial":
            value = (row.get("wsda_id") or "").strip()
            if not is_real_wsda_product_number(value):
                raise ValueError(f"Fixture WSDAMaterial has a non-WSDA Product #: {value!r}")

    def _osp_graph(self, data, est, owner, certs):
        """Seed the § 205.201 plan and everything hanging off it.

        Without this the packet reports "No Organic System Plan on file" and "No approved-inputs
        list on file", and the Documentation Snapshot turns DOCUMENTED rows into GAP/REVIEW. The
        farm would then render the product at its weakest — which is the exact failure
        `seed_showcase_walnut_farm` was written to end, one farm over.

        Versions are created in `version_number` order so `previous_version` always points at a
        row that already exists; the answers themselves live in the `sections` and
        `module_responses` JSON columns and travel verbatim.
        """
        OSP = apps.get_model("certifications", "OrganicSystemPlan")
        AICL = apps.get_model("certifications", "ApprovedInputChangeLog")
        OCN = apps.get_model("certifications", "OSPChangeNotification")
        AU = apps.get_model("certifications", "OSPAnnualUpdate")
        NLS = apps.get_model("certifications", "NationalListSubstance")
        OMRI = apps.get_model("certifications", "OMRIProduct")
        WSDA = apps.get_model("certifications", "WSDAMaterial")

        # The approved-input registry lives on the OSP as three many-to-many sets, and a fresh
        # database has NO OMRI or WSDA rows at all (they arrive from a listing import, not a
        # migration). Create the ones this farm references before wiring the sets, or the
        # packet reports "No approved-inputs list on file" and demotes § 205.201(a)(2) to
        # REVIEW — an absence of evidence presented where the real farm shows DOCUMENTED.
        approved = {}
        for model_name, natural in (
            ("NationalListSubstance", "substance_name"),
            ("OMRIProduct", "product_name"),
            ("WSDAMaterial", "brand_name"),
        ):
            Model = apps.get_model("certifications", model_name)
            approved[model_name] = {}
            for key, row in data.get("approved_input_rows", {}).get(model_name, {}).items():
                # A fixture may not author a catalogue identifier. Both global catalogues are
                # transcriptions of a published list, and a demo farm that invents a row puts a
                # string into a certifier packet that resolves to nothing at the registry — which
                # is exactly what "OMRI-SVR-ENTRUST" and "WSDA-REG-FERT-2025-016" did. Refuse
                # loudly here rather than let the seed define the catalogue on a fresh database.
                self._assert_real_catalog_id(model_name, row)
                obj = Model.objects.filter(**{natural: key}).first()
                if obj is None:
                    obj = self._stamp(Model.objects.create(**self._scalar_fields(row)), row)
                approved[model_name][key] = obj

        M2M_SOURCE = {
            "approved_national_list_substances": "NationalListSubstance",
            "approved_omri_products": "OMRIProduct",
            "approved_wsda_materials": "WSDAMaterial",
        }

        osps = {}
        for row in sorted(data.get("osps", []), key=lambda r: r.get("version_number") or 0):
            kwargs = dict(establishment=est, created_by=owner, **self._scalar_fields(row))
            prev = row.get("#previous_version")
            if prev and prev in osps:
                kwargs["previous_version"] = osps[prev]
            cert = row.get("#certification")
            if cert and cert in certs:
                kwargs["certification"] = certs[cert]
            osp = self._stamp(OSP.objects.create(**kwargs), row)
            for m2m, model_name in M2M_SOURCE.items():
                keys = row.get("~" + m2m)
                if keys:
                    members = [approved[model_name][k] for k in keys if k in approved[model_name]]
                    getattr(osp, m2m).set(members)
            osps[row["_id"]] = osp

        def _target(row, key, model, field):
            ref = row.get("@" + key)
            if not ref:
                return None
            return model.objects.filter(**{field: ref[field]}).first()

        for row in data.get("approved_input_changes", []):
            osp = osps.get(row.get("#osp"))
            if osp is None:
                continue
            kwargs = dict(osp=osp, changed_by=owner, **self._scalar_fields(row))
            for key, model, field in (
                ("target_national_list", NLS, "substance_name"),
                ("target_omri", OMRI, "product_name"),
                ("target_wsda", WSDA, "brand_name"),
            ):
                obj = _target(row, key, model, field)
                if obj is not None:
                    kwargs[key] = obj
            self._stamp(AICL.objects.create(**kwargs), row)

        for row in data.get("osp_change_notifications", []):
            osp = osps.get(row.get("#osp"))
            if osp is not None:
                self._stamp(OCN.objects.create(osp=osp, created_by=owner, **self._scalar_fields(row)), row)

        for row in data.get("annual_updates", []):
            kwargs = self._scalar_fields(row)
            prior, new = osps.get(row.get("#prior_osp")), osps.get(row.get("#new_osp"))
            if prior is not None:
                kwargs["prior_osp"] = prior
            if new is not None:
                kwargs["new_osp"] = new
            update = AU.objects.create(**kwargs)
            if update.submitted_at is not None and update.filed_pdf is None:
                # Filed before Trazo kept a frozen copy, and unsigned in Trazo: exactly what
                # migration 0044 marks on an existing database. A fresh seed never runs that
                # migration's data step, so without this the row read as neither state.
                update.snapshot_state = AU.SNAPSHOT_LEGACY_NONE
                update.save(update_fields=["snapshot_state"])
            self._stamp(update, row)

        return osps

    def _parcels(self, data, est):
        out = {}
        for row in data["parcels"]:
            obj = self._stamp(Parcel.objects.create(establishment=est, **self._scalar_fields(row)), row)
            out[row["_id"]] = obj
        return out

    # ------------------------------------------------------------------
    def _resolve_crop_type(self, ref):
        CropType = apps.get_model("carbon", "CropType")
        obj = CropType.objects.filter(slug=ref["slug"]).first() or CropType.objects.filter(name=ref["name"]).first()
        if obj is None:
            raise CommandError(
                f"CropType {ref['name']!r} (slug {ref['slug']!r}) is not in this database. "
                "Run `populate_usda_crop_types --crops-only` first."
            )
        return obj

    def _resolve_substance(self, ref):
        NLS = apps.get_model("certifications", "NationalListSubstance")
        obj = NLS.objects.filter(substance_name=ref["substance_name"]).first()
        if obj is None:
            raise CommandError(
                f"NationalListSubstance {ref['substance_name']!r} missing. Run the National "
                "List seeder before this command."
            )
        return obj

    def _seasons(self, data, est, parcels, facilities, owner):
        out = {}
        for row in data["seasons"]:
            fields = self._scalar_fields(row)
            parcel = parcels[row["#parcel"]]
            product, _ = Product.objects.get_or_create(name=row["@product"]["name"])
            kwargs = dict(
                parcel=parcel,
                product=product,
                operator=owner,
                **fields,
            )
            if "@crop_type" in row:
                kwargs["crop_type"] = self._resolve_crop_type(row["@crop_type"])
            history = self._stamp(History.objects.create(**kwargs), row)
            linked = [facilities[f] for f in row.get("post_harvest_facilities", []) if f in facilities]
            if linked:
                history.post_harvest_facilities.set(linked)
            out[row["_id"]] = history
        # `Parcel.current_history` points at whichever season the parcel is working now.
        for row in data["parcels"]:
            ref = row.get("#current_history")
            if ref and ref in out:
                p = parcels[row["_id"]]
                p.current_history = out[ref]
                p.save(update_fields=["current_history"])
        return out

    def _related_records(self, data, seasons, parcels, event_map, owner):
        """Everything else that hangs off a season or a parcel and is NOT derived.

        Found by walking every model with a foreign key into this farm rather than by listing
        them, which is how `SalesRecord` turned up at all: its FK is named `production`, not
        `history`, so a hand-written list missed it and the packet demoted § 205.307 sales
        documentation from DOCUMENTED to REVIEW.

        `CarbonEntry` and `USDAComplianceRecord` are deliberately NOT carried. Both are rebuilt
        by post_save signals as the events are written, landing on exactly the same 333 rows as
        the source database; seeding them too would double every figure.
        """
        PCH = apps.get_model("product", "ParcelCropHistory")
        SR = apps.get_model("history", "SalesRecord")
        PPI = apps.get_model("history", "ProductionPlanItem")
        HS = apps.get_model("history", "HistoryScan")
        EA = apps.get_model("history", "EventAmendment")
        ET = apps.get_model("carbon", "EventTemplate")

        for row in data.get("parcel_crop_history", []):
            parcel = parcels.get(row.get("#parcel"))
            if parcel is not None:
                self._stamp(PCH.objects.create(parcel=parcel, **self._scalar_fields(row)), row)

        for row in data.get("sales_records", []):
            season = seasons.get(row.get("#production"))
            if season is None:
                continue
            sale = self._stamp(SR.objects.create(production=season, **self._scalar_fields(row)), row)
            linked = [
                event_map[("ProductionEvent", pk)]
                for pk in row.get("~harvest_events", [])
                if ("ProductionEvent", pk) in event_map
            ]
            if linked:
                sale.harvest_events.set(linked)

        for row in data.get("production_plan_items", []):
            season = seasons.get(row.get("#history"))
            if season is None:
                continue
            kwargs = dict(history=season, **self._scalar_fields(row))
            ref = row.get("@source_template")
            if ref and ref.get("name"):
                template = ET.objects.filter(name=ref["name"]).first()
                if template is not None:
                    kwargs["source_template"] = template
            self._stamp(PPI.objects.create(**kwargs), row)

        for row in data.get("history_scans", []):
            season = seasons.get(row.get("#history"))
            if season is not None:
                self._stamp(HS.objects.create(history=season, **self._scalar_fields(row)), row)

        # `EventAmendment` stores a bare (event_type code, event_id) pair rather than a real
        # relation, so the id is a primary key from the SOURCE database and renumbers here.
        # Left untranslated it would point at whatever row happens to hold that pk — attaching
        # a § 205.103 correction to an unrelated record, which is worse than losing it.
        from history.constants import EVENT_TYPE_TO_MODEL

        for row in data.get("event_amendments", []):
            season = seasons.get(row.get("#history"))
            if season is None:
                continue
            fields = self._scalar_fields(row)
            old_id = fields.get("event_id")
            model = EVENT_TYPE_TO_MODEL.get(fields.get("event_type"))
            if old_id is not None:
                if model is None:
                    continue
                target = event_map.get((model.__name__, old_id))
                if target is None:
                    # A correction whose subject did not come across is not seeded at all: an
                    # amendment pointing at nothing reads as a missing record to a reviewer.
                    continue
                fields["event_id"] = target.pk
            self._stamp(EA.objects.create(history=season, amended_by=owner, **fields), row)

    def _events(self, data, seasons, owner):
        total = 0
        # Two passes: `equipment_cleaning_event` is an event pointing at ANOTHER event, so the
        # target may not exist when the referrer is written. Create everything, then wire.
        created: dict[tuple[str, int], object] = {}
        deferred: list[tuple[str, int, int]] = []

        for row_season in data["seasons"]:
            history = seasons[row_season["_id"]]
            for model_name in EVENT_MODELS:
                Model = apps.get_model("history", model_name)
                for row in row_season["events"].get(model_name, []):
                    fields = self._scalar_fields(row)
                    kwargs = dict(history=history, created_by=owner, **fields)
                    if "@national_list_substance" in row:
                        kwargs["national_list_substance"] = self._resolve_substance(row["@national_list_substance"])
                    obj = self._stamp(Model.objects.create(**kwargs), row)
                    created[(model_name, row["_id"])] = obj
                    if "#equipment_cleaning_event" in row:
                        deferred.append((model_name, row["_id"], row["#equipment_cleaning_event"]))
                    total += 1

        for model_name, own_id, target_id in deferred:
            obj = created[(model_name, own_id)]
            # The cleaning event it points at is a ProductionEvent in every observed case, but
            # look through all models rather than assuming — a wrong link here is a § 205.272
            # contamination-prevention claim attached to the wrong record.
            target = next(
                (v for (m, i), v in created.items() if i == target_id and m == "ProductionEvent"),
                None,
            )
            if target is not None:
                obj.equipment_cleaning_event = target
                obj.save(update_fields=["equipment_cleaning_event"])

        return total, created

    # ------------------------------------------------------------------
    # The renewal, driven through the product's own services (OSP alignment audit 2026-10, S6).
    # Every step below is one an operator takes in the app: confirm record types, correct a
    # filed update, sign it, file it, open next year's plan and start next year's update. The
    # frozen copy is rendered by `file_filing` itself, never written from the fixture.

    def _record_type_confirmations(self, data, osps, owner):
        from certifications.services.common_osp_records import confirm

        for row in data.get("osps", []):
            keys = row.get("_confirm_record_types")
            if keys and row["_id"] in osps:
                confirm(osps[row["_id"]], keys, user=owner)

    def _renewal(self, data, osps, owner):
        """Correct, sign and file the year's update; fork next year's plan; open its update."""
        from certifications.services.annual_update_filing import correct_filing, file_filing, sign_filing
        from certifications.services.annual_update_linking import link_filing_to_open_draft
        from certifications.services.osp_fork import fork_plan

        AU = apps.get_model("certifications", "OSPAnnualUpdate")
        by_fixture_id = {}
        for row in data.get("annual_updates", []):
            prior = osps.get(row.get("#prior_osp"))
            if prior is not None:
                by_fixture_id[row["_id"]] = AU.objects.get(
                    establishment_id=prior.establishment_id,
                    reporting_year=row["reporting_year"],
                    revision_number=1,
                )

        for row in data.get("annual_update_corrections", []):
            corrected = by_fixture_id[row["#corrects"]]
            revision = correct_filing(corrected, owner)
            fields = self._scalar_fields(row)
            for name, value in fields.items():
                setattr(revision, name, value)
            revision.save(update_fields=[*fields, "updated_at"])

            sign = row.get("_sign") or {}
            revision = sign_filing(revision, owner, signer_title=sign.get("signer_title", ""))
            # The account that pressed Sign is whoever ran the seed; the person who signs on the
            # farm's behalf is the fixture's member-manager. Name and date sit outside the signed
            # hash, so restating them before filing changes no signed content.
            stamped = {k: _decode(v) for k, v in sign.items() if k in ("signer_name", "signed_at")}
            if stamped:
                AU.objects.filter(pk=revision.pk).update(**stamped)
                revision.refresh_from_db()

            filed = row.get("_file")
            if filed:
                revision = file_filing(
                    revision,
                    filing_method=filed.get("filing_method", ""),
                    submitted_at=_decode(filed.get("submitted_at")),
                )
            by_fixture_id[row["_id"]] = revision

        forks = {}
        for row in data.get("plan_forks", []):
            forks[row["_id"]] = fork_plan(osps[row["#previous_version"]], owner)

        for row in data.get("draft_annual_updates", []):
            prior = osps[row["#prior_osp"]]
            draft = AU.objects.create(
                prior_osp=prior,
                establishment_id=prior.establishment_id,
                revision_number=1,
                created_by=owner,
                **self._scalar_fields(row),
            )
            # What the viewset's perform_create does: an update started while a newer draft is
            # open belongs to that draft.
            link_filing_to_open_draft(draft)
        return forks

    def _specimen_documents(self, data, est, owner):
        """File the specimen source documents the packet attaches (labels, sale paperwork).

        The bytes are generated here from the fixture's own rows and stamped SPECIMEN on every
        page. They stand in for a scan the operator would upload, so the packet can show a file
        attached against its requirement and a sale with its source document beside sales that
        have only a number typed in.
        """
        from documents.services.filing import file_document

        SR = apps.get_model("history", "SalesRecord")
        sales = {(row.get("invoice_number") or ""): row for row in data.get("sales_records", [])}
        for row in data.get("specimen_documents", []):
            sale = None
            lines = list(row.get("lines") or [])
            invoice = row.get("@sales_record_invoice")
            if invoice:
                sale = SR.objects.filter(production__parcel__establishment=est, invoice_number=invoice).first()
                if sale is None:
                    raise CommandError(f"specimen document names sale {invoice!r}, which was not seeded")
                lines = self._sale_lines(sales.get(invoice) or {}) + lines
            file_document(
                establishment=est,
                source="upload",
                folder=row.get("folder") or "uploads",
                title=row["title"],
                filename=row["filename"],
                content=_specimen_pdf(row["title"], lines),
                content_type="application/pdf",
                linked_section=row.get("linked_section", ""),
                requirement=row.get("requirement", ""),
                sales_record=sale,
                source_kind=row.get("source_kind", ""),
                created_by=owner,
            )

    @staticmethod
    def _sale_lines(row) -> list[str]:
        labels = (
            ("invoice_number", "Invoice"),
            ("bill_of_lading", "Bill of lading"),
            ("buyer_name", "Buyer"),
            ("destination", "Destination"),
            ("carrier_name", "Carrier"),
            ("vehicle_id", "Vehicle"),
            ("transport_notes", "Notes"),
        )
        out = []
        sale_date = _decode(row.get("sale_date"))
        if sale_date:
            out.append(f"Date: {sale_date.isoformat()}")
        for key, label in labels:
            if row.get(key):
                out.append(f"{label}: {row[key]}")
        return out


def _specimen_pdf(title: str, lines: list[str]) -> bytes:
    """A one-page PDF carrying `lines`, watermarked SPECIMEN like every export of a demo farm."""
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from common.specimen import draw_specimen_watermark

    styles = getSampleStyleSheet()
    story = [
        Paragraph(escape(title), styles["Title"]),
        Paragraph("Specimen document for a demo farm. It is not a real invoice, label or record.", styles["Italic"]),
        Spacer(1, 12),
    ]
    story += [Paragraph(escape(line), styles["BodyText"]) for line in lines]
    buf = io.BytesIO()

    def _page(canvas, _doc):
        draw_specimen_watermark(canvas, letter)

    SimpleDocTemplate(buf, pagesize=letter, title=title).build(story, onFirstPage=_page, onLaterPages=_page)
    return buf.getvalue()
