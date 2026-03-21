import logging
import threading

from django.db import connections, transaction

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet

from .models import Certification
from .serializers import CertificationSerializer

logger = logging.getLogger(__name__)


class CertificationViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """CRUD + manual verification for establishment certifications."""

    serializer_class = CertificationSerializer

    def get_queryset(self):
        return Certification.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).select_related("establishment")

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return super().get_permissions()
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        certification = serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user,
        )
        self._trigger_background_verification(certification)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"])
    def verify(self, request, **kwargs):
        """Manually trigger re-verification."""
        certification = self.get_object()
        self._trigger_background_verification(certification)
        return Response(
            {"status": "verification_initiated", "certification_id": certification.id},
            status=status.HTTP_202_ACCEPTED,
        )

    def _trigger_background_verification(self, certification):
        """Trigger verification in background thread (MVP pattern)."""

        def _bg_verify(cert_id):
            try:
                connections.close_all()
                from .services.verification_manager import VerificationManager

                cert = Certification.objects.get(id=cert_id)
                manager = VerificationManager()
                manager.verify_certification(cert)
            except Exception as e:
                logger.error(f"Background verification failed for cert {cert_id}: {e}")
            finally:
                connections.close_all()

        transaction.on_commit(
            lambda: threading.Thread(
                target=_bg_verify,
                args=(certification.id,),
                daemon=True,
            ).start()
        )
