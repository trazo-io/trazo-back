"""Seed the in-app FAQ content (``FarmerQuestionAnswer``).

This command used to seed ~2,300 lines of EducationCategory/EducationCourse/
EducationLesson rows as well. That catalogue was written pre-pivot — it taught
"maximum transparency scores", a 0-100 score, and the withdrawn blockchain
add-on — and NOTHING rendered it: the only education API the frontend calls is
the FAQ endpoint (``useGetFarmerQuestionsQuery``); the topic pages are i18n
strings bundled with the app. The course/lesson viewsets and serializers were
removed with it (2026-08-24). The models remain for their migrations; ``handle``
purges any rows an earlier deploy seeded, so the retired copy cannot be served
by a future surface that resurrects the models.
"""

from django.core.management.base import BaseCommand

from education.models import EducationCategory, EducationCourse, EducationLesson, FarmerQuestionAnswer


class Command(BaseCommand):
    help = "Seeds the farmer FAQ content and purges retired pre-pivot course/lesson rows"

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh",
            action="store_true",
            help=(
                "Rewrite FAQ rows that already exist. Without this the command is "
                "create-only, so a correction to the copy can never reach an "
                "environment that has been seeded once."
            ),
        )

    def handle(self, *args, **kwargs):
        self.refresh = kwargs.get("refresh", False)
        self.stdout.write(self.style.SUCCESS("Seeding FAQ content..."))

        # Purge the retired course/lesson catalogue wherever it was ever seeded.
        # Cascades cover lessons, progress rows, certificates and bookmarks.
        deleted_courses, _ = EducationCourse.objects.all().delete()
        deleted_lessons, _ = EducationLesson.objects.all().delete()
        deleted_categories, _ = EducationCategory.objects.all().delete()
        if deleted_courses or deleted_lessons or deleted_categories:
            self.stdout.write(
                self.style.WARNING(
                    f"Purged retired education content: {deleted_courses} course, "
                    f"{deleted_lessons} lesson, {deleted_categories} category rows (with cascades)."
                )
            )

        self.create_transparency_faqs()

        self.stdout.write(self.style.SUCCESS("Successfully seeded FAQ content!"))

    def create_transparency_faqs(self):
        """Create the farmer-facing FAQ entries."""
        faqs_data = [
            {
                "question": "What does a complete season record look like?",
                "answer": """A complete season covers seven kinds of records — the same map your certifier's reviewer works through:

**The Seven Categories:**
- Growing Practices: Planting, irrigation, harvest, pruning
- Treatments & Applications: Fertilizer, pest control, amendments
- Soil & Land Care: Soil preparation, composting, cover crops
- Pest Management: Scouting, traps, beneficial releases
- Business & Compliance: Certifications, audits, inspections
- Weather and General: Observations and everything else

**Photos are evidence, not decoration** — planting, harvest, and chemical applications are where an inspector most wants a photo behind the entry.

**Where to check yourself:** the readiness card on your farm home lists what is missing before your certifier asks. Buyers and shoppers never see any score — they see the documented practices themselves.""",
                "category": "records",
                "is_featured": True,
            },
            {
                "question": "Do I need special equipment to document transparency?",
                "answer": """No special equipment required! Trazo works with:

**Basic Level:** Just your smartphone for photos and event logging
**With location:** Smartphone GPS auto-fills the parcel and weather context

**Getting Started:** most farmers start with their phone and see their documentation completeness improve within the first week of logging events.""",
                "category": "setup",
                "is_featured": False,
            },
            {
                "question": "How do consumers actually use the transparency information?",
                "answer": """When someone scans your QR code, they see your records — not a rating:

**What Consumers See:**
- Documented practices: each activity in plain words, with its date
- Farming story: your farm description, in your words, labeled as yours
- Photo evidence: timestamped photos from the field
- Certifications: USDA Organic shows "Verified" only when it matches the USDA Organic Integrity Database; anything else is labeled "Self-Reported"
- Carbon data (secondary): available in an expandable section, never the headline

**What consumers do NOT see:** any score, grade, or rating. Practices are counted and shown; they are never graded.""",
                "category": "consumer_page",
                "is_featured": False,
            },
            # Logging activities — matches the LIVE "Add event → What did you do?"
            # verb-tile flow (WS-4). The old "Quick Add Event" feature name and the
            # backend 7-type taxonomy are retired from farmer-facing copy: farmers
            # pick a VERB; the seven record categories appear only as list filters.
            {
                "question": "How do I log an activity?",
                "answer": """From your parcel or the Activities page, press **Add event**. Three steps:

1. **What did you do?** Pick the activity tile — Planting, Input application, Irrigation, Field work, Pruning & canopy, Harvest, Equipment cleanout, Soil & amendments, Pest & scouting, Weather event, Certification & compliance, Transport, and more — and set the date
2. **Details** — the form asks only what that activity needs; templates and voice can pre-fill most of it
3. **Photos** — optional but powerful; add them for planting, harvest, and input applications especially

Most activities take under two minutes. Everything you log builds the same record your certifier reviews and your renewal packet assembles from.""",
                "category": "quick_add",
                "is_featured": True,
            },
            {
                "question": "Which activity type should I choose?",
                "answer": """Pick the tile that matches what happened in the field:

- **Input application** — any fertilizer, pesticide, fungicide, herbicide, or amendment you applied (product, rate, and area are captured here)
- **Planting / Harvest** — crop in, crop out; harvest also records quantity, destination, and buffer-row disposition
- **Irrigation** — water source, method, and duration
- **Soil & amendments** — soil tests, compost, cover crops
- **Pest & scouting** — monitoring walks, traps, beneficial releases
- **Equipment cleanout** — what was cleaned and how; this is your commingling-prevention record (7 CFR 205.272)
- **Certification & compliance** — certifications, inspections, audits, certifier correspondence. Sales are not logged here: a sale is a transaction against a finished lot, recorded in Sales Records on the production page
- **Weather event / Field work / Other activity** — context and everything else

**Quick decision:** applying something to the crop or soil? Input application. Working with the plants themselves? Planting or Harvest.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "Can I use voice or templates to log faster?",
                "answer": """Yes — both live inside the activity form:

- **Voice**: speak it the way you'd say it — "Applied 200 pounds of zinc sulfate on the north block" — and Trazo pre-fills 4-7 fields from your words. You review before saving
- **Templates**: crop-specific accelerators pre-fill typical values for common activities; you adjust the numbers to match the day

Whatever the entry method, you confirm every field — the record is yours.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How do I add photos to an activity?",
                "answer": """The photo step is the last step of every activity form — snap from your phone in the field or upload later.

**Where photos matter most:** planting, harvest, and input applications — those are the records where an inspector most wants visual evidence behind the entry. A product-label photo on an input application answers the "what exactly did you apply?" question before it is asked.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How does each activity build my season record?",
                "answer": """Each activity you log lands in the season file your certifier reviews:

**How Categories Work:**
- Growing Practices: Planting, irrigation, harvest, pruning events
- Treatments: Input applications — photos essential here
- Soil & Land Care: Soil management activities
- Pest Management: Scouting and control activities
- Business: Certifications and compliance
- Weather and General: Observations and everything else

**Key Tip:** Photos matter most on essential events — an input application with its label photo answers the inspector's question before it is asked.

**Weekly Goal for Success:**
- Log 5-7 activities per week for steady coverage
- Time required: Just 3-5 minutes daily total

**The payoff:** at renewal time, your OSP answers are backed by what you logged and the packet assembles from those records — and the readiness card shows any gaps while there is still time to close them.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How do I build my Organic System Plan in Trazo?",
                "answer": """Open **Organic System Plan** in the sidebar. Your OSP is a set of guided modules that follow the Common OSP structure — seeds, soil, pest management, harvest, storage, recordkeeping, and more.

**How it works:**
- Answer each module as a short questionnaire, in English or Spanish
- Where Trazo can suggest an answer from your season's records, it shows the suggestion **with the evidence named** — you confirm or edit it; nothing is ever auto-saved
- Topics that don't apply get an explicit Not Applicable attestation, so "skipped" never looks like "forgotten"
- Completed modules become PDFs, and the whole plan assembles into a renewal packet

You are the author of your plan — Trazo makes sure nothing is missing when your certifier asks.""",
                "category": "osp_renewal",
                "is_featured": True,
            },
            {
                "question": "What deadlines matter for renewal season?",
                "answer": """The window runs October to April, and the exact dates depend on your certifier — always confirm with them. Typical recent windows:

- **CCOF**: annual update opens early November, due January 1
- **OTCO (Oregon Tilth)**: January 1 or April 1, depending on scope
- **PCO**: January 15 - **OEFFA**: February 15 - **NOFA-NY**: February 28
- **WSDA** (most of Washington's organic tree fruit): **March 1** - **MOSA**: April 1
- **OCCSP cost-share**: applications historically due **December 31** at your county FSA office — reimburses a share of certification costs (verify current-year terms)

**The practical rule:** reconcile your records in the postharvest window, while the season is still fresh. Trazo's readiness card shows what is missing while there is still time to close the gaps.""",
                "category": "osp_renewal",
                "is_featured": True,
            },
            {
                "question": "What is the review list under my Organic System Plan?",
                "answer": """Your renewal starts from last year's plan, and most answers carry forward unchanged. The review list shows what your **dated records** did after each answer was written — ground you began managing, seasons started and closed, change notices filed, materials added, affidavits, incidents, parcels the plan never names, and modules not revisited in a year.

It is a list, **never a verdict**: it does not read your prose, it never says an answer is wrong, and it never blocks the Submit button — you may well have re-read a section and decided it still holds. It sits under your plan on screen, prints on the first page of your renewal packet, and on an active plan it runs all year as the running list of what next year's annual update will have to mention.""",
                "category": "osp_renewal",
                "is_featured": True,
            },
            {
                "question": "I'm coming from COG Pro — how do I move my records?",
                "answer": """COG Pro has announced it will end service December 31, 2026. Your organic records must stay retrievable for **5 years** (7 CFR 205.103(b)(3)), so export everything before the shutdown — field lists, input applications, harvest logs, and sales records, covering the full retention window.

Trazo imports COG Pro CSV exports **white-glove**: send us the export and your records arrive as structured activities, linked to your parcels. Their Field maps to a Trazo parcel; Row/Section identifiers land on each activity's block ID.""",
                "category": "records",
                "is_featured": False,
            },
            {
                "question": "How does my certifier see my records?",
                "answer": """Two ways, and you control both:

- **The renewal packet** — the § 205.406 annual update, your change notices, module PDFs, per-parcel applications, workbooks, and the audit PDF, generated on demand and filed in your Documents. Receipts you link to purchase records travel inside the packet, so the inspector sees the paper behind the invoice number without asking you for it
- **A live review link** — a read-only page you can share that opens your current records in the browser: activity log, inputs with National List cross-references, and documents. No account needed on their side, and it always shows the records as they stand today

Trazo never sends anything to your certifier on its own — sharing is always your action.""",
                "category": "records",
                "is_featured": False,
            },
            {
                "question": "Can a buyer see my records before harvest?",
                "answer": """Yes — and this matters because wholesale deals often close **before** harvest: a buyer deciding mid-season wants to see records now, while your public page only exists once you finish and publish. Without publishing anything, on the Compliance plan, the **Share with a buyer** card on your Buyer Page mints a private review link: a read-only page listing your seasons, including the one still in progress, where each season opens exactly what a shopper would see on your public page — same information policy, nothing extra.

It is a link you send to one buyer, not a public page:

- You can **revoke it at any time**, and it expires on its own after 90 days
- Every open is **logged**, so you can see whether they actually looked
- A buyer's visit is never counted as a QR scan

Certifier review links are separate and show a certifier-grade dossier; one kind of link never opens the other's view.""",
                "category": "consumer_page",
                "is_featured": False,
            },
            {
                "question": "Why don't some of my records appear on the buyer page?",
                "answer": """Four record categories are withheld from every public and buyer view, for every farm on Trazo: **buffer-zone harvest dispositions**, the **seed commercial-availability search**, **equipment cleanout/purge records**, and **transport/handler records**.

They are evidence of *correct* practice — but they read as their own opposite to a reader without the regulation open. "None could supply certified organic seed" is the § 205.204(a)(1) allowance working exactly as designed; to a shopper or a produce buyer it reads as "not fully organic." Transport records also name your handler, which is your supply chain — commercial information a buyer counterparty should not get by default.

Three things to know:

- This is a **uniform policy**, not a per-farm setting — no farm can hide more or show more, which is why a buyer can take any Trazo page at face value
- These records are **not hidden from the people they persuade**: they stay in your certifier packet and audit dossier, where the reader can weigh them
- Trazo tells you **as you log** which records a buyer will and will not see, so nothing about the policy is a surprise

If a buyer genuinely needs certifier-grade depth, that is a different act: answer their documentation request from your Buyer Page inbox, or share the packet yourself. Deeper access is always your explicit decision, never a wider default.""",
                "category": "consumer_page",
                "is_featured": False,
            },
            {
                "question": "Can I attach a purchase receipt to a record?",
                "answer": """Yes. Chemical and soil-amendment purchase records have a **receipt field**: upload the receipt or invoice in **Documents** first, then pick it from the record's receipt selector.

Why it matters: an inspector's first move on a materials question is "show me the receipt behind this invoice number." A linked receipt travels **inside your renewal packet** (a receipts folder with the actual files), and the audit tables mark the purchase row "receipt on file" — so the paper and the record arrive together instead of you couriering between them.""",
                "category": "records",
                "is_featured": False,
            },
            {
                "question": "Can I export all my records?",
                "answer": """Yes, on every plan including the free one — one click, no gate. The **Export all records** button in Documents downloads a ZIP of plain CSV files: every activity record with all its fields, your productions, parcels, sales records, and photo references.

Your records are your records: 7 CFR 205.103 makes you keep them for **five years**, and they should never be trapped in any tool, including this one. The certifier-ready packet and audit exports are a paid feature; the raw data never is.""",
                "category": "records",
                "is_featured": False,
            },
            {
                "question": "How do I log the same activity again quickly?",
                "answer": """Open the existing record and use **Log this again**. It opens the activity form pre-filled with your own previous entry — product, rates, method — with the date reset to today and photos not copied. Adjust what changed and save.

A spray program that repeats eight times a season becomes one careful entry plus seven quick confirmations. The pre-fill comes from **your own record**, never from a template, so every saved activity is still your entry with your date.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "My season is finished — can I still log post-harvest work?",
                "answer": """Yes. When a parcel has no season in progress, the add-activity page offers two doors: **start the next production**, or **log this against the finished season** as post-harvest work.

October cover crop, shipping from storage, equipment cleanup after the last pick — these belong to the season they close out, and the record keeps its own date even though it lands after the finish date. Your certifier reads them exactly that way.""",
                "category": "quick_add",
                "is_featured": False,
            },
        ]

        # Questions renamed over time: get_or_create keys on question text, so the
        # old rows must be removed or the FAQ list serves both generations forever.
        LEGACY_QUESTIONS = [
            "How does transparency scoring actually work?",
            "How does Quick Add affect my transparency score?",
            # 2026-08-09: "Quick Add Event" feature name retired (WS-7); questions
            # re-authored around the live verb-tile flow.
            "What is Quick Add Event and how does it work?",
            "Which event type should I choose in Quick Add?",
            "How do I add photos in Quick Add?",
            "Can I use voice to create events in Quick Add?",
            "What are smart defaults in Quick Add?",
            "How does Quick Add build my season record?",
        ]
        FarmerQuestionAnswer.objects.filter(question__in=LEGACY_QUESTIONS).delete()

        for faq_data in faqs_data:
            faq, created = FarmerQuestionAnswer.objects.get_or_create(question=faq_data["question"], defaults=faq_data)
            if not created and getattr(self, "refresh", False):
                for field, value in faq_data.items():
                    setattr(faq, field, value)
                faq.save()
            if created:
                self.stdout.write(f"Created FAQ: {faq.question[:50]}...")
