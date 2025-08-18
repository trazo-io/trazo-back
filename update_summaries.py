#!/usr/bin/env python3
import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model

from history.models_consumer import UserImpactSummary
from history.views_consumer import ConsumerDashboardViewSet

User = get_user_model()

print("🔄 Updating impact summaries with real data...")

dashboard_view = ConsumerDashboardViewSet()
users_with_scans = User.objects.filter(historyscan__isnull=False).distinct()

for user in users_with_scans:
    print(f"📊 Updating impact summary for {user.email}")
    impact_summary, created = UserImpactSummary.objects.get_or_create(user=user)
    dashboard_view._update_impact_summary(user, impact_summary)

print("✅ All impact summaries updated with production-ready calculations!")
