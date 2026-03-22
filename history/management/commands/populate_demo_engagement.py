"""
Populate realistic consumer engagement data for demo productions.

Usage:
    poetry run python manage.py populate_demo_engagement oscar+demo@trazo.io
    poetry run python manage.py populate_demo_engagement oscar+demo@trazo.io --reset

Creates for each finished production:
    ~45-55 QR scans spread over last 30 days
    5-8 reviews with realistic ratings and text
    10 consumer users with @demo.trazo.io emails
    Updated production metrics (public_views, unique_visitors, reputation)
    UserImpactSummary per consumer
"""

import hashlib
import random
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from history.models import History, HistoryScan
from history.models_consumer import UserImpactSummary
from notifications.models import Notification
from notifications.services import notification_service
from reviews.models import Review
from users.constants import CONSUMER
from users.models import User

DEMO_CONSUMER_DOMAIN = "@demo.trazo.io"

DEMO_CONSUMERS = [
    ("Sarah", "Mitchell", "sarah.m@demo.trazo.io", None),
    ("Carlos", "Rivera", "carlos.r@demo.trazo.io", "google"),
    ("Jennifer", "Park", "jennifer.p@demo.trazo.io", None),
    ("Michael", "Thompson", "michael.t@demo.trazo.io", "google"),
    ("Emily", "Nakamura", "emily.n@demo.trazo.io", "apple"),
    ("David", "Okafor", "david.o@demo.trazo.io", None),
    ("Amanda", "Chen", "amanda.c@demo.trazo.io", "google"),
    ("Marcus", "Williams", "marcus.w@demo.trazo.io", None),
    ("Rachel", "Goldstein", "rachel.g@demo.trazo.io", None),
    ("Tyler", "Santos", "tyler.s@demo.trazo.io", None),
]

QUICK_COMMENTS = [
    "Love the transparency! Great to see where my food comes from.",
    "Impressive farming practices. Will buy again.",
    "The blockchain verification gives me confidence.",
    "So cool to see every step of the production!",
    "This is exactly the kind of transparency I want from food producers.",
    "Shared this with my family - they were amazed at the detail.",
    "Great quality product, love the transparency score.",
    "First time scanning a QR code on produce - very informative!",
    "The IPM approach is impressive. Supporting sustainable farming!",
    "Really appreciate the detailed farming events.",
    "Bought this at Whole Foods, the QR code was a pleasant surprise.",
    "More farms should be this transparent about their practices.",
    "Beautiful farm, beautiful product. Keep it up!",
    "Verified on blockchain - that's next level food traceability.",
    "My kids loved learning about how their food was grown.",
    "As a chef, I appreciate knowing exactly where ingredients come from.",
    "The transparency score sold me. 95% is incredible.",
    "Ventura County produce is the best. Thanks for being transparent!",
    "Finally, a company that shows the full picture.",
    "Subscribed to follow this farm's future productions!",
]

AVOCADO_REVIEWS = [
    {
        "headline": "Best avocados I've found in California",
        "written_review": (
            "I bought these at the farmers market after scanning the QR code. "
            "The transparency is incredible - I can see every single farming "
            "event from soil testing to harvest. The IPM approach with "
            "beneficial insects instead of harsh chemicals really sold me. "
            "The avocados themselves are perfectly creamy with amazing flavor."
        ),
        "rating": 5,
    },
    {
        "headline": "Impressed by the farming transparency",
        "written_review": (
            "As someone who cares about sustainable agriculture, this is "
            "exactly what I've been looking for. Being able to see 13 "
            "documented farming events gives me confidence in what I'm "
            "buying. The blockchain verification is the cherry on top. "
            "Will definitely be a repeat customer."
        ),
        "rating": 5,
    },
    {
        "headline": "Great product, love the QR code experience",
        "written_review": (
            "Scanned the QR code on a whim and was blown away by the level "
            "of detail. I can see soil test results, irrigation records, and "
            "even the pest management approach. The avocados taste great and "
            "I feel good about where they come from."
        ),
        "rating": 4,
    },
    {
        "headline": "Good avocados with excellent traceability",
        "written_review": (
            "The avocados are consistently good quality. What sets them apart "
            "is the complete production history available through the QR code. "
            "I can see they use cover crops and beneficial insects. "
            "Wish more producers would be this open about their practices."
        ),
        "rating": 4,
    },
    {
        "headline": "Solid quality, interesting transparency approach",
        "written_review": (
            "Good avocados, about what you'd expect from Ventura County. "
            "The transparency platform is interesting - it's nice to see "
            "the farming details though some of the technical information "
            "could be more consumer-friendly. The transparency score makes "
            "it easy to understand at a glance."
        ),
        "rating": 3,
    },
]

ORANGE_REVIEWS = [
    {
        "headline": "The juiciest oranges with full transparency",
        "written_review": (
            "These Valencia oranges are incredible - sweet, juicy, and I can "
            "trace every step of production. The fact that they release "
            "parasitic wasps instead of using harsh pesticides shows real "
            "commitment to sustainable farming. The composted citrus pulp "
            "recycling is a nice touch too."
        ),
        "rating": 5,
    },
    {
        "headline": "Supporting local farming done right",
        "written_review": (
            "Bought a bag of these at the local grocery store and was "
            "impressed by the QR code experience. 15 documented events! "
            "The biological pest control with Aphytis wasps is fascinating. "
            "Great to support a local Ventura County farm that's doing "
            "things the right way."
        ),
        "rating": 5,
    },
    {
        "headline": "Perfect for fresh juice, amazing transparency",
        "written_review": (
            "We go through a lot of oranges for juicing and these are "
            "consistently great. What I love is being able to see the full "
            "production journey - from soil tests to harvest. The blockchain "
            "verification gives me confidence that the transparency claims "
            "are real and not just marketing."
        ),
        "rating": 4,
    },
    {
        "headline": "Family-friendly farm transparency",
        "written_review": (
            "My daughter loves looking at the farming events when we scan "
            "the QR code. It's become a fun educational moment at the "
            "grocery store. The oranges are sweet with great juice content. "
            "The detailed pest management records are particularly "
            "interesting to follow."
        ),
        "rating": 4,
    },
    {
        "headline": "Good oranges, nice to see the full picture",
        "written_review": (
            "Decent Valencia oranges. The transparency platform is well "
            "done - you can see everything from weather events to equipment "
            "maintenance. The Santa Ana wind damage documentation shows "
            "they're being honest about challenges too, not just the good "
            "stuff. That builds trust."
        ),
        "rating": 3,
    },
]

GENERIC_REVIEWS = [
    {
        "headline": "Food transparency the way it should be",
        "written_review": (
            "This is the future of food traceability. Being able to scan a "
            "QR code and see exactly how your food was grown, verified on "
            "blockchain, is incredible. Every farm should be using something "
            "like this. The transparency score makes it easy to compare and "
            "choose products."
        ),
        "rating": 5,
    },
    {
        "headline": "Shared with friends, they love it too",
        "written_review": (
            "I've been telling everyone about this. The QR code experience "
            "is so well designed - you immediately see the transparency "
            "score and can dive deeper into the farming details. My friends "
            "who are into sustainable food have all started looking for "
            "these QR codes at the store."
        ),
        "rating": 4,
    },
    {
        "headline": "Great concept, well executed",
        "written_review": (
            "As a tech person, I appreciate the thoughtful implementation. "
            "The progressive disclosure design works well - transparency "
            "score first, then farming events, then detailed carbon data "
            "for those who want it. Makes sustainability accessible to "
            "everyone, not just experts."
        ),
        "rating": 4,
    },
]

US_REGIONS = [
    ("California", 70),
    ("Arizona", 8),
    ("Oregon", 6),
    ("Nevada", 5),
    ("Texas", 5),
    ("New York", 3),
    ("Washington", 3),
]


class Command(BaseCommand):
    help = "Populate realistic consumer engagement data for demo productions"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Email of the producer user")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing engagement data and recreate",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)

        email = options["email"]
        reset = options["reset"]

        # 1. Look up user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' not found.")

        self.stdout.write(f"User: {user.get_full_name()} ({email})")

        # 2. Find finished productions for this user
        finished_productions = list(
            History.objects.filter(
                operator=user,
                finish_date__isnull=False,
                published=True,
            ).order_by("id")
        )

        if not finished_productions:
            raise CommandError(f"No finished productions found for user '{email}'. " f"Run create_demo_user first.")

        self.stdout.write(f"Found {len(finished_productions)} finished production(s):")
        for prod in finished_productions:
            self.stdout.write(f"  #{prod.id} - {prod.name}")

        # 3. Idempotency check
        existing_scans = HistoryScan.objects.filter(history__in=finished_productions).exists()

        if existing_scans and not reset:
            self.stdout.write(
                self.style.WARNING("Engagement data already exists for these productions. " "Use --reset to recreate.")
            )
            return

        if existing_scans and reset:
            self._reset_engagement(finished_productions)

        # 4. Create consumer users
        consumers = self._create_consumers()

        # 5. For each production, create scans and reviews
        total_scans = 0
        total_reviews = 0

        for prod in finished_productions:
            product_name = prod.product.name.lower() if prod.product else ""
            scans_created = self._create_scans(prod, consumers)
            reviews_created = self._create_reviews(prod, consumers, product_name)
            self._update_production_metrics(prod)

            total_scans += scans_created
            total_reviews += reviews_created

            self.stdout.write(
                f"  #{prod.id}: {scans_created} scans, "
                f"{reviews_created} reviews, "
                f"reputation={prod.reputation:.1f}"
            )

        # 6. Create notifications for recent scans (last ~5 per production)
        total_notifications = self._create_notifications(user, finished_productions, consumers)

        # 7. Create UserImpactSummary per consumer
        self._create_impact_summaries(consumers, finished_productions)

        # 8. Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Engagement data created!"))
        self.stdout.write("")
        self.stdout.write(f"  Consumers created: {len(consumers)}")
        self.stdout.write(f"  Total scans:       {total_scans}")
        self.stdout.write(f"  Total reviews:     {total_reviews}")
        self.stdout.write(f"  Notifications:     {total_notifications}")
        self.stdout.write("")
        for prod in finished_productions:
            self.stdout.write(
                f"  /production/{prod.id}  "
                f"({prod.name}) - "
                f"{prod.public_views} views, "
                f"{prod.unique_visitors} visitors, "
                f"rep={prod.reputation:.1f}"
            )

    def _reset_engagement(self, productions):
        """Delete all engagement data for these productions."""
        self.stdout.write("Deleting existing engagement data...")

        # Delete reviews first (FK to scans)
        review_count = Review.objects.filter(production__in=productions).delete()[0]
        self.stdout.write(f"  Deleted {review_count} reviews")

        # Delete scans
        scan_count = HistoryScan.objects.filter(history__in=productions).delete()[0]
        self.stdout.write(f"  Deleted {scan_count} scans")

        # Delete notifications for this user from demo consumers
        notif_count = Notification.objects.filter(
            recipient__email=productions[0].operator.email,
            type__in=["product_scan", "product_review"],
        ).delete()[0]
        self.stdout.write(f"  Deleted {notif_count} notifications")

        # Delete demo consumer users and their impact summaries
        demo_users = User.objects.filter(email__endswith=DEMO_CONSUMER_DOMAIN)
        impact_count = UserImpactSummary.objects.filter(user__in=demo_users).delete()[0]
        user_count = demo_users.delete()[0]
        self.stdout.write(f"  Deleted {user_count} consumer users, " f"{impact_count} impact summaries")

        # Reset production metrics
        for prod in productions:
            prod.public_views = 0
            prod.unique_visitors = 0
            prod.reputation = 0
            prod.save(update_fields=["public_views", "unique_visitors", "reputation"])

        self.stdout.write(self.style.SUCCESS("  Reset complete."))

    def _create_consumers(self):
        """Create 10 demo consumer users."""
        consumers = []
        for first, last, email, provider in DEMO_CONSUMERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "user_type": CONSUMER,
                    "is_active": False,
                    "social_auth_provider": provider,
                },
            )
            consumers.append(user)

        self.stdout.write(f"  Consumers: {len(consumers)} ready")
        return consumers

    def _create_scans(self, production, consumers):
        """Create 45-55 scans spread over last 30 days."""
        now = datetime.now(tz=dt_tz.utc)
        total_count = random.randint(45, 55)

        # Build day weights: last 30 days with weekend boost
        days = []
        weights = []
        for i in range(30):
            day = now - timedelta(days=29 - i)
            days.append(day.date())
            weekday = day.weekday()
            # Base weight
            w = 1.0
            # Weekend boost
            if weekday in (5, 6):
                w *= 1.4
            # Random spike days (2-3 days)
            if random.random() < 0.1:
                w *= 2.0
            # Random quiet days
            if random.random() < 0.08:
                w *= 0.3
            weights.append(w)

        scan_dates = random.choices(days, weights=weights, k=total_count)

        # Region distribution
        region_names = [r[0] for r in US_REGIONS]
        region_weights = [r[1] for r in US_REGIONS]

        # Create all scans
        scan_objects = []
        session_hashes = set()
        created_count = 0

        for scan_date in scan_dates:
            # Time-of-day: bimodal lunch + evening
            if random.random() < 0.6:
                hour = random.randint(11, 14)
            else:
                hour = random.randint(18, 20)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)

            actual_dt = datetime(
                scan_date.year,
                scan_date.month,
                scan_date.day,
                hour,
                minute,
                second,
                tzinfo=dt_tz.utc,
            )

            # Scan type distribution
            r = random.random()
            if r < 0.70:
                scan_type = "qr"
            elif r < 0.90:
                scan_type = "feedback"
            else:
                scan_type = "review"

            # Referrer type
            r = random.random()
            if r < 0.60:
                referrer_type = "qr"
            elif r < 0.80:
                referrer_type = "direct"
            elif r < 0.95:
                referrer_type = "social"
            else:
                referrer_type = "search"

            # User: 60% authenticated, 40% anonymous
            scan_user = None
            if random.random() < 0.60:
                scan_user = random.choice(consumers)

            # Session hash
            session_seed = f"{production.id}-{actual_dt.isoformat()}-{random.randint(0, 99999)}"
            session_hash = hashlib.sha256(session_seed.encode()).hexdigest()[:16]
            session_hashes.add(session_hash)

            # IP hash
            ip_seed = f"ip-{random.randint(1, 200)}-{scan_date}"
            ip_hash = hashlib.sha256(ip_seed.encode()).hexdigest()[:16]

            # Engagement score: beta distribution skewing low
            engagement_score = round(random.betavariate(1.5, 5.0) * 0.8, 3)

            # Country
            r = random.random()
            if r < 0.95:
                country_code = "US"
            elif r < 0.98:
                country_code = "MX"
            else:
                country_code = "CA"

            # Region
            region = random.choices(region_names, region_weights, k=1)[0]

            # Bot score
            r = random.random()
            if r < 0.90:
                bot_score = round(random.uniform(0.0, 0.02), 3)
            elif r < 0.98:
                bot_score = round(random.uniform(0.05, 0.15), 3)
            else:
                bot_score = round(random.uniform(0.3, 0.6), 3)

            # Duplicate
            is_duplicate = random.random() < 0.10

            # Consent
            consent_given = random.random() < 0.85

            # Comment (~15% of scans)
            comment = None
            if random.random() < 0.15:
                comment = random.choice(QUICK_COMMENTS)

            scan = HistoryScan.objects.create(
                history=production,
                user=scan_user,
                comment=comment,
                scan_type=scan_type,
                referrer_type=referrer_type,
                engagement_score=engagement_score,
                bot_score=bot_score,
                ip_hash=ip_hash,
                session_hash=session_hash,
                country_code=country_code,
                region=region,
                is_duplicate=is_duplicate,
                consent_given=consent_given,
                is_verified_human=bot_score < 0.1,
            )

            # Override auto_now_add date
            HistoryScan.objects.filter(id=scan.id).update(date=actual_dt)

            scan_objects.append(scan)
            created_count += 1

        # Link some duplicates to earlier scans
        for scan in scan_objects:
            if scan.is_duplicate and len(scan_objects) > 1:
                earlier = [s for s in scan_objects if s.id < scan.id and not s.is_duplicate]
                if earlier:
                    HistoryScan.objects.filter(id=scan.id).update(original_scan=random.choice(earlier))

        return created_count

    def _create_reviews(self, production, consumers, product_name):
        """Create 5-8 reviews for a production."""
        # Pick review templates based on product
        if "avocado" in product_name:
            templates = list(AVOCADO_REVIEWS)
        elif "orange" in product_name:
            templates = list(ORANGE_REVIEWS)
        else:
            templates = list(GENERIC_REVIEWS)

        # Add 1-3 generic reviews
        extra_generics = random.sample(
            GENERIC_REVIEWS,
            k=min(random.randint(1, 3), len(GENERIC_REVIEWS)),
        )
        templates.extend(extra_generics)

        # Shuffle and limit to 5-8
        random.shuffle(templates)
        review_count = min(random.randint(5, 8), len(templates))
        templates = templates[:review_count]

        # Pick distinct consumers for reviews
        available_consumers = list(consumers)
        random.shuffle(available_consumers)
        review_consumers = available_consumers[:review_count]

        created = 0
        for i, template in enumerate(templates):
            consumer = review_consumers[i]

            # Create a linked scan (scan_type="review")
            scan = HistoryScan.objects.create(
                history=production,
                user=consumer,
                scan_type="review",
                referrer_type="qr",
                engagement_score=round(random.uniform(0.4, 0.8), 3),
                bot_score=0.0,
                session_hash=hashlib.sha256(f"review-{production.id}-{consumer.id}".encode()).hexdigest()[:16],
                country_code="US",
                region="California",
                consent_given=True,
                is_verified_human=True,
            )

            # Override scan date to somewhere in last 30 days
            now = datetime.now(tz=dt_tz.utc)
            review_date = now - timedelta(
                days=random.randint(1, 28),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            HistoryScan.objects.filter(id=scan.id).update(date=review_date)

            # Create the review
            review = Review.objects.create(
                headline=template["headline"],
                written_review=template["written_review"],
                rating=template["rating"],
                user=consumer,
                production=production,
                scan=scan,
                images=[],
            )

            # Override auto_now_add date
            Review.objects.filter(id=review.id).update(date=review_date)

            created += 1

        return created

    def _update_production_metrics(self, production):
        """Update public_views, unique_visitors, reputation."""
        scans = HistoryScan.objects.filter(history=production)

        # public_views = non-duplicate, non-bot scans
        production.public_views = scans.filter(
            is_duplicate=False,
            bot_score__lt=0.3,
        ).count()

        # unique_visitors = distinct session hashes
        production.unique_visitors = scans.exclude(session_hash="").values("session_hash").distinct().count()

        production.save(update_fields=["public_views", "unique_visitors"])

        # update_reputation() recalculates from reviews
        production.update_reputation()

    def _create_impact_summaries(self, consumers, productions):
        """Create UserImpactSummary for each consumer who has scans."""
        for consumer in consumers:
            scan_count = HistoryScan.objects.filter(
                user=consumer,
                history__in=productions,
            ).count()

            if scan_count == 0:
                continue

            review_count = Review.objects.filter(
                user=consumer,
                production__in=productions,
            ).count()

            first_scan = (
                HistoryScan.objects.filter(
                    user=consumer,
                    history__in=productions,
                )
                .order_by("date")
                .values_list("date", flat=True)
                .first()
            )

            last_scan = (
                HistoryScan.objects.filter(
                    user=consumer,
                    history__in=productions,
                )
                .order_by("-date")
                .values_list("date", flat=True)
                .first()
            )

            achievements = []
            if scan_count >= 1:
                achievements.append("first_scan")
            if scan_count >= 5:
                achievements.append("frequent_scanner")
            if review_count >= 1:
                achievements.append("first_review")

            summary, _ = UserImpactSummary.objects.update_or_create(
                user=consumer,
                defaults={
                    "total_scans": scan_count,
                    "total_reviews": review_count,
                    "first_scan_date": first_scan,
                    "last_scan_date": last_scan,
                    "achievements_earned": achievements,
                    "sustainable_farms_found": 1,
                    "local_farms_found": 1,
                    "better_choices_made": scan_count,
                    "points_earned": scan_count * 10 + review_count * 50,
                    "current_level": 1 + (scan_count // 5),
                },
            )

    def _create_notifications(self, owner, productions, consumers):
        """Create scan notifications for the most recent scans per production."""
        total = 0
        for prod in productions:
            product_name = prod.product.name if prod.product else f"Production {prod.id}"
            establishment_id = prod.parcel.establishment.id if prod.parcel and prod.parcel.establishment else None
            product_id = prod.product.id if prod.product else None
            parcel_id = prod.parcel.id if prod.parcel else None

            # Get last 5 scans with a user (so we have a scanner name)
            recent_scans = (
                HistoryScan.objects.filter(history=prod, user__isnull=False)
                .select_related("user")
                .order_by("-date")[:5]
            )

            for scan in recent_scans:
                region = scan.region or "California"
                country = "US" if scan.country_code == "US" else scan.country_code
                location = f"{region}, {country}" if region else None

                notification_service.create_product_scan_notification(
                    product_owner=owner,
                    scanner=scan.user,
                    product_name=product_name,
                    scan_location=location,
                    production_id=prod.id,
                    establishment_id=establishment_id,
                    product_id=product_id,
                    parcel_id=parcel_id,
                )
                total += 1

        self.stdout.write(f"  Notifications: {total} created")
        return total
