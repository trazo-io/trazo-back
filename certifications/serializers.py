from django.utils import timezone

from dateutil.relativedelta import relativedelta
from rest_framework import serializers

from backend.permissions import CallerScopedRelatedFields
from certifications.services.osp_sections import registry_sync_diff, sections_with_text
from certifications.services.registry_identifiers import wsda_product_number
from documents.models import GeneratedDocument

from .models import (
    OSP_SECTION_KEYS,
    AdjoiningLandAffidavit,
    ApprovedInputChangeLog,
    BrandOwner,
    Certification,
    CertificationVerificationLog,
    CertifierAccessLink,
    CertifierAccessLog,
    LandownerAffidavit,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    OSPChangeNotification,
    PlanMaterialEntry,
    PostHarvestFacility,
    ProductionEquipment,
    StateOrganicRegistration,
    Supplier,
    SupplierCertificate,
    SupplierName,
    normalize_supplier_name,
)


class PlanMaterialEntrySerializer(serializers.ModelSerializer):
    """Operator-authored materials-list rows (CCOF ORGB41 §A-§D, WSDA AGR 2196).

    The write path enforces the one rule the model exists under: a listing basis may not claim
    more than the row supports. `certifier_letter` without a reference is refused, and a catalog
    basis without the matching FK is refused — otherwise "OMRI listed" becomes a free-text claim
    the operator can type, which is the whole defect this replaces, inverted.
    """

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    listing_basis_display = serializers.CharField(source="get_listing_basis_display", read_only=True)
    listing_statement = serializers.CharField(read_only=True)
    agent_review_statement = serializers.CharField(read_only=True)
    label_document_title = serializers.CharField(source="label_document.title", read_only=True, default=None)

    class Meta:
        model = PlanMaterialEntry
        fields = [
            "id",
            "product_name",
            "manufacturer",
            "category",
            "category_display",
            "reason_for_use",
            "listing_basis",
            "listing_basis_display",
            "listing_statement",
            "certifier_letter_reference",
            "status",
            "notes",
            "agent_review",
            "agent_review_date",
            "agent_review_reference",
            "agent_review_agent",
            "agent_review_use",
            "agent_review_statement",
            "label_document",
            "label_document_title",
            "facility_material_type",
            "where_used",
            "applied_by_fumigation",
            "national_list_substance",
            "omri_product",
            "wsda_material",
            "created_at",
            "updated_at",
        ]
        # The agent is the plan's, set by the server when a review is recorded: an operator never
        # names which agent approved a material, so one agent's approval cannot be typed as another's.
        read_only_fields = ["id", "created_at", "updated_at", "agent_review_agent"]

    def validate_label_document(self, value):
        """A file uploaded to THIS plan's farm. Another farm's id fails exactly like one that does not
        exist, so the refusal does not confirm it does; a generated document is not a label."""
        osp = self.context.get("osp")
        if value is None:
            return value
        if osp is None or value.establishment_id != osp.establishment_id or value.source != "upload":
            raise serializers.ValidationError(f'Invalid pk "{value.pk}" - object does not exist.')
        return value

    def validate_agent_review_date(self, value):
        from django.utils import timezone

        if value is not None and value > timezone.localdate():
            raise serializers.ValidationError("The date on the agent's list or letter cannot be in the future.")
        return value

    def validate_product_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError(
                "A material needs a name — this is the column CCOF and WSDA both ask for first."
            )
        return cleaned

    def validate(self, attrs):
        # One material, one row. Nothing else stopped a double-click — or a slow network and a
        # second press — from putting the same product on a regulatory list twice, and a
        # duplicated line is a reviewer's question the operator has to answer for no reason.
        # Checked case-insensitively on the name within this OSP; a genuinely different
        # formulation is a different name.
        osp = self.context.get("osp")
        name = (attrs.get("product_name") or getattr(self.instance, "product_name", "") or "").strip()
        if osp is not None and name:
            clash = osp.plan_material_entries.filter(product_name__iexact=name)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"product_name": f"{name} is already on this plan's materials list."})

        # 2026-11-04: the agent's approval is its own record (`agent_review`), not a kind of listing;
        # migration 0068 moved every certifier-letter row there. A new one is refused rather than
        # silently converted, so a client still sending it learns where the approval now goes.
        if attrs.get("listing_basis") == PlanMaterialEntry.BASIS_CERTIFIER_LETTER:
            raise serializers.ValidationError(
                {
                    "listing_basis": (
                        "Record the certifier's approval under the agent's review (approved, with the list "
                        "or letter and its date), not as a listing."
                    )
                }
            )
        review = attrs.get("agent_review", getattr(self.instance, "agent_review", ""))
        if review in (PlanMaterialEntry.REVIEW_APPROVED, PlanMaterialEntry.REVIEW_NOT_APPROVED):
            reference = attrs.get("agent_review_reference", getattr(self.instance, "agent_review_reference", ""))
            when = attrs.get("agent_review_date", getattr(self.instance, "agent_review_date", None))
            if not (reference or "").strip() and when is None:
                raise serializers.ValidationError(
                    {
                        "agent_review_reference": (
                            "Name the agent's list or letter that shows it, or its date. An agent's decision "
                            "with nothing behind it is the claim a reviewer asks about."
                        )
                    }
                )
        basis = attrs.get("listing_basis", getattr(self.instance, "listing_basis", PlanMaterialEntry.BASIS_NONE))
        reference = attrs.get("certifier_letter_reference", getattr(self.instance, "certifier_letter_reference", ""))
        if basis == PlanMaterialEntry.BASIS_CERTIFIER_LETTER and not (reference or "").strip():
            raise serializers.ValidationError(
                {
                    "certifier_letter_reference": (
                        "Name the certifier letter that approved this material. "
                        "\u201cApproved by our certifier\u201d with nothing behind it is the kind of "
                        "unsupported claim a reviewer sends the packet back for."
                    )
                }
            )
        catalog_field = {
            PlanMaterialEntry.BASIS_OMRI: "omri_product",
            PlanMaterialEntry.BASIS_WSDA: "wsda_material",
            PlanMaterialEntry.BASIS_NATIONAL_LIST: "national_list_substance",
        }.get(basis)
        if catalog_field:
            resolved = attrs.get(catalog_field, getattr(self.instance, catalog_field, None))
            if not resolved:
                raise serializers.ValidationError(
                    {
                        catalog_field: (
                            "A catalog listing basis has to point at the catalog row it came from. "
                            "Search for the material to attach it, or record it as operator-entered "
                            "with no third-party listing."
                        )
                    }
                )
        # § 205.602 substances are prohibited; the same refusal as add_approved_input, which also
        # accepts the rows the rule allows for a stated use.
        nl = attrs.get("national_list_substance", getattr(self.instance, "national_list_substance", None))
        if nl is not None and nl.is_refused_on_a_plan:
            raise serializers.ValidationError(
                {
                    "national_list_substance": (
                        f"{nl.substance_name} is prohibited in organic production "
                        f"(\u00a7 {nl.cfr_section or '205.602'}) and cannot be put on an organic system plan."
                    )
                }
            )
        # CCOF §F/§G's three columns belong to a facility pest row only. On any other row they would print
        # nowhere and read as an answer to a question never asked of that material.
        category = attrs.get("category", getattr(self.instance, "category", ""))
        if category != "facility_pest":
            stray = [
                f
                for f in ("facility_material_type", "where_used", "applied_by_fumigation")
                if attrs.get(f) not in (None, "")
            ]
            if stray:
                raise serializers.ValidationError(
                    {
                        f: "Asked only of a material used for pest control in a handling or storage facility."
                        for f in stray
                    }
                )
            # Moving a row out of facility pest control clears the three answers, so moving it back asks them
            # again rather than reviving values nobody re-affirmed (review of back #340).
            if "category" in attrs and getattr(self.instance, "category", "") == "facility_pest":
                attrs.update({"facility_material_type": "", "where_used": "", "applied_by_fumigation": None})
        return attrs


class PostHarvestFacilitySerializer(serializers.ModelSerializer):
    """Producer-dashboard CRUD for off-farm post-harvest handlers (CCOF G6.1)."""

    facility_type_display = serializers.CharField(source="get_facility_type_display", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    verification_status_display = serializers.CharField(source="get_verification_status_display", read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    cert_is_current = serializers.BooleanField(read_only=True)
    is_own = serializers.BooleanField(read_only=True)
    operated_by_display = serializers.CharField(source="get_operated_by_display", read_only=True)
    #: The crops on the production records linked to this facility, by season year
    #: (`facility_crops.crops_by_facility`); read from the records, never typed.
    crops_recorded = serializers.SerializerMethodField()

    class Meta:
        model = PostHarvestFacility
        fields = [
            "id",
            "public_id",
            "establishment",
            "name",
            "facility_type",
            "facility_type_display",
            "role",
            "role_display",
            "operated_by",
            "operated_by_display",
            "is_own",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "layout_document",
            "certification_number",
            "certifier_name",
            "effective_date",
            "expiry_date",
            "cert_document",
            "verification_status",
            "verification_status_display",
            "is_verified",
            "cert_is_current",
            "last_verified_at",
            "verification_source",
            "notes",
            "products_detail",
            "crops_recorded",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            # The nested route owns this — the facility belongs to the establishment in the
            # URL, never to one named in the body.
            "establishment",
            "verification_status",
            "last_verified_at",
            "verification_source",
            "raw_api_response",
            "created_at",
            "updated_at",
        ]

    def get_crops_recorded(self, obj):
        from certifications.services.facility_crops import crops_for

        return [{"crop": crop, "years": years} for crop, years in crops_for(obj)]

    _CERTIFICATE_FIELDS = ("certification_number", "certifier_name", "effective_date", "expiry_date", "cert_document")

    def validate(self, attrs):
        """An own facility is covered by the operation's own certificate, so it carries none of its own.

        A certificate typed onto the farm's own shed would print as a second certified operation in the plan.
        Checked against the stored row too, so switching an existing handler to "our own" with its certificate
        still on it is refused rather than half-applied.
        """
        attrs = super().validate(attrs)
        operated_by = attrs.get("operated_by", getattr(self.instance, "operated_by", "another_operation"))
        if operated_by != "this_operation":
            return attrs
        held = [f for f in self._CERTIFICATE_FIELDS if (attrs[f] if f in attrs else getattr(self.instance, f, None))]
        if held:
            raise serializers.ValidationError(
                {f: "An own facility is covered by the operation's own certificate; leave this empty." for f in held}
            )
        return attrs


class SupplierNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierName
        fields = ["id", "name"]


class SupplierCertificateSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    """One certificate copy. `document` is a file in this farm's Documents: another farm's or
    another company's id fails exactly like an id that does not exist, so the refusal says
    nothing about which ids exist."""

    caller_scoped_fields = {"document": "establishment__company"}
    establishment_scoped_fields = {"document": "establishment_id"}

    document_title = serializers.CharField(source="document.title", read_only=True)

    class Meta:
        model = SupplierCertificate
        fields = [
            "id",
            "document",
            "document_title",
            "issued_on",
            "anniversary_date",
            "original_effective_date",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class BrandOwnerSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    """A company whose brand this farm packs into. Both documents must be files in the URL's farm:
    another farm's or company's id fails exactly like an id that does not exist."""

    caller_scoped_fields = {
        "certificate_document": "establishment__company",
        "agreement_document": "establishment__company",
    }
    establishment_scoped_fields = {
        "certificate_document": "establishment_id",
        "agreement_document": "establishment_id",
    }

    certification_status_display = serializers.CharField(source="get_certification_status_display", read_only=True)
    # default=None: with no document the key reads null instead of dropping out of the row (review of #268).
    certificate_document_title = serializers.CharField(
        source="certificate_document.title", read_only=True, default=None
    )
    agreement_document_title = serializers.CharField(source="agreement_document.title", read_only=True, default=None)
    #: What G7.0 page C says of this owner (`brand_owners.owner_state`): on_file, certificate_missing,
    #: certificate_old, agreement_missing or status_unknown.
    state = serializers.SerializerMethodField()

    class Meta:
        model = BrandOwner
        fields = [
            "id",
            "public_id",
            "name",
            "brand_names",
            "products",
            "certification_status",
            "certification_status_display",
            "certifier_name",
            "nop_operation_id",
            "certificate_document",
            "certificate_document_title",
            "certificate_issued_on",
            "agreement_document",
            "agreement_document_title",
            "notes",
            "state",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def get_state(self, obj):
        from certifications.services.brand_owners import owner_state

        return owner_state(obj)[0]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name the brand owner.")
        return value

    def validate(self, attrs):
        # A copy with no issue date cannot be judged current, and the plan would print it as on file.
        document = attrs.get("certificate_document", getattr(self.instance, "certificate_document", None))
        issued = attrs.get("certificate_issued_on", getattr(self.instance, "certificate_issued_on", None))
        if document is not None and issued is None:
            raise serializers.ValidationError(
                {"certificate_issued_on": "Enter the issue date printed on the certificate."}
            )
        return attrs


class ProductionEquipmentSerializer(serializers.ModelSerializer):
    """One item of farm equipment that contacts organic crops, on the farm in the URL."""

    use_display = serializers.CharField(source="get_use_display", read_only=True)
    ownership_display = serializers.CharField(source="get_ownership_display", read_only=True)
    #: What G6.0 page F says of this item (`production_equipment.item_state`): complete or incomplete,
    #: with the codes of the facts still missing (`MISSING_FACTS`). The app shows these; it never
    #: re-derives them.
    state = serializers.SerializerMethodField()
    missing = serializers.SerializerMethodField()

    class Meta:
        model = ProductionEquipment
        fields = [
            "id",
            "public_id",
            "name",
            "use",
            "use_display",
            "dedicated_organic",
            "ownership",
            "ownership_display",
            "cleaning_method",
            "cleaning_materials",
            "rinsed",
            "rinse_detail",
            "notes",
            "state",
            "missing",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def get_state(self, obj):
        from certifications.services.production_equipment import item_state

        return item_state(obj)[0]

    def get_missing(self, obj):
        from certifications.services.production_equipment import missing_codes

        return missing_codes(obj)

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name the equipment.")
        return value


class SupplierSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    """A seed or planting-stock supplier on the farm in the URL, with its confirmed spellings and
    certificate copies. Spellings and copies are added through their own actions.

    Since 2026.11.08 also a supplier of organic crops or products the operation buys in (CCOF G6.5,
    OTCO C12 12.2-4): what it supplies, and for an uncertified one the certified operation it sources
    from and its Exempt Handler Affidavit, a file in this farm's Documents."""

    caller_scoped_fields = {"exempt_handler_affidavit": "establishment__company"}
    establishment_scoped_fields = {"exempt_handler_affidavit": "establishment_id"}
    exempt_handler_affidavit_title = serializers.CharField(
        source="exempt_handler_affidavit.title", read_only=True, default=None
    )
    #: What G6.5 says of this supplier as a sourcing supplier (`sourced_products.supplier_state`), or
    #: null when it supplies no bought-in product.
    sourcing_state = serializers.SerializerMethodField()
    #: The issue date of the copy that state is about (`sourced_products.newest_certificate`), so the app
    #: never picks a date by array position (review of app #241).
    sourcing_certificate_issued_on = serializers.SerializerMethodField()

    organic_status_display = serializers.CharField(source="get_organic_status_display", read_only=True)
    names = SupplierNameSerializer(many=True, read_only=True)
    certificates = SupplierCertificateSerializer(many=True, read_only=True)
    archived = serializers.BooleanField(required=False)
    #: Records whose supplier text resolves here. Set by the view, which counts once per request.
    records_count = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id",
            "public_id",
            "name",
            "organic_status",
            "organic_status_display",
            "nop_operation_id",
            "certifier_name",
            "notes",
            "sourced_products",
            "source_operation",
            "exempt_handler_affidavit",
            "exempt_handler_affidavit_title",
            "sourcing_state",
            "sourcing_certificate_issued_on",
            "archived",
            "archived_at",
            "names",
            "certificates",
            "records_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "archived_at", "created_at", "updated_at"]

    def get_sourcing_state(self, obj):
        from certifications.services.sourced_products import supplier_state

        if not (obj.sourced_products or "").strip():
            return None
        return supplier_state(obj)[0]

    def get_sourcing_certificate_issued_on(self, obj):
        from certifications.services.sourced_products import newest_certificate

        if not (obj.sourced_products or "").strip():
            return None
        newest = newest_certificate(obj)
        return newest.issued_on.isoformat() if newest else None

    def get_records_count(self, obj):
        counts = self.context.get("spelling_counts") or {}
        return sum(counts.get(n.normalized, (None, 0))[1] for n in obj.names.all())

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["archived"] = instance.archived_at is not None
        return data

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name the supplier.")
        return value

    def _apply_archived(self, validated_data, instance=None):
        archived = validated_data.pop("archived", None)
        if archived is None:
            return
        if archived and (instance is None or instance.archived_at is None):
            validated_data["archived_at"] = timezone.now()
        elif not archived:
            validated_data["archived_at"] = None

    def create(self, validated_data):
        """A new supplier is known by its own name from the start: that spelling is confirmed with
        it, unless another supplier on the farm already holds it."""
        self._apply_archived(validated_data)
        establishment_id = validated_data["establishment_id"]
        spelling = normalize_supplier_name(validated_data["name"])
        if SupplierName.objects.filter(establishment_id=establishment_id, normalized=spelling).exists():
            raise serializers.ValidationError({"name": "Another supplier on this farm already uses this name."})
        supplier = super().create(validated_data)
        SupplierName.objects.create(supplier=supplier, name=supplier.name)
        return supplier

    def update(self, instance, validated_data):
        """A renamed supplier is known by its new name too, like a new one; its old spellings stay,
        because records written that way still name it."""
        self._apply_archived(validated_data, instance)
        new_name = validated_data.get("name")
        spelling = normalize_supplier_name(new_name) if new_name else None
        if spelling:
            held = (
                SupplierName.objects.filter(establishment_id=instance.establishment_id, normalized=spelling)
                .values_list("supplier_id", flat=True)
                .first()
            )
            if held is not None and held != instance.pk:
                raise serializers.ValidationError({"name": "Another supplier on this farm already uses this name."})
        supplier = super().update(instance, validated_data)
        if spelling and held is None:
            SupplierName.objects.create(supplier=supplier, name=supplier.name)
        return supplier


class CertificationVerificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificationVerificationLog
        fields = [
            "id",
            "attempted_at",
            "status_before",
            "status_after",
            "verification_source",
            "success",
            "error_message",
        ]
        read_only_fields = fields


class CertificationSerializer(serializers.ModelSerializer):
    """Full serializer for producer dashboard CRUD."""

    is_active = serializers.BooleanField(read_only=True)
    consumer_display_status = serializers.CharField(read_only=True)
    # 🔴 2026-09-16 — the producer dashboard needs the third state too.
    #
    # `CertificationManager` rendered its badge from the raw `verification_status`, so a row an
    # admin edit or a fixture marked "verified" painted green with "Verified via USDA Organic
    # Integrity Database" on the farm profile — including for a seeded operation. It now reads
    # `consumer_display_status`, and this field lets it distinguish "we did not match you"
    # from "these records are fabricated" instead of collapsing both to self-reported.
    specimen = serializers.SerializerMethodField()
    certification_type_display = serializers.CharField(source="get_certification_type_display", read_only=True)
    verification_status_display = serializers.CharField(source="get_verification_status_display", read_only=True)

    class Meta:
        model = Certification
        fields = [
            "id",
            "public_id",
            "certification_type",
            "certification_type_display",
            "certification_number",
            "certifier_name",
            "effective_date",
            "expiry_date",
            "certification_scope",
            "certified_items",
            "verification_status",
            "verification_status_display",
            "last_verified_at",
            "verification_source",
            "verification_source_url",
            "verification_notes",
            "usda_operation_name",
            "notes",
            "document_url",
            "is_active",
            "consumer_display_status",
            "specimen",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "specimen",
            "verification_status",
            "last_verified_at",
            "verification_source",
            "verification_source_url",
            "raw_api_response",
            "verification_notes",
            "created_at",
            "updated_at",
        ]

    def get_specimen(self, obj):
        """True when this certificate belongs to a FABRICATED operation (`Establishment.is_demo`)."""
        from common.specimen import is_specimen

        return is_specimen(getattr(obj, "establishment", None))


class ConsumerCertificationSerializer(serializers.ModelSerializer):
    """Minimal serializer for consumer QR page. FTC-compliant language only."""

    display_name = serializers.CharField(source="get_certification_type_display", read_only=True)
    # 🔴 2026-09-08 — was `source="consumer_display_status"`, read straight off the model.
    #
    # That property answers "is this claim substantiated by the source we cite", and it answers
    # it correctly. What it cannot see is whether the OPERATION exists: a seeded farm whose
    # fixture stamped `verification_source="usda_organic_integrity_db"` satisfied it honestly
    # and rendered the green "Verified via USDA Organic Integrity Database" card, naming a real
    # accredited certifier, from invented records. `consumer_certification_status` adds the
    # specimen check, and every consumer surface reads that one function.
    status = serializers.SerializerMethodField()
    specimen = serializers.SerializerMethodField()

    class Meta:
        model = Certification
        fields = [
            "display_name",
            "certifier_name",
            "status",
            "specimen",
            "effective_date",
            "expiry_date",
            "verification_source_url",
        ]

    def get_status(self, obj):
        from certifications.services.consumer_claim_validator import consumer_certification_status

        return consumer_certification_status(obj)

    def get_specimen(self, obj):
        """True when this certificate belongs to a FABRICATED operation.

        Emitted so the card can say WHY it is not showing a verified badge. Absent-as-False is
        deliberate on the payload above (`get_specimen` on the history serializer returns None
        for a real farm) but a plain boolean is right here: this is a per-row field in a list
        the client iterates, and a missing key would read as "unknown" rather than "real".
        """
        from common.specimen import is_specimen

        return is_specimen(getattr(obj, "establishment", None))


# ---------------------------------------------------------------------------
# Sprint 5A — OSP / Annual Update / Landowner Affidavit serializers
# ---------------------------------------------------------------------------


def packet_agent_payload(osp) -> dict:
    """Which agent the packet is for, where that came from, and whether it speaks that agent's forms.

    The plan page shows this beside the picker, so the grower learns before submitting what the
    coverage page will tell their reviewer. Same functions the packet calls, so the two agree.
    """
    from certifications.certifying_agents import agent_for_name
    from certifications.services.packet_coverage import packet_agent, registered_certifiers

    agent = packet_agent(osp)
    known = agent_for_name(agent.name) if agent.slug else None
    return {
        "name": agent.name,
        # The picker's own spelling of a recognised agent. A certificate reads "Washington State
        # Department of Agriculture Organic Program"; the picker offers the Integrity DB spelling,
        # so a form prefilled from `name` opened under "Other" for an agent that IS on the list.
        "canonical_name": known.name if known else "",
        "slug": agent.slug,
        "source": agent.source,
        "own_numbering": bool(agent.slug and agent.slug in registered_certifiers()),
    }


class OrganicSystemPlanListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — omits full sections JSONB."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    section_completion = serializers.FloatField(read_only=True)
    # The count the OSP page and the onboarding checklist show; see services/osp_sections.py.
    sections_with_text = serializers.SerializerMethodField()
    packet_agent = serializers.SerializerMethodField()

    def get_packet_agent(self, osp):
        return packet_agent_payload(osp)

    def get_sections_with_text(self, osp):
        return sections_with_text(osp)

    class Meta:
        model = OrganicSystemPlan
        fields = [
            "id",
            "public_id",
            "version_number",
            "status",
            "status_display",
            "effective_date",
            "submitted_at",
            "approved_at",
            "certifier_name",
            "packet_agent",
            "certifier_template_name",
            "section_completion",
            "sections_with_text",
            "created_at",
            "updated_at",
        ]


class _ApprovedNationalListInline(serializers.Serializer):
    """Compact read-only view of an approved NationalListSubstance on an OSP."""

    id = serializers.IntegerField()
    substance_name = serializers.CharField()
    cfr_section = serializers.CharField(required=False, allow_null=True)
    # "§ 205.601(e)", or "" for a nonsynthetic row. The client prints this, never a § built from
    # `cfr_section`, which for a nonsynthetic row is a catalogue code, not a section.
    citation = serializers.CharField(required=False, allow_blank=True, read_only=True)
    # False for a nonsynthetic row: the client must not file it under a "National List" heading.
    is_national_list_entry = serializers.BooleanField(read_only=True)
    status = serializers.CharField(required=False, allow_null=True)
    # A § 205.602 row the rule allows for one stated use: the client shows the condition instead of
    # "prohibited". `subsection` names the paragraph ("c") so the client can word it in Spanish.
    is_conditionally_permitted = serializers.BooleanField(read_only=True)
    subsection = serializers.CharField(required=False, allow_null=True, allow_blank=True, read_only=True)
    restriction_notes = serializers.CharField(required=False, allow_null=True, allow_blank=True, read_only=True)


class _ApprovedOMRIInline(serializers.Serializer):
    """Compact read-only view of an approved OMRIProduct on an OSP.

    `cdfa_oim_reg_number` was removed 2026-09-06: CDFA's published Registered OIM
    Products list carries no identifier (Firm | Product Name | Annotations), so every
    `CDFA-OIM-*` value in the column is invented. `is_cdfa_oim_registered` is the whole
    of what a client may render — "CDFA OIM registered", and nothing more.
    """

    id = serializers.IntegerField()
    product_name = serializers.CharField()
    # OMRI codes are real and deep-link to a live certificate — kept.
    omri_id = serializers.CharField(required=False, allow_null=True)
    manufacturer = serializers.CharField(required=False, allow_null=True)
    is_cdfa_oim_registered = serializers.BooleanField(required=False)
    # Emitted so the panel can mark a lapsed listing rather than rendering it as current.
    # A client that ignores this field shows a listing OMRI has withdrawn, which is why the
    # value travels with the row instead of being derived from a separate lookup.
    delisted_on = serializers.DateField(required=False, allow_null=True)


class _ApprovedWSDAInline(serializers.Serializer):
    """Compact read-only view of an approved WSDAMaterial on an OSP.

    `wsda_id` is sanitized on the way out: a real WSDA Product # is a bare integer, and
    the seeded `WSDA-REG-…` strings are Trazo inventions. Sanitizing here rather than in
    the client is deliberate — the OSP approved-inputs panel renders whatever arrives.
    """

    id = serializers.IntegerField()
    brand_name = serializers.CharField()
    wsda_id = serializers.SerializerMethodField()
    manufacturer = serializers.CharField(required=False, allow_null=True)
    category = serializers.CharField(required=False, allow_null=True)
    is_cdfa_oim_registered = serializers.BooleanField(required=False)

    def get_wsda_id(self, obj):
        raw = obj.get("wsda_id") if isinstance(obj, dict) else getattr(obj, "wsda_id", None)
        return wsda_product_number(raw) or None


class ApprovedInputChangeLogSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for ApprovedInputChangeLog rows.

    Exposed on OSP retrieve responses as approved_input_changes (newest-first,
    per model Meta ordering = ["-changed_at"]). Write access is intentionally
    not exposed — rows are created only by add/remove_approved_input actions.
    """

    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovedInputChangeLog
        fields = [
            "id",
            "kind",
            "target_name_at_change",
            "action",
            "changed_by_name",
            "changed_at",
            "change_notification_reference",
            "notes",
        ]
        read_only_fields = fields

    def get_changed_by_name(self, obj):
        """Return a display name for the user who made the change, or None."""
        user = obj.changed_by
        if user is None:
            return None
        full = (f"{user.first_name} {user.last_name}").strip()
        return full or getattr(user, "email", None) or str(user)


class OrganicSystemPlanSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    caller_scoped_fields = {"certification": "establishment__company"}
    establishment_scoped_fields = {"certification": "establishment_id"}

    """Full OSP serializer for dashboard CRUD."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    section_completion = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    # Sprint 5.1 — Read-only projections of the approved-inputs M2Ms. Writes
    # go through the add_approved_input / remove_approved_input viewset
    # actions, not via PATCH, to keep audit trails clean and validations
    # explicit.
    approved_national_list_substances = _ApprovedNationalListInline(many=True, read_only=True)
    approved_omri_products = _ApprovedOMRIInline(many=True, read_only=True)
    approved_wsda_materials = _ApprovedWSDAInline(many=True, read_only=True)

    # Sprint 5.1 GA — append-only change log. Nested read-only; writes happen
    # exclusively inside add/remove_approved_input viewset actions.
    approved_input_changes = ApprovedInputChangeLogSerializer(many=True, read_only=True)

    # P0-5 — registry ↔ narrative sync diff. Inspector signal: narrative mentions
    # inputs but registry has fewer structured entries, or registry entries don't
    # appear in the narrative. Frontend surfaces as a yellow warning banner.
    registry_sync_diff = serializers.SerializerMethodField()
    sections_with_text = serializers.SerializerMethodField()
    packet_agent = serializers.SerializerMethodField()

    def get_packet_agent(self, osp):
        return packet_agent_payload(osp)

    def validate_certifier_name(self, value):
        return (value or "").strip()

    def get_registry_sync_diff(self, osp):
        # Memoised per instance: `sections_with_text` reads the same diff.
        cache = self.__dict__.setdefault("_registry_sync_diffs", {})
        if osp.pk not in cache:
            cache[osp.pk] = registry_sync_diff(osp)
        return cache[osp.pk]

    def get_sections_with_text(self, osp):
        return sections_with_text(osp, diff=self.get_registry_sync_diff(osp))

    class Meta:
        model = OrganicSystemPlan
        fields = [
            "id",
            "public_id",
            "establishment",
            "certification",
            "version_number",
            "previous_version",
            "status",
            "status_display",
            "effective_date",
            "submitted_at",
            "approved_at",
            "sections",
            "module_responses",
            "pdf_document",
            "submission_pdf",
            "approval_document",
            "approval_certificate_number",
            "approval_certifier_name",
            "certifier_name",
            "packet_agent",
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            "approved_input_changes",
            "registry_sync_diff",
            "certifier_template_name",
            "certifier_template_url",
            "notes",
            "section_completion",
            "sections_with_text",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "establishment",
            "version_number",
            "previous_version",
            "submission_pdf",  # Set only by submit() action.
            "module_responses",  # Written only via the module PUT action (WS-2.2).
            # 🔴 2026-08-23 — `status` and `submitted_at` were ordinary writable fields, so
            # PATCH {"status": "submitted"} on a draft reached "submitted" through
            # perform_update (which only refuses edits to NON-drafts) and skipped everything
            # the submit action exists to do: the § 205.201(a) narrative floor, the module
            # recompile, and above all the frozen submission_pdf — "the exact artifact the
            # certifier receives", whose absence the submit docstring itself calls "a silent
            # gap the inspector can't detect". activate() then activated it. Found replaying
            # a pilot's renewal through the API: two "submitted" plans, no snapshot on either.
            # The UI only ever PATCHes `sections`. Status moves through submit / activate.
            "status",
            "submitted_at",
            "approved_at",
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            "approved_input_changes",
            "registry_sync_diff",
            "created_at",
            "updated_at",
        ]

    def validate_sections(self, value):
        """
        Enforce that every required § 205.201(a)(1)-(6) section key is present.
        Unknown keys are allowed (certifier-specific extensions) but required keys
        cannot be dropped — the frontend editor must always show all six.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError("sections must be a JSON object.")
        missing = [k for k in OSP_SECTION_KEYS if k not in value]
        if missing:
            raise serializers.ValidationError(f"Missing required OSP sections per 7 CFR 205.201(a): {missing}")
        return value


# Values that are obviously scratch input rather than a real answer. A length floor
# was rejected as the tool here: "No material changes." is a valid annual-update
# summary and would fail one, while "Test" would pass a short one. Match the
# failure mode instead — the same approach as the OFPP suspicious-filename check.
PLACEHOLDER_VALUES = {
    "test",
    "tests",
    "testing",
    "tbd",
    "todo",
    "n/a",
    "na",
    "none",
    "asdf",
    "qwerty",
    "xxx",
    "aaa",
    "foo",
    "bar",
    "sample",
    "placeholder",
    "prueba",
}


# Punctuation stripped from each word before matching. "/" is deliberately absent so
# "n/a" stays matchable.
_ENTRY_PUNCTUATION = ".,!?;:\"'()[]{}-–—_*"


def looks_like_placeholder(value) -> bool:
    """True when *every* word in the value is scratch input.

    Whole-string matching let "test test" through — the same failure this guard exists
    to stop, one space wider. Matching per word still clears "Latest soil test results",
    where only one word is a placeholder.
    """
    if not value:
        return False
    tokens = [token.strip(_ENTRY_PUNCTUATION).lower() for token in str(value).split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return False
    return all(token in PLACEHOLDER_VALUES for token in tokens)


def _quote_all(items) -> str:
    """Quote offending entries for a farmer-facing message.

    repr() was leaking Python's quoting conventions into a message a grower reads.
    """
    return ", ".join('"{}"'.format(item) for item in items)


class OSPAnnualUpdateSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    # § 205.406(a)(1) "supported by documentation": files on THIS farm's Documents shelf, named by
    # public id. Scoped at the field (not in `validate`), so another farm's or company's id fails
    # exactly like an id that does not exist and the refusal says nothing about which ids exist.
    caller_scoped_fields = {"supporting_document_ids": "establishment__company"}
    establishment_scoped_fields = {"supporting_document_ids": "establishment_id"}

    supporting_document_ids = serializers.SlugRelatedField(
        slug_field="public_id",
        many=True,
        queryset=GeneratedDocument.objects.all(),
        source="supporting_documents",
        required=False,
        write_only=True,
    )
    supporting_documents = serializers.SerializerMethodField()

    # Filing, signature and revision state are set by their own actions on the viewset
    # (sign, file, correct, withdraw), never by an edit. A payload that carries one of them is
    # refused rather than ignored: a client that thinks it filed something must hear that it
    # did not.
    ACTION_ONLY_FIELDS = (
        "submitted_at",
        "filing_method",
        "signed_at",
        "signed_by",
        "signer_name",
        "signer_title",
        "signed_content_sha256",
        "revision_number",
        "corrects",
        "superseded_at",
        "withdrawn_at",
        "withdrawal_reason",
        "snapshot_state",
        "filed_sha256",
        "filed_document",
        "new_osp",
    )

    def validate(self, attrs):
        sent = [name for name in self.ACTION_ONLY_FIELDS if name in (self.initial_data or {})]
        if sent:
            raise serializers.ValidationError(
                {
                    name: (
                        "Set by the sign, file, correct or withdraw actions, not by editing the update."
                        if name != "new_osp"
                        else "Linked by Trazo when the plan version this update produced is created."
                    )
                    for name in sent
                },
                code="action_only_field",
            )
        return self._validate_content(attrs)

    def validate_changes_summary(self, value):
        # 7 CFR 205.406 annual update goes to the certifier. "Test" reached a real
        # dossier and rendered verbatim into the regulatory filing (2026-08-03 review).
        if looks_like_placeholder(value):
            raise serializers.ValidationError(
                "Describe the actual changes for the reporting year, or state that there were none."
            )
        return value

    # Arbitrary keyboard noise ("TNe") is not matchable as a placeholder word, but an
    # additions/deletions entry is meant to DESCRIBE a change to the certifier, and
    # three characters cannot. Deliberately low so a real short entry ("Lime") passes.
    MIN_CHANGE_ENTRY_CHARS = 4

    def _clean_entry_list(self, value):
        """Reject entries that cannot describe a change to a certifier.

        The two failure modes are kept apart on purpose. A placeholder word and a
        three-character string need different instructions — "replace it" versus "write
        more" — and the single shared sentence this replaces gave neither. The field name
        is also gone from the text: DRF already keys the error under `additions` /
        `deletions`, so repeating it produced "additions: Additions contains entries...".
        """
        if not value:
            return value
        placeholders = []
        too_short = []
        for item in value:
            text = str(item).strip()
            if looks_like_placeholder(text):
                placeholders.append(text)
            elif len(text) < self.MIN_CHANGE_ENTRY_CHARS:
                too_short.append(text)
        problems = []
        if placeholders:
            problems.append(
                "Placeholder text, not a change: {}. Replace or delete {}.".format(
                    _quote_all(placeholders),
                    "that line" if len(placeholders) == 1 else "those lines",
                )
            )
        if too_short:
            problems.append(
                "Too short to describe a change: {}. Use at least {} characters, or delete {}.".format(
                    _quote_all(too_short),
                    self.MIN_CHANGE_ENTRY_CHARS,
                    "that line" if len(too_short) == 1 else "those lines",
                )
            )
        if problems:
            raise serializers.ValidationError(" ".join(problems))
        return value

    def validate_additions(self, value):
        return self._clean_entry_list(value)

    def validate_deletions(self, value):
        return self._clean_entry_list(value)

    # The plan VERSIONS this filing moved between, not just their row ids. A § 205.406 update
    # is the hinge between two versions of the plan — "the 2026 update took us from v1 to v3" is
    # the traceability an inspector follows, and `prior_osp: 59` cannot be read that way by
    # anyone. The viewset already select_relateds both, so this costs no query.
    prior_osp_version = serializers.IntegerField(source="prior_osp.version_number", read_only=True)
    # No `allow_null`: it is a validation kwarg and inert on a read-only field. DRF already
    # returns None when the source traversal hits a null relation, which is the normal case
    # here — a "no material changes" attestation creates no new version.
    new_osp_version = serializers.IntegerField(source="new_osp.version_number", read_only=True)

    class Meta:
        model = OSPAnnualUpdate
        fields = [
            "id",
            "public_id",
            "prior_osp",
            "prior_osp_version",
            "new_osp",
            "new_osp_version",
            "reporting_year",
            "revision_number",
            "corrects",
            "changes_summary",
            "additions",
            "deletions",
            "sections_unchanged_attestation",
            "application_info_changes",
            "agent_requested_info",
            "agent_requested_info_none",
            "sales_period_start",
            "sales_period_end",
            "correction_note",
            "supporting_document_ids",
            "supporting_documents",
            "filed_document",
            "signer_name",
            "signer_title",
            "signed_at",
            "signed_content_sha256",
            "submitted_at",
            "filing_method",
            "snapshot_state",
            "filed_sha256",
            "superseded_at",
            "withdrawn_at",
            "withdrawal_reason",
            "certifier_acknowledged_at",
            "is_locked",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "prior_osp_version",
            "new_osp",
            "new_osp_version",
            "revision_number",
            "corrects",
            "signer_name",
            "signer_title",
            "signed_at",
            "signed_content_sha256",
            "submitted_at",
            "filing_method",
            "snapshot_state",
            "filed_sha256",
            "filed_document",
            "superseded_at",
            "withdrawn_at",
            "withdrawal_reason",
            "certifier_acknowledged_at",
            "created_at",
            "updated_at",
        ]

    is_locked = serializers.BooleanField(read_only=True)

    # ModelSerializer writes a many field with `.set()`, which loses the attach order (see
    # OSPAnnualUpdate.replace_supporting_documents). Pop the list and write it in order.
    def create(self, validated_data):
        documents = validated_data.pop("supporting_documents", None)
        instance = super().create(validated_data)
        if documents is not None:
            instance.replace_supporting_documents(documents)
        return instance

    def update(self, instance, validated_data):
        documents = validated_data.pop("supporting_documents", None)
        instance = super().update(instance, validated_data)
        if documents is not None:
            instance.replace_supporting_documents(documents)
        return instance

    def get_supporting_documents(self, obj):
        """The files this revision names, in the order they were attached."""
        if obj.pk is None:
            return []
        return [
            {
                "id": link.document.pk,
                "public_id": str(link.document.public_id),
                "title": link.document.title,
                "source": link.document.source,
                "source_display": link.document.get_source_display(),
                "content_type": link.document.content_type,
                "created_at": link.document.created_at,
            }
            for link in obj.supporting_links.all()
        ]

    def validate_supporting_document_ids(self, value):
        # The field's queryset is already this farm's shelf; a caller off the nested route still
        # cannot name another farm's file, because the filing's own farm is checked in `validate`.
        seen, unique = set(), []
        for doc in value:
            if doc.pk not in seen:
                seen.add(doc.pk)
                unique.append(doc)
        return unique

    def _validate_content(self, attrs):
        """§ 205.406(a)(1) asks for the changes "to the previous plan" — the one on file.

        The card used to post whichever version the OSP screen was focused on, which defaults
        to the newest — the working DRAFT. The resulting row said "the changes to v4" against
        a plan the certifying agent has never seen, and it read correctly on screen the whole
        time. The client now picks the plan on file; this is the backstop for every other
        caller.

        Create only, and only when the operation HAS a non-draft version: an operation whose
        single plan has never left draft is not yet certified, § 205.406 does not bind it yet,
        and refusing the filing would leave it with no way to record one at all.
        """
        attrs = super().validate(attrs)
        prior = attrs.get("prior_osp")
        if self.instance is None and prior is not None and prior.status == "draft":
            has_filed_version = (
                OrganicSystemPlan.objects.filter(establishment_id=prior.establishment_id)
                .exclude(status="draft")
                .exists()
            )
            if has_filed_version:
                raise serializers.ValidationError(
                    {
                        "prior_osp": (
                            f"OSP v{prior.version_number} is a draft that has not been submitted. "
                            "An annual update continues the plan your certifier holds — file it "
                            "against that version; it will be linked to the draft it produces."
                        )
                    },
                    code="prior_osp_is_draft",
                )
        # The year a revision belongs to is fixed when it is created. Moving a draft to another
        # year would collide with that year's revisions at the database (a 500, review of back #79)
        # or detach a correction from the year it corrects. A draft in the wrong year is deleted
        # and started again.
        if self.instance is not None and "reporting_year" in attrs:
            if attrs["reporting_year"] != self.instance.reporting_year:
                raise serializers.ValidationError(
                    {
                        "reporting_year": (
                            "The year of an annual update cannot be changed. Delete this draft and start "
                            "the update for the other year."
                        )
                    },
                    code="reporting_year_fixed",
                )
        # A year has one chain of revisions. A second update for the same year would sit beside
        # the first rather than correct it, so it is refused; the correct action opens the next
        # revision instead. Withdrawn revisions do not count: a year whose filing was withdrawn
        # can be filed again, as the next revision number (perform_create).
        if self.instance is None and prior is not None and attrs.get("reporting_year") is not None:
            if OSPAnnualUpdate.objects.filter(
                establishment_id=prior.establishment_id,
                reporting_year=attrs["reporting_year"],
                withdrawn_at__isnull=True,
            ).exists():
                raise serializers.ValidationError(
                    {
                        "reporting_year": (
                            f"An annual update for {attrs['reporting_year']} already exists for this operation. "
                            "Edit it while it is a draft, or create a correction once it is signed or filed."
                        )
                    },
                    code="year_already_has_update",
                )
        self._validate_sales_period(attrs)
        docs = attrs.get("supporting_documents")
        if docs:
            establishment_id = prior.establishment_id if prior is not None else self.instance.establishment_id
            if any(doc.establishment_id != establishment_id for doc in docs):
                raise serializers.ValidationError(
                    {"supporting_document_ids": "Attach files from this farm's Documents only."},
                    code="supporting_document_other_farm",
                )
        return attrs

    def _validate_sales_period(self, attrs):
        """Both ends or neither, in order, at most a year long, and already over.

        The period is what the sales subtotal on 02 is drawn from. Half a period is no period, and a
        period still running would print a figure for sales that have not happened yet.
        """
        start = attrs.get("sales_period_start", getattr(self.instance, "sales_period_start", None))
        end = attrs.get("sales_period_end", getattr(self.instance, "sales_period_end", None))
        if start is None and end is None:
            return
        if start is None or end is None:
            raise serializers.ValidationError(
                {"sales_period_start" if start is None else "sales_period_end": "State both ends of the sales period."},
                code="sales_period_incomplete",
            )
        if end < start:
            raise serializers.ValidationError(
                {"sales_period_end": "The sales period ends before it starts."}, code="sales_period_order"
            )
        # Both ends are included (renewal_sales counts sale_date__gte=start, __lte=end), so a 12-month
        # period ends the day before its first anniversary: 2025-10-01 to 2026-09-30, and a leap year's
        # 366 days still count as one year. Compared by calendar, not by a day count (review of back #217).
        if end >= start + relativedelta(years=1):
            raise serializers.ValidationError(
                {"sales_period_end": "A sales period covers at most 12 months."}, code="sales_period_too_long"
            )
        if end > timezone.localdate():
            raise serializers.ValidationError(
                {"sales_period_end": "The sales period has to be over: it cannot end after today."},
                code="sales_period_not_over",
            )


class OSPChangeNotificationSerializer(serializers.ModelSerializer):
    """Notification-of-Changes record — 7 CFR 205.400(f) / NOP 2615 §3.4."""

    change_category_display = serializers.CharField(source="get_change_category_display", read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    documentation_timing_display = serializers.CharField(source="get_documentation_timing_display", read_only=True)
    cfr_reference = serializers.CharField(read_only=True)
    is_immediate = serializers.BooleanField(read_only=True)
    parcel_name = serializers.CharField(source="parcel.name", read_only=True, default=None)

    class Meta:
        model = OSPChangeNotification
        fields = [
            "id",
            "osp",
            "parcel",
            "parcel_name",
            "change_category",
            "change_category_display",
            "description",
            "date_notified",
            "method",
            "method_display",
            "documentation_timing",
            "documentation_timing_display",
            "supporting_document",
            "removal_reason",
            "certifier_acknowledged_at",
            "cfr_reference",
            "is_immediate",
            "created_at",
        ]
        read_only_fields = ["id", "osp", "created_at"]

    def validate_parcel(self, parcel):
        """A notice may only be attached to a parcel of the plan's own operation.

        The create path saves with `osp=` from the URL, so the establishment comes through the
        serializer context (`osp`) or the instance; without either there is nothing to check
        against and the FK is accepted as given.
        """
        if parcel is None:
            return parcel
        osp = self.context.get("osp") or getattr(self.instance, "osp", None)
        if osp is not None and parcel.establishment_id != osp.establishment_id:
            raise serializers.ValidationError("That parcel belongs to a different operation.")
        return parcel

    def validate_supporting_document(self, uploaded):
        """The same size and type gate as a DMS upload: this file ships in the packet ZIP."""
        if uploaded is None:
            return uploaded
        from documents.serializers import _validate_document_file

        return _validate_document_file(uploaded)

    def validate(self, attrs):
        """Run the model's date guard on the API path — DRF does not call Model.clean()."""
        merged = {
            **{f: getattr(self.instance, f, None) for f in ("change_category", "date_notified", "removal_reason")},
            **attrs,
        }
        date_notified = merged.get("date_notified")
        if date_notified and date_notified > timezone.localdate():
            raise serializers.ValidationError(
                {"date_notified": "The certifier cannot have been notified on a future date."}
            )
        # WSDA AGR 2516 asks why removed acreage left organic production. A new removal notice states
        # it; one recorded before the field existed keeps reading as "reason not recorded".
        if self.instance is None and merged.get("change_category") == OSPChangeNotification.CATEGORY_FIELD_REMOVAL:
            if not (merged.get("removal_reason") or "").strip():
                raise serializers.ValidationError(
                    {
                        "removal_reason": "Say why the acreage left organic production (for example, "
                        "transferred to another grower, or converted to conventional)."
                    }
                )
        if "removal_reason" in attrs:
            attrs["removal_reason"] = (attrs["removal_reason"] or "").strip()
        return attrs


class AdjoiningLandAffidavitSerializer(serializers.ModelSerializer):
    """USDA Adjoining Land Use Verification (form #25) — signed by the NEIGHBOUR.

    `materials_display` and `is_signed` are exposed read-only so a client renders the same
    three-state logic the certifier packet does, rather than re-deriving it and drifting.
    """

    materials_display = serializers.CharField(read_only=True)
    is_signed = serializers.BooleanField(read_only=True)

    class Meta:
        model = AdjoiningLandAffidavit
        fields = [
            "id",
            "public_id",
            "parcel",
            "neighbor_name",
            "neighbor_farm_name",
            "neighbor_address",
            "neighbor_phone",
            "border_side",
            "neighbor_is_certified_organic",
            "neighbor_certifier_name",
            "materials_used",
            "declares_no_materials",
            "not_used_on_adjoining_fields",
            "distance_to_organic_property_ft",
            "agrees_to_notify",
            "neighbor_signed_date",
            "signed_document",
            "notes",
            "materials_display",
            "is_signed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def validate_materials_used(self, value):
        """Reject anything but a list of known codes.

        An unknown code would render verbatim in the certifier packet (deliberately — a
        stored value is evidence of something), so the guard belongs at the write boundary
        rather than the render one.
        """
        if not isinstance(value, list):
            raise serializers.ValidationError("materials_used must be a list of codes.")
        unknown = [c for c in value if c not in AdjoiningLandAffidavit.MATERIAL_CHOICES]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown material code(s): {', '.join(map(str, unknown))}. "
                f"Valid: {', '.join(AdjoiningLandAffidavit.MATERIAL_CHOICES)}."
            )
        return value

    def validate(self, attrs):
        """ "None of the above" and a list of materials are contradictory answers."""
        declares_none = attrs.get("declares_no_materials")
        materials = attrs.get("materials_used")
        if declares_none is True and materials:
            raise serializers.ValidationError(
                {
                    "declares_no_materials": (
                        "The neighbour cannot declare 'none of the above' while also listing "
                        "materials. Clear one of the two."
                    )
                }
            )
        return attrs


class LandownerAffidavitSerializer(CallerScopedRelatedFields, serializers.ModelSerializer):
    caller_scoped_fields = {"osp": "establishment__company"}
    establishment_scoped_fields = {"osp": "establishment_id"}

    attestation_default = serializers.SerializerMethodField()
    # The form hint says "leave blank to use the standard wording". The model TextField has
    # default="" but no blank=True, so DRF's mapped field rejects an explicit "" with
    # "This field may not be blank" (a silent 400 for a farmer following the hint). Allow
    # blank here and fill the canonical MOFGA attestation in validate() so the stored/exported
    # attestation is never empty.
    attestation_text = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = LandownerAffidavit
        fields = [
            "id",
            "public_id",
            "parcel",
            "osp",
            "farm_name",
            "field_name",
            "field_acres",
            "previous_manager_name",
            "previous_manager_address",
            "previous_manager_phone",
            "landowner_name",
            "landowner_address",
            "landowner_phone",
            "yearly_history",
            # USDA Land Use History Verification form #2
            "no_materials_applied",
            "management_period_start",
            "management_period_end",
            "parcel_legal_description",
            "last_prohibited_date",
            "attestation_text",
            "attestation_default",
            "previous_manager_signed_date",
            "landowner_signed_date",
            "signed_document",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def get_attestation_default(self, obj):
        """
        Expose the canonical MOFGA attestation text as a read-only hint for the UI
        so the form can pre-fill while still allowing the operator to review/edit.
        """
        return LandownerAffidavit.ATTESTATION_TEXT

    def validate(self, attrs):
        """Blank attestation → the canonical MOFGA wording (honors the form's own hint).

        Only fills when attestation_text is actually being written (present in attrs). On a
        partial PATCH that omits the field entirely (e.g. editing just a phone number), we must
        NOT inject the default — that would overwrite a previously-saved custom attestation.
        On create, DRF applies the field default ("") so the key is present and gets filled.
        """
        if "attestation_text" in attrs and not (attrs.get("attestation_text") or "").strip():
            attrs["attestation_text"] = LandownerAffidavit.ATTESTATION_TEXT
        return attrs


class StateOrganicRegistrationSerializer(serializers.ModelSerializer):
    def validate_county(self, value):
        """CDFA registration is per-county and CalAgPermits validates on the county.

        Catching a bad county here beats discovering it at PUR-export time, where it
        surfaces as "County 'X' is not a recognized CA county" on a document already
        headed to the County Agricultural Commissioner.
        """
        if not value:
            return value
        from history.services.pur_export_service import _CA_COUNTY_CODES

        known = {name.strip().lower() for name in _CA_COUNTY_CODES}
        candidate = value.strip().lower().replace(" county", "")
        if candidate not in known:
            raise serializers.ValidationError(
                f"'{value}' is not a California county. CDFA registration is filed per county."
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        registration = attrs.get("registration_date") or getattr(self.instance, "registration_date", None)
        renewal = attrs.get("renewal_date") or getattr(self.instance, "renewal_date", None)
        # A renewal dated the same day as the registration carries no information and
        # makes is_current() meaningless — it was rendering that way on a live record.
        if registration and renewal and renewal <= registration:
            raise serializers.ValidationError({"renewal_date": "Renewal date must be after the registration date."})
        return attrs

    """Producer-dashboard CRUD for State Organic Program registration (CDFA SOP).

    Distinct from CDFA OIM (input-material) registration — this is the
    producer/operation registration CA wholesale (> $5,000 organic) operations
    must hold before their first organic sale (CA Food & Ag Code §§ 46000-46029).
    """

    operation_type_display = serializers.CharField(source="get_operation_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = StateOrganicRegistration
        fields = [
            "id",
            "public_id",
            "establishment",
            "state",
            "program_name",
            "operation_type",
            "operation_type_display",
            "status",
            "status_display",
            "registration_number",
            "county",
            "commodities",
            "prior_year_organic_gross_sales",
            "registration_date",
            "renewal_date",
            "registration_document",
            "notes",
            "is_current",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]


class CertifierAccessLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    # Which source file a `document` open was for, so the grower's activity log names it.
    document_title = serializers.CharField(source="document.title", read_only=True, default=None)

    class Meta:
        model = CertifierAccessLog
        fields = ["id", "action", "action_display", "accessed_at", "ip_address", "document_title"]
        read_only_fields = fields


class CertifierAccessLinkSerializer(serializers.ModelSerializer):
    """Farmer-facing view of a certifier review link.

    `token` is exposed to the OWNER only (this serializer is used behind the
    authenticated, company-scoped viewset) so the farmer can copy the URL to send
    their certifier. It is never rendered on any anonymous surface.
    """

    accesses = CertifierAccessLogSerializer(many=True, read_only=True)
    # Optional on input; create() falls back to the 90-day default.
    expires_at = serializers.DateTimeField(required=False)
    access_count = serializers.SerializerMethodField()
    last_accessed_at = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)

    class Meta:
        model = CertifierAccessLink
        fields = [
            "id",
            "token",
            "label",
            "audience",
            "certification_type",
            "period_start",
            "period_end",
            "include_source_files",
            "expires_at",
            "revoked_at",
            "created_at",
            "is_active",
            "is_expired",
            "is_revoked",
            "access_count",
            "last_accessed_at",
            "accesses",
        ]
        # establishment/token/created_by are set server-side in perform_create;
        # accepting them from the client would let a caller mint a link for
        # another operation or choose a guessable token.
        read_only_fields = [
            "id",
            "token",
            "revoked_at",
            "created_at",
            "is_active",
            "is_expired",
            "is_revoked",
            "access_count",
            "last_accessed_at",
            "accesses",
        ]

    # Both read the prefetched list rather than issuing a query per link.
    # `.count()` and `.first()` each bypass the prefetch cache (they add their own
    # COUNT / LIMIT), so on a farm with N links the list view fired 2N extra queries.
    def get_access_count(self, obj):
        return len(obj.accesses.all())

    def get_last_accessed_at(self, obj):
        accesses = list(obj.accesses.all())  # Meta.ordering = -accessed_at
        return accesses[0].accessed_at if accesses else None

    def validate_expires_at(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Expiry must be in the future.")
        return value

    def validate_certification_type(self, value):
        # Single source of truth: the export profiles the dossier builder actually
        # knows about. A hardcoded copy here would silently drift and let a farmer
        # mint a link whose profile falls back to "all" — a broader dossier than
        # they chose to share.
        from history.services.audit_export_service import AuditExportService

        valid = set(AuditExportService.CERTIFICATION_SECTIONS)
        if value not in valid:
            raise serializers.ValidationError(f"Invalid certification type. Choose from: {sorted(valid)}")
        return value

    def validate(self, attrs):
        # Source files are a certifier-dossier option. A buyer link serves the claim-safe consumer
        # payload only, and a file shelf holds invoices and prices (H-3, 2026-10-18).
        if attrs.get("include_source_files") and attrs.get("audience", "certifier") != "certifier":
            raise serializers.ValidationError(
                {"include_source_files": "Source files can only be shared with a certifier link."}
            )
        # The files a link opens are the ones its dossier lists; a profile without the document
        # index lists none (review of back #183).
        if attrs.get("include_source_files"):
            from history.services.audit_export_service import AuditExportService

            profile = attrs.get("certification_type") or "organic"
            if "attached_documents" not in AuditExportService.CERTIFICATION_SECTIONS.get(profile, []):
                raise serializers.ValidationError(
                    {
                        "include_source_files": f"The {profile} dossier lists no documents, so it cannot share their files."
                    }
                )
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("expires_at", CertifierAccessLink.default_expiry())
        return super().create(validated_data)
